import pathlib
import sys

from django.apps import apps as django_apps
from django.db import connection


def function_exists(function_name):
    with connection.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) FROM information_schema.routines WHERE routine_name = %s', [function_name])
        return cursor.fetchone()[0] == 1


def migrations_dir(app_label: str) -> pathlib.Path:
    return pathlib.Path(django_apps.get_app_config(app_label).path) / 'migrations'


def write_test_migration(app_label: str, name: str, content: str) -> pathlib.Path:
    """Write a migration file for a test. ``name`` must be unique across the
    whole suite: migration modules stay cached in sys.modules, so a reused
    name would serve a previous test's content."""
    path = migrations_dir(app_label) / f'{name}.py'
    path.write_text(content)
    return path


def remove_test_migration(app_label: str, path: pathlib.Path) -> None:
    path.unlink(missing_ok=True)
    module_name = f'{django_apps.get_app_config(app_label).name}.migrations.{path.stem}'
    sys.modules.pop(module_name, None)
