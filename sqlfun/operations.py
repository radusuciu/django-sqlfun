from __future__ import annotations

from django.db import router
from django.db.migrations.operations.base import Operation


def _drop_statement(name: str, identity_arguments: str) -> str:
    return f'DROP FUNCTION IF EXISTS {name}({identity_arguments});'


class CreateFunction(Operation):
    """Create or replace a PostgreSQL function.

    Carries the previous definition when replacing an existing one: an
    incompatible previous signature (identity arguments or result type)
    must be dropped first because CREATE OR REPLACE cannot change either,
    and reverse migration restores the previous definition. Replay-based
    change detection reads these attributes back from migration files, so
    they are the persistent record of the function's state.
    """

    reversible = True

    # NB: no keyword-only marker -- Django's OperationWriter serializes only
    # the parameters django.utils.inspect.get_func_args reports, and before
    # Django 5.0 that excludes keyword-only ones, so the written migration
    # would call CreateFunction() with no arguments at all.
    def __init__(
        self,
        name: str,
        identity_arguments: str,
        result_type: str,
        sql: str,
        previous_sql: str | None = None,
        previous_identity_arguments: str | None = None,
        previous_result_type: str | None = None,
    ):
        self.name = name
        self.identity_arguments = identity_arguments
        self.result_type = result_type
        self.sql = sql
        self.previous_sql = previous_sql
        self.previous_identity_arguments = previous_identity_arguments
        self.previous_result_type = previous_result_type

        previous_values = {
            'previous_sql': previous_sql,
            'previous_identity_arguments': previous_identity_arguments,
            'previous_result_type': previous_result_type,
        }
        missing = sorted(key for key, value in previous_values.items() if value is None)
        if missing and len(missing) != len(previous_values):
            raise ValueError(
                'CreateFunction previous_* arguments must be provided '
                f"together; missing: {', '.join(missing)}"
            )

    def state_forwards(self, app_label, state):
        pass  # functions do not participate in Django's model state

    def _replaces_incompatible_signature(self) -> bool:
        return self.previous_sql is not None and (
            self.previous_identity_arguments != self.identity_arguments
            or self.previous_result_type != self.result_type
        )

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if not router.allow_migrate(schema_editor.connection.alias, app_label):
            return
        if self._replaces_incompatible_signature():
            schema_editor.execute(
                _drop_statement(self.name, self.previous_identity_arguments)
            )
        schema_editor.execute(self.sql)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        if not router.allow_migrate(schema_editor.connection.alias, app_label):
            return
        schema_editor.execute(_drop_statement(self.name, self.identity_arguments))
        if self.previous_sql is not None:
            schema_editor.execute(self.previous_sql)

    def describe(self):
        return f'Create or replace function {self.name}({self.identity_arguments})'


class DropFunction(Operation):
    """Drop a PostgreSQL function that is no longer registered.

    ``sql`` is the dropped definition, kept so the operation can reverse.
    """

    reversible = True

    def __init__(self, name: str, identity_arguments: str, sql: str):
        self.name = name
        self.identity_arguments = identity_arguments
        self.sql = sql

    def state_forwards(self, app_label, state):
        pass

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if not router.allow_migrate(schema_editor.connection.alias, app_label):
            return
        schema_editor.execute(_drop_statement(self.name, self.identity_arguments))

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        if not router.allow_migrate(schema_editor.connection.alias, app_label):
            return
        schema_editor.execute(self.sql)

    def describe(self):
        return f'Drop function {self.name}({self.identity_arguments})'
