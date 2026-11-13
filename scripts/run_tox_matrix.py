#!/usr/bin/env python3
"""Run every tox environment in one pass.

A temporary PostgreSQL Docker container is started automatically and removed
after the run. Environments are executed sequentially because the test suite
resets shared database schemas. Environments whose Python interpreter is not
installed are skipped and reported in the final summary.

Usage:
    python scripts/run_tox_matrix.py
    python scripts/run_tox_matrix.py --verbose
    python scripts/run_tox_matrix.py --fail-fast
    python scripts/run_tox_matrix.py --no-postgres
    python scripts/run_tox_matrix.py --keep-postgres
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FACTOR = re.compile(r"^py(?P<major>\d)(?P<minor>\d+)")
DEFAULT_POSTGRES_IMAGE = "postgres:18"
DEFAULT_POSTGRES_PORT = 5492


@dataclass
class Result:
    env: str
    status: str
    returncode: int = 0


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


def run_env(env: str, python: str, *, verbose: bool) -> Result:
    command = [
        "tox",
        "-e",
        env,
        "-x",
        f"testenv:{env}.basepython={python}",
    ]

    if verbose:
        proc = subprocess.run(command, cwd=ROOT, check=False)
        return Result(
            env, "passed" if proc.returncode == 0 else "failed", proc.returncode
        )

    proc = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    log_path = ROOT / ".tox" / "matrix" / f"{env}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(proc.stdout + proc.stderr)

    if proc.returncode == 0:
        return Result(env, "passed")

    print(f"\n--- {env} (last 40 lines, full log: {log_path}) ---")
    print("\n".join((proc.stdout + proc.stderr).splitlines()[-40:]))
    return Result(env, "failed", proc.returncode)


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

    name = f"pga-tox-matrix-{os.getpid()}"
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


def stop_postgres(name: str) -> None:
    if docker := shutil.which("docker"):
        subprocess.run([docker, "rm", "-f", name], capture_output=True, check=False)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run all tox environments with available interpreters."
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="stop after the first failing environment",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="stream tox output instead of only printing failures",
    )
    parser.add_argument(
        "--no-postgres",
        action="store_true",
        help="use an existing PostgreSQL server instead of starting a container",
    )
    parser.add_argument(
        "--keep-postgres",
        action="store_true",
        help="leave the PostgreSQL container running after the tests",
    )
    parser.add_argument(
        "--postgres-image",
        default=DEFAULT_POSTGRES_IMAGE,
        help=f"Docker image for PostgreSQL (default: {DEFAULT_POSTGRES_IMAGE})",
    )
    parser.add_argument(
        "--postgres-port",
        type=int,
        default=None,
        help=(
            "Host port for PostgreSQL "
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

    container: str | None = None
    try:
        if not args.no_postgres:
            user = os.environ.get("POSTGRES_USER", "postgres")
            password = os.environ.get("POSTGRES_PASSWORD", "postgres")
            database = os.environ.get("POSTGRES_DB", "pg_audit_test")
            port = args.postgres_port
            if port is None:
                port = int(os.environ.get("POSTGRES_PORT", str(DEFAULT_POSTGRES_PORT)))

            if is_port_in_use(port):
                print(
                    f"error: port {port} is already in use; pass --postgres-port "
                    "with a free port or --no-postgres to use an existing database.",
                    file=sys.stderr,
                )
                return 1

            print(
                f"Starting PostgreSQL ({args.postgres_image}) on localhost:{port} ..."
            )
            try:
                container = start_postgres(
                    args.postgres_image,
                    port,
                    user,
                    password,
                    database,
                    args.postgres_timeout,
                )
            except RuntimeError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1

            os.environ.update(
                {
                    "POSTGRES_USER": user,
                    "POSTGRES_PASSWORD": password,
                    "POSTGRES_DB": database,
                    "POSTGRES_PORT": str(port),
                }
            )
            print(f"PostgreSQL ready on localhost:{port}")

        envs = discover_envs()
        results: list[Result] = []

        for index, env in enumerate(envs, start=1):
            python = find_python(env)
            if python is None:
                print(f"[{index}/{len(envs)}] {env} ... SKIP (no matching interpreter)")
                results.append(Result(env, "skipped"))
                continue

            print(f"[{index}/{len(envs)}] {env} ... ", end="", flush=True)
            result = run_env(env, python, verbose=args.verbose)
            results.append(result)
            print(result.status.upper())

            if result.status == "failed" and args.fail_fast:
                break

        print_summary(results)
        return 1 if any(result.status == "failed" for result in results) else 0
    finally:
        if container is not None:
            if args.keep_postgres:
                print(
                    f"PostgreSQL container {container} left running on "
                    f"localhost:{os.environ['POSTGRES_PORT']}."
                )
            else:
                stop_postgres(container)


if __name__ == "__main__":
    raise SystemExit(main())
