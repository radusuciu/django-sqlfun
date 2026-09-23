from __future__ import annotations

import importlib
from dataclasses import dataclass

from django.db.migrations.loader import MigrationLoader

from sqlfun.naming import SqlFunError, normalize_identity
from sqlfun.operations import CreateFunction, DropFunction


@dataclass(frozen=True)
class FunctionState:
    sql: str
    identity_arguments: str
    result_type: str
    app_label: str
    # the migration holding this state; a later migration that replaces it
    # from another app must depend on it
    migration_name: str | None = None

    @property
    def node(self) -> tuple[str, str | None]:
        return (self.app_label, self.migration_name)


def _identity(name: str) -> str:
    """Key a replayed operation on the same identity the registry computes.

    Hand-written migrations may spell a name in any case/quoting variant; an
    unparseable one degrades to its raw form rather than breaking replay.
    """
    try:
        return normalize_identity(name)
    except SqlFunError:
        return name


def load_migration_graph() -> MigrationLoader:
    """Load the on-disk migration graph without touching the database.

    Import caches are invalidated first: a FileFinder cached before the base
    makemigrations wrote its files can miss or fail to import them.
    connection=None makes the loader always substitute squashed migrations
    for the ones they replace.
    """
    importlib.invalidate_caches()
    return MigrationLoader(None, ignore_no_migrations=True)


def get_replayed_state(loader: MigrationLoader | None = None) -> dict[str, FunctionState]:
    """Rebuild each function's last known state from the on-disk migration
    graph."""
    if loader is None:
        loader = load_migration_graph()
    graph = loader.graph

    # merge the per-leaf plans into one topological order: forwards_plan
    # lists dependencies before dependents, so nodes already seen from an
    # earlier leaf's plan are always ancestors
    plan = []
    seen = set()
    for leaf in graph.leaf_nodes():
        for node in graph.forwards_plan(leaf):
            if node not in seen:
                seen.add(node)
                plan.append(node)

    state: dict[str, FunctionState] = {}
    for app_label, migration_name in plan:
        migration = loader.get_migration(app_label, migration_name)
        for operation in migration.operations:
            if isinstance(operation, CreateFunction):
                state[_identity(operation.name)] = FunctionState(
                    sql=operation.sql,
                    identity_arguments=operation.identity_arguments,
                    result_type=operation.result_type,
                    app_label=app_label,
                    migration_name=migration_name,
                )
            elif isinstance(operation, DropFunction):
                state.pop(_identity(operation.name), None)
    return state
