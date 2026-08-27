from __future__ import annotations

import re

_CREATE_FUNCTION_NAME_RE = re.compile(
    r'CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+'
    r'(?P<name>(?:"[^"]+"|[\w$]+)(?:\s*\.\s*(?:"[^"]+"|[\w$]+))?)\s*\(',
    re.IGNORECASE,
)


class SqlFunError(Exception):
    """Raised when a function name or signature cannot be resolved from a SQL definition."""


class SqlFunConfigurationError(SqlFunError):
    """Raised when the setup itself is wrong -- an unresolvable app label, a
    migration target that cannot be written to, two classes claiming one
    identity. Distinct from a signature that failed to resolve, because no
    amount of running `migrate` will fix it."""


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


def _unquote(part: str) -> tuple[str, bool]:
    """Return (bare_identifier, was_quoted) for one dotted name component."""
    part = part.strip()
    if part.startswith('"') and part.endswith('"'):
        return part[1:-1].replace('""', '"'), True
    return part.lower(), False


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
