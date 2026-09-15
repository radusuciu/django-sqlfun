from __future__ import annotations

import re
from dataclasses import dataclass

import sqlparse

_IDENTIFIER = r'(?:(?:"(?:[^"]|"")*")|[\w$]+)'
_FUNCTION_HEADER_RE = re.compile(
    rf'^\s*CREATE\s+(?:(?P<or_replace>OR\s+REPLACE)\s+)?FUNCTION\s+'
    rf'(?P<name>{_IDENTIFIER}(?:\s*\.\s*{_IDENTIFIER})?)\s*\(',
    re.IGNORECASE,
)


class SqlFunError(Exception):
    """Raised when a function name or signature cannot be resolved from a SQL definition."""


@dataclass(frozen=True)
class FunctionHeader:
    name: str
    or_replace: bool


def _parse_function_header(sql: str) -> FunctionHeader:
    inspection_sql = sqlparse.format(sql, strip_comments=True)
    match = _FUNCTION_HEADER_RE.match(inspection_sql)
    if not match:
        raise SqlFunError(
            'Could not find a CREATE FUNCTION statement with a parenthesized '
            f'parameter list at the start of SQL definition:\n{sql}'
        )
    return FunctionHeader(
        name=re.sub(r'\s*\.\s*', '.', match.group('name').strip()),
        or_replace=match.group('or_replace') is not None,
    )


def extract_function_name(sql: str) -> str:
    """Return the function name declared in a CREATE FUNCTION statement.

    Only the name is extracted; the argument list and return type are resolved
    later by PostgreSQL introspection. Quoted identifiers keep their case and
    quotes; a schema qualifier is joined with a single dot and surrounding
    whitespace removed.
    """
    return _parse_function_header(sql).name
