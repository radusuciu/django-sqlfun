from __future__ import annotations

import re
from dataclasses import dataclass

from django.db import connection as default_connection
from django.db import transaction

from sqlfun.naming import SqlFunError


@dataclass(frozen=True)
class Signature:
    name: str               # canonical, schema-qualified, PostgreSQL-quoted
    identity_arguments: str  # exactly what DROP FUNCTION expects
    result_type: str

    @property
    def drop_clause(self) -> str:
        return f'{self.name}({self.identity_arguments})'


def _unquote(part: str) -> tuple[str, bool]:
    """Return (bare_identifier, was_quoted) for one dotted name component."""
    part = part.strip()
    if part.startswith('"') and part.endswith('"'):
        return part[1:-1].replace('""', '"'), True
    return part.lower(), False


def _split_qualified(name: str) -> tuple[str | None, str]:
    """Split a possibly schema-qualified name into (schema | None, bare_name),
    unquoting each component to the value stored in pg_proc/pg_namespace."""
    # split on the dot that is not inside double quotes
    match = re.match(r'\s*(?:("[^"]+"|[\w$]+)\s*\.\s*)?("[^"]+"|[\w$]+)\s*$', name)
    if not match:
        raise SqlFunError(f'Could not interpret function name {name!r}')
    schema_raw, bare_raw = match.group(1), match.group(2)
    schema = _unquote(schema_raw)[0] if schema_raw else None
    bare = _unquote(bare_raw)[0]
    return schema, bare


_LOOKUP_SQL = """
    SELECT
        quote_ident(n.nspname) || '.' || quote_ident(p.proname) AS canonical_name,
        pg_get_function_identity_arguments(p.oid) AS identity_arguments,
        pg_get_function_result(p.oid) AS result_type
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE p.proname = %(name)s
      AND (
        (%(schema)s IS NOT NULL AND n.nspname = %(schema)s)
        OR (%(schema)s IS NULL AND n.nspname = ANY (current_schemas(true)))
      )
"""


def introspect_signature(sql: str, extracted_name: str, conn=None) -> Signature:
    """Create the function in a rolled-back savepoint and read its signature
    from the PostgreSQL catalog.

    ``check_function_bodies`` is disabled so only the argument and return types
    must resolve, not the body's referenced tables/views.
    """
    conn = conn or default_connection
    schema, bare = _split_qualified(extracted_name)

    with transaction.atomic(using=conn.alias):
        with conn.cursor() as cursor:
            cursor.execute('SET LOCAL check_function_bodies = off')
            try:
                cursor.execute(sql)
            except Exception as error:  # noqa: BLE001 - re-raised as SqlFunError
                raise SqlFunError(
                    f'PostgreSQL rejected the function definition:\n{sql}\n\n{error}'
                ) from error
            cursor.execute(_LOOKUP_SQL, {'name': bare, 'schema': schema})
            rows = cursor.fetchall()
        transaction.set_rollback(True, using=conn.alias)

    if not rows:
        raise SqlFunError(
            f'No function named {extracted_name!r} was found after creating it from:\n{sql}'
        )
    if len(rows) > 1:
        raise SqlFunError(
            f'Function name {extracted_name!r} is overloaded ({len(rows)} definitions); '
            'overloads are not supported.'
        )
    canonical_name, identity_arguments, result_type = rows[0]
    return Signature(
        name=canonical_name,
        identity_arguments=identity_arguments,
        result_type=result_type,
    )
