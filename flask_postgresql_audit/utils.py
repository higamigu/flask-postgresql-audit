import os
import re
import string

ROOT_PATH = os.path.dirname(os.path.abspath(__file__))
SQL_DEFINITION_PATTERN = re.compile(
    r"""
    # Group 'type': Capture the start statement (e.g., CREATE FUNCTION)
    ^\s*(?P<type>CREATE\s+(?:OR\s+REPLACE\s+)?(?:FUNCTION|PROCEDURE|TRIGGER))
    # Group 'signature': Capture the full signature (for functions/procedures)
    \s+(?P<signature>(?:[a-zA-Z0-9_."$]+\s*\([^;]*?\))|[a-zA-Z0-9_."$]+)
    # Group 'definition': The entire body of the definition.
    (?P<definition>[\s\S]*)
    """,
    re.IGNORECASE | re.DOTALL | re.MULTILINE | re.VERBOSE,
)


def load_template(tmpl_name: str):
    with open(os.path.join(ROOT_PATH, f"templates/{tmpl_name}")) as f:
        s = f.read()
    return string.Template(s.replace("$$", "$$$$"))


def parse_template(tmpl_name: str, **context):
    sql = load_template(tmpl_name).substitute(**context).strip()
    res = SQL_DEFINITION_PATTERN.search(sql)
    if not res:
        return {}
    return {k: v.strip() for k, v in res.groupdict().items()}
