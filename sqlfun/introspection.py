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

# Used by ATTEMPT 2 (see introspect_signature) to clear out any existing
# same-name function(s) BEFORE executing the candidate CREATE OR REPLACE,
# once ATTEMPT 1 (no drop) has shown that a live function with an
# incompatible signature is in the way - it either caused the new
# definition to be rejected (return type / parameter rename changes) or made
# it coexist as a second overload (parameter added / type changed), neither
# of which reflects the signature the caller is trying to introspect. The
# DROP statements are built server-side via format(... %I ...), so they are
# safe to execute as-is.
_EXISTING_DROPS_SQL = """
    SELECT format(
        'DROP FUNCTION %%I.%%I(%%s)',
        n.nspname, p.proname, pg_get_function_identity_arguments(p.oid)
    )
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE p.proname = %(name)s
      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND (
        (%(schema)s IS NOT NULL AND n.nspname = %(schema)s)
        OR (%(schema)s IS NULL AND n.nspname = ANY (current_schemas(true)))
      )
"""


class _CollisionDetected(Exception):
    """Internal sentinel: ATTEMPT 1 (no drop) produced more than one row,
    meaning a live same-name function with an incompatible signature
    coexists with the new one as an overload. Raising this inside the
    ATTEMPT 1 savepoint discards that transient overload so ATTEMPT 2 can
    retry from a clean slate."""


def _create_and_lookup(cursor, sql: str, name: str, schema: str | None) -> list[tuple]:
    """Execute the candidate definition and look up its signature. Used by
    both attempts; the caller is responsible for wrapping this in its own
    savepoint so a failure here can be discarded independently."""
    cursor.execute(sql)
    cursor.execute(_LOOKUP_SQL, {'name': name, 'schema': schema})
    return cursor.fetchall()


def introspect_signature(sql: str, extracted_name: str, conn=None) -> Signature:
    """Create the function in a rolled-back savepoint and read its signature
    from the PostgreSQL catalog.

    ``check_function_bodies`` is disabled so only the argument and return types
    must resolve, not the body's referenced tables/views.

    Two attempts are made, both inside the outer rolled-back transaction:

    ATTEMPT 1 runs the candidate definition as-is, with no drop. This is the
    common case (new function, unchanged signature, body-only change) and,
    critically, never drops anything - so a function with dependent views or
    other objects introspects successfully as long as its signature is not
    actually changing.

    ATTEMPT 2 only runs if ATTEMPT 1 fails to produce exactly one signature:
    either PostgreSQL rejected the new definition outright (e.g. "cannot
    change return type of existing function"), or the new definition landed
    as a second overload alongside the live, incompatible one. ATTEMPT 2
    drops any existing same-name function(s) first, then retries; if it
    still fails (e.g. the drop itself is blocked by a dependent view), that
    failure is surfaced to the caller as a genuine, expected error.
    """
    conn = conn or default_connection
    schema, bare = _split_qualified(extracted_name)

    with transaction.atomic(using=conn.alias):
        with conn.cursor() as cursor:
            cursor.execute('SET LOCAL check_function_bodies = off')

            rows = None
            try:
                with transaction.atomic(using=conn.alias):
                    rows = _create_and_lookup(cursor, sql, bare, schema)
                    if len(rows) > 1:
                        rows = None
                        raise _CollisionDetected
            except Exception:  # noqa: BLE001 - both DB rejection and _CollisionDetected retry via ATTEMPT 2
                pass

            if rows is None:
                try:
                    with transaction.atomic(using=conn.alias):
                        cursor.execute(_EXISTING_DROPS_SQL, {'name': bare, 'schema': schema})
                        for (drop_stmt,) in cursor.fetchall():
                            cursor.execute(drop_stmt)
                        rows = _create_and_lookup(cursor, sql, bare, schema)
                except Exception as error:  # noqa: BLE001 - re-raised as SqlFunError
                    raise SqlFunError(
                        f'PostgreSQL rejected the function definition:\n{sql}\n\n{error}'
                    ) from error
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
