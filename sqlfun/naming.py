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


class SqlFunConfigurationError(SqlFunError):
    """Raised when the setup itself is wrong -- an unresolvable app label, a
    migration target that cannot be written to, two classes claiming one
    identity. Distinct from a signature that failed to resolve, because no
    amount of running `migrate` will fix it."""


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


def ensure_or_replace(sql: str) -> None:
    """Reject plain CREATE FUNCTION definitions.

    sqlfun re-executes definitions against databases where the function may
    already exist (unchanged-function baselines, upgrade re-declarations),
    so every definition must be idempotent via CREATE OR REPLACE.
    """
    if not _parse_function_header(sql).or_replace:
        raise SqlFunError(
            'Definition must use CREATE OR REPLACE FUNCTION (plain CREATE '
            'FUNCTION fails when the function already exists).'
        )


# PostgreSQL's downcase_identifier folds only ASCII letters in multibyte
# encodings; str.lower() would also fold e.g. 'É', naming a different object.
_ASCII_LOWER = str.maketrans(
    'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'
)


def _unquote(part: str) -> tuple[str, bool]:
    """Return (bare_identifier, was_quoted) for one dotted name component."""
    part = part.strip()
    if part.startswith('"') and part.endswith('"'):
        return part[1:-1].replace('""', '"'), True
    return part.translate(_ASCII_LOWER), False


def split_qualified(name: str) -> tuple[str | None, str]:
    """Split a possibly schema-qualified name into (schema | None, bare_name),
    unquoting each component to the value stored in pg_proc/pg_namespace."""
    match = re.match(r'\s*(?:("(?:[^"]|"")*"|[\w$]+)\s*\.\s*)?("(?:[^"]|"")*"|[\w$]+)\s*$', name)
    if not match:
        raise SqlFunError(f'Could not interpret function name {name!r}')
    schema_raw, bare_raw = match.group(1), match.group(2)
    schema = _unquote(schema_raw)[0] if schema_raw else None
    bare = _unquote(bare_raw)[0]
    return schema, bare


_SAFE_IDENTIFIER_RE = re.compile(r'^[a-z_][a-z0-9_$]*$')


def _render_identifier(part: str) -> str:
    if _SAFE_IDENTIFIER_RE.match(part):
        return part
    escaped = part.replace('"', '""')
    return f'"{escaped}"'


def normalize_identity(name: str) -> str:
    """Canonical as-written identity of a function name.

    The persistent identity is the name exactly as the user wrote it —
    unqualified names stay unqualified so the target database's search_path
    resolves them at migrate time, the same rule the CREATE itself follows.
    Components are case-folded/unquoted per PostgreSQL identifier rules and
    re-quoted only where required, so 'My_Fn', my_fn and "my_fn" are one
    identity while "MyFn" stays distinct.
    """
    schema, bare = split_qualified(name)
    rendered = _render_identifier(bare)
    if schema is not None:
        return f'{_render_identifier(schema)}.{rendered}'
    return rendered
