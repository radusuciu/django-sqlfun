from __future__ import annotations

import re

_CREATE_FUNCTION_NAME_RE = re.compile(
    r'CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+'
    r'(?P<name>(?:"[^"]+"|[\w$]+)(?:\s*\.\s*(?:"[^"]+"|[\w$]+))?)\s*\(',
    re.IGNORECASE,
)


class SqlFunError(Exception):
    """Raised when a function name or signature cannot be resolved from a SQL definition."""


def extract_function_name(sql: str) -> str:
    """Return the function name declared in a CREATE FUNCTION statement.

    Only the name is extracted; the argument list and return type are resolved
    later by PostgreSQL introspection. Quoted identifiers keep their case and
    quotes; a schema qualifier is joined with a single dot and surrounding
    whitespace removed.
    """
    match = _CREATE_FUNCTION_NAME_RE.search(sql)
    if not match:
        raise SqlFunError(
            'Could not find a CREATE FUNCTION statement with a parenthesized '
            f'parameter list in SQL definition:\n{sql}'
        )
    return re.sub(r'\s*\.\s*', '.', match.group('name').strip())


_OR_REPLACE_RE = re.compile(r'CREATE\s+OR\s+REPLACE\s+FUNCTION', re.IGNORECASE)


def ensure_or_replace(sql: str) -> None:
    """Reject plain CREATE FUNCTION definitions.

    sqlfun re-executes definitions against databases where the function may
    already exist (unchanged-function baselines, upgrade re-declarations),
    so every definition must be idempotent via CREATE OR REPLACE.
    """
    if not _OR_REPLACE_RE.search(sql):
        raise SqlFunError(
            'Definition must use CREATE OR REPLACE FUNCTION (plain CREATE '
            'FUNCTION fails when the function already exists).'
        )
