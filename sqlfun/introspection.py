from __future__ import annotations

from dataclasses import dataclass

from django.db import DatabaseError, OperationalError, transaction
from django.db import connection as default_connection

from sqlfun.naming import SqlFunError, split_qualified


@dataclass(frozen=True)
class Signature:
    identity_arguments: str  # exactly what DROP FUNCTION expects
    result_type: str


# Predicate shared by _LOOKUP_SQL and _EXISTING_DROPS_SQL so the two can
# never drift apart. PostgreSQL creates an unqualified function in
# current_schema(), so same-named functions in later search-path schemas are
# unrelated and must not be treated as overloads of the candidate.
_NAME_MATCH_SQL = """
    p.proname = %(name)s
      AND (
        (%(schema)s IS NOT NULL AND n.nspname = %(schema)s)
        OR (
          %(schema)s IS NULL
          AND n.nspname = current_schema()
        )
      )
"""

_LOOKUP_SQL = f"""
    SELECT p.oid
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE {_NAME_MATCH_SQL}
"""

_SIGNATURE_SQL = """
    SELECT
        pg_get_function_identity_arguments(%(oid)s),
        pg_get_function_result(%(oid)s)
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
_EXISTING_DROPS_SQL = f"""
    SELECT format(
        'DROP FUNCTION %%I.%%I(%%s)',
        n.nspname, p.proname, pg_get_function_identity_arguments(p.oid)
    )
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE {_NAME_MATCH_SQL}
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
    matches = cursor.fetchall()
    if len(matches) != 1:
        return matches

    (oid,) = matches[0]
    # The pg_get_function_* deparsers omit a type's schema whenever it is
    # visible on search_path. These strings are persisted into migrations and
    # later used in DROP FUNCTION, so make their rendering portable across
    # environments by exposing only pg_catalog while deparsing. The function
    # OID was resolved above under the caller's original search_path.
    cursor.execute('SET LOCAL search_path = pg_catalog')
    cursor.execute(_SIGNATURE_SQL, {'oid': oid})
    identity_arguments, result_type = cursor.fetchone()
    return [(identity_arguments, result_type)]


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
    schema, bare = split_qualified(extracted_name)

    with transaction.atomic(using=conn.alias):
        with conn.cursor() as cursor:
            cursor.execute('SET LOCAL check_function_bodies = off')

            rows = None
            try:
                with transaction.atomic(using=conn.alias):
                    rows = _create_and_lookup(cursor, sql, bare, schema)
                    if len(rows) != 1:
                        raise _CollisionDetected
            except _CollisionDetected:
                pass
            except OperationalError:
                # a lost connection or timeout says nothing about the
                # definition; retrying would blame the user's SQL for it
                raise
            except DatabaseError:
                pass  # PostgreSQL rejected the definition: retry via ATTEMPT 2

            if rows is None or len(rows) != 1:
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
    identity_arguments, result_type = rows[0]
    return Signature(
        identity_arguments=identity_arguments,
        result_type=result_type,
    )
