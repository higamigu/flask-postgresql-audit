#!/usr/bin/env python3
"""Run every tox environment in one pass.

A temporary PostgreSQL Docker container is started for each `pgXX` factor in
the tox environment names. Environments are distributed across a bounded pool
of workers, and every worker uses its own database so concurrent runs cannot
reset each other's schemas.

Usage:
    python scripts/run_tox_matrix.py
    python scripts/run_tox_matrix.py --workers 4
    python scripts/run_tox_matrix.py --verbose
    python scripts/run_tox_matrix.py --fail-fast
    python scripts/run_tox_matrix.py --no-postgres
    python scripts/run_tox_matrix.py --keep-postgres
"""

from __future__ import annotations

import argparse
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FACTOR = re.compile(r"^py(?P<major>\d)(?P<minor>\d+)")
PG_FACTOR = re.compile(r"(?:^|-)(?:pg)(?P<version>\d+)(?:-|$)")
DEFAULT_POSTGRES_VERSION = "18"
DEFAULT_POSTGRES_PORT = 5492
DEFAULT_WORKERS = 4
MIGRATIONS_SOURCE = ROOT / "tests" / "migrations"
MIGRATIONS_WORK_ROOT = ROOT / ".tox" / "matrix" / "migrations"


@dataclass
class Result:
    env: str
    status: str
    returncode: int = 0
    log_path: Path | None = None
    output: str = ""


def discover_envs() -> list[str]:
    try:
        proc = subprocess.run(
            ["tox", "-l"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        print("tox is not installed; run `pip install tox` first.", file=sys.stderr)
        raise SystemExit(1)

    if proc.returncode != 0:
        print(proc.stdout, end="", file=sys.stderr)
        print(proc.stderr, end="", file=sys.stderr)
        raise SystemExit(proc.returncode)

    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def postgres_version(env: str) -> str:
    match = PG_FACTOR.search(env)
    return match.group("version") if match else DEFAULT_POSTGRES_VERSION


def group_envs(envs: list[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for env in envs:
        groups.setdefault(postgres_version(env), []).append(env)
    return groups


def is_usable(path: str, version: str) -> bool:
    proc = subprocess.run(
        [
            path,
            "-c",
            "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0 and proc.stdout.strip() == version


def find_python(env: str) -> str | None:
    match = VERSION_FACTOR.match(env)
    if not match:
        return None

    version = f"{match.group('major')}.{match.group('minor')}"
    executable = f"python{version}"

    if (path := shutil.which(executable)) and is_usable(path, version):
        return path

    if uv := shutil.which("uv"):
        proc = subprocess.run(
            [uv, "python", "find", version],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            path = proc.stdout.strip()
            if is_usable(path, version):
                return path

    if mise := shutil.which("mise"):
        proc = subprocess.run(
            [
                mise,
                "exec",
                f"python@{version}",
                "--",
                "python",
                "-c",
                "import sys; print(sys.executable)",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            path = proc.stdout.strip()
            if is_usable(path, version):
                return path

    return None


def run_env(
    env: str,
    python: str,
    *,
    verbose: bool,
    env_vars: dict[str, str],
) -> Result:
    command = [
        "tox",
        "-e",
        env,
        "-x",
        f"testenv:{env}.basepython={python}",
    ]
    process_env = {**os.environ, **env_vars}

    if verbose:
        proc = subprocess.run(command, cwd=ROOT, env=process_env, check=False)
        return Result(
            env, "passed" if proc.returncode == 0 else "failed", proc.returncode
        )

    proc = subprocess.run(
        command,
        cwd=ROOT,
        env=process_env,
        capture_output=True,
        text=True,
        check=False,
    )

    output = proc.stdout + proc.stderr
    log_path = ROOT / ".tox" / "matrix" / f"{env}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(output)

    status = "passed" if proc.returncode == 0 else "failed"
    return Result(env, status, proc.returncode, log_path, output)


def report(result: Result, completed: int, total: int) -> None:
    print(f"[{completed}/{total}] {result.env} ... {result.status.upper()}")
    if result.status == "failed" and result.output:
        print(f"--- {result.env} (last 40 lines, full log: {result.log_path}) ---")
        print("\n".join(result.output.splitlines()[-40:]))


def print_summary(results: list[Result]) -> None:
    groups = {
        "passed": [r.env for r in results if r.status == "passed"],
        "skipped": [r.env for r in results if r.status == "skipped"],
        "failed": [r.env for r in results if r.status == "failed"],
    }

    print("\nSummary")
    print("=======")
    for status in ("passed", "skipped", "failed"):
        envs = groups[status]
        print(f"{status.capitalize():>8}: {len(envs)}")
        for env in envs:
            print(f"          {env}")


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def wait_for_postgres(
    docker: str,
    name: str,
    user: str,
    database: str,
    timeout: float,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready = subprocess.run(
            [docker, "exec", name, "pg_isready", "-U", user, "-d", database],
            capture_output=True,
            text=True,
            check=False,
        )
        if ready.returncode == 0:
            return

        running = subprocess.run(
            [docker, "inspect", "-f", "{{.State.Running}}", name],
            capture_output=True,
            text=True,
            check=False,
        )
        if running.returncode != 0 or running.stdout.strip() != "true":
            raise RuntimeError("PostgreSQL container exited before becoming ready.")

        time.sleep(0.5)

    raise TimeoutError(f"PostgreSQL did not become ready within {timeout:.0f} seconds.")


def start_postgres(
    image: str,
    version: str,
    port: int,
    user: str,
    password: str,
    database: str,
    timeout: float,
) -> str:
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError(
            "docker is not installed; pass --no-postgres to use an existing database."
        )

    name = f"pga-tox-matrix-{os.getpid()}-pg{version}"
    proc = subprocess.run(
        [
            docker,
            "run",
            "--rm",
            "-d",
            "--name",
            name,
            "-e",
            f"POSTGRES_USER={user}",
            "-e",
            f"POSTGRES_PASSWORD={password}",
            "-e",
            f"POSTGRES_DB={database}",
            "-p",
            f"127.0.0.1:{port}:5432",
            image,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or "docker run failed"
        raise RuntimeError(message)

    try:
        wait_for_postgres(docker, name, user, database, timeout)
    except (RuntimeError, TimeoutError):
        logs = subprocess.run(
            [docker, "logs", "--tail", "40", name],
            capture_output=True,
            text=True,
            check=False,
        )
        subprocess.run([docker, "rm", "-f", name], capture_output=True, check=False)
        output = (logs.stdout + logs.stderr).strip()
        raise RuntimeError(f"Failed to start PostgreSQL.\n{output}".strip())

    return name


def ensure_database(container: str, user: str, database: str) -> None:
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("docker is not installed")

    proc = subprocess.run(
        [docker, "exec", container, "createdb", "-U", user, database],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 and "already exists" not in proc.stderr.lower():
        message = proc.stderr.strip() or proc.stdout.strip()
        raise RuntimeError(f"Failed to create database {database}: {message}")


def worker_database(base: str, worker: int) -> str:
    return f"{base[:50]}_w{worker}"


def prepare_migrations(workers: int) -> dict[int, Path]:
    if MIGRATIONS_WORK_ROOT.exists():
        shutil.rmtree(MIGRATIONS_WORK_ROOT)

    paths: dict[int, Path] = {}
    for worker in range(workers):
        destination = MIGRATIONS_WORK_ROOT / f"w{worker}"
        shutil.copytree(
            MIGRATIONS_SOURCE,
            destination,
            ignore=shutil.ignore_patterns("versions", "__pycache__"),
        )
        paths[worker] = destination
    return paths


def stop_postgres(name: str) -> None:
    if docker := shutil.which("docker"):
        subprocess.run([docker, "rm", "-f", name], capture_output=True, check=False)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run all tox environments with available interpreters."
    )
    parser.add_argument(
        "-j",
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=(
            "number of parallel workers, capped by the number of PostgreSQL "
            f"containers (default: {DEFAULT_WORKERS})"
        ),
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="stop after the first failing environment (runs sequentially)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="stream tox output instead of only printing failures",
    )
    parser.add_argument(
        "--no-postgres",
        action="store_true",
        help=(
            "use an existing PostgreSQL server instead of starting containers; "
            "runs sequentially because all environments share one database"
        ),
    )
    parser.add_argument(
        "--keep-postgres",
        action="store_true",
        help="leave the PostgreSQL containers running after the tests",
    )
    parser.add_argument(
        "--postgres-image",
        default=None,
        help=(
            "override the Docker image for every PostgreSQL version "
            "(default: postgres:<pg version>)"
        ),
    )
    parser.add_argument(
        "--postgres-port",
        type=int,
        default=None,
        help=(
            "base host port for PostgreSQL; each version uses the next port "
            f"(default: $POSTGRES_PORT or {DEFAULT_POSTGRES_PORT})"
        ),
    )
    parser.add_argument(
        "--postgres-timeout",
        type=float,
        default=60.0,
        help="Seconds to wait for PostgreSQL to become ready (default: 60)",
    )
    args = parser.parse_args()

    if args.workers < 1:
        parser.error("--workers must be at least 1")

    workers = args.workers
    if args.no_postgres and workers > 1:
        print("warning: --no-postgres uses one database; forcing --workers 1.")
        workers = 1
    if args.fail_fast and workers > 1:
        print("warning: --fail-fast runs sequentially; forcing --workers 1.")
        workers = 1

    running: list[tuple[str, int]] = []
    try:
        envs = discover_envs()
        groups = group_envs(envs)
        results: dict[str, Result] = {}
        runnable: list[tuple[str, str]] = []

        for env in envs:
            python = find_python(env)
            if python is None:
                results[env] = Result(env, "skipped")
            else:
                runnable.append((env, python))

        for env in envs:
            if env in results:
                print(f"{env} ... SKIP (no matching interpreter)")

        user = os.environ.get("POSTGRES_USER", "postgres")
        password = os.environ.get("POSTGRES_PASSWORD", "postgres")
        database = os.environ.get("POSTGRES_DB", "pg_audit_test")
        containers: dict[str, tuple[str, int]] = {}

        if not args.no_postgres:
            needed_versions = {postgres_version(env) for env, _ in runnable}
            max_useful_workers = max(1, len(needed_versions))
            if workers > max_useful_workers:
                print(
                    f"warning: --workers {workers} exceeds the number of "
                    f"PostgreSQL containers ({max_useful_workers}); extra workers "
                    f"will not improve throughput. Capping to {max_useful_workers}."
                )
                workers = max_useful_workers

            base_port = args.postgres_port
            if base_port is None:
                base_port = int(
                    os.environ.get("POSTGRES_PORT", str(DEFAULT_POSTGRES_PORT))
                )

            for offset, version in enumerate(groups):
                if version not in needed_versions:
                    continue

                port = base_port + offset
                image = args.postgres_image or f"postgres:{version}"

                if is_port_in_use(port):
                    print(
                        f"error: port {port} is already in use; pass --postgres-port "
                        "with a free base port or --no-postgres to use an existing "
                        "database.",
                        file=sys.stderr,
                    )
                    return 1

                print(
                    f"Starting PostgreSQL {version} ({image}) on localhost:{port} ..."
                )
                try:
                    container = start_postgres(
                        image,
                        version,
                        port,
                        user,
                        password,
                        database,
                        args.postgres_timeout,
                    )
                except RuntimeError as exc:
                    print(f"error: {exc}", file=sys.stderr)
                    return 1

                containers[version] = (container, port)
                running.append((container, port))
                print(f"PostgreSQL {version} ready on localhost:{port}")

            for container, _port in containers.values():
                for worker in range(workers):
                    ensure_database(
                        container,
                        user,
                        worker_database(database, worker),
                    )

        if args.verbose and workers > 1:
            print("warning: verbose output may interleave across workers.")

        migration_dirs = {} if args.no_postgres else prepare_migrations(workers)

        def env_vars_for(env: str, worker: int) -> dict[str, str]:
            if args.no_postgres:
                return {}
            version = postgres_version(env)
            _container, port = containers[version]
            return {
                "POSTGRES_USER": user,
                "POSTGRES_PASSWORD": password,
                "POSTGRES_DB": worker_database(database, worker),
                "POSTGRES_PORT": str(port),
                "ALEMBIC_CONFIG": str(migration_dirs[worker]),
                "PYTHONDONTWRITEBYTECODE": "1",
            }

        total = len(envs)
        completed = len(results)
        failed = False

        if workers == 1:
            for env, python in runnable:
                result = run_env(
                    env,
                    python,
                    verbose=args.verbose,
                    env_vars=env_vars_for(env, 0),
                )
                results[env] = result
                completed += 1
                report(result, completed, total)
                if result.status == "failed":
                    failed = True
                    if args.fail_fast:
                        break
        else:
            slots: queue.Queue[int] = queue.Queue()
            for worker in range(workers):
                slots.put(worker)

            def task(env: str, python: str) -> Result:
                worker = slots.get()
                try:
                    return run_env(
                        env,
                        python,
                        verbose=args.verbose,
                        env_vars=env_vars_for(env, worker),
                    )
                finally:
                    slots.put(worker)

            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(task, env, python): env for env, python in runnable
                }
                for future in as_completed(futures):
                    result = future.result()
                    results[result.env] = result
                    completed += 1
                    report(result, completed, total)
                    if result.status == "failed":
                        failed = True

        ordered_results = [results[env] for env in envs if env in results]
        print_summary(ordered_results)

        if failed or any(result.status == "failed" for result in ordered_results):
            return 1
        return 0
    finally:
        for name, port in running:
            if args.keep_postgres:
                print(f"PostgreSQL container {name} left running on localhost:{port}.")
            else:
                stop_postgres(name)


if __name__ == "__main__":
    raise SystemExit(main())
