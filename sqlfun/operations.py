from __future__ import annotations

from django.db.migrations.operations.base import Operation


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

    def __init__(
        self,
        *,
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

    def state_forwards(self, app_label, state):
        pass  # functions do not participate in Django's model state

    def _replaces_incompatible_signature(self) -> bool:
        return self.previous_sql is not None and (
            self.previous_identity_arguments != self.identity_arguments
            or self.previous_result_type != self.result_type
        )

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if self._replaces_incompatible_signature():
            schema_editor.execute(
                f'DROP FUNCTION IF EXISTS '
                f'{self.name}({self.previous_identity_arguments});'
            )
        schema_editor.execute(self.sql)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        schema_editor.execute(
            f'DROP FUNCTION IF EXISTS {self.name}({self.identity_arguments});'
        )
        if self.previous_sql is not None:
            schema_editor.execute(self.previous_sql)

    def describe(self):
        return f'Create or replace function {self.name}({self.identity_arguments})'
