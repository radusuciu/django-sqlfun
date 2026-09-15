import io
from unittest.mock import patch

import pytest
from django.core.management import call_command

from sqlfun import SqlFun
from sqlfun.introspection import introspect_signature as real_introspect_signature
from sqlfun.naming import SqlFunError
from sqlfun.utils import make_sqlfun_migrations


@pytest.mark.django_db(databases=['default', 'secondary'])
def test_database_option_reaches_introspection():
    class DbProbe(SqlFun):
        app_label = 'test_project'
        sql = """
            CREATE OR REPLACE FUNCTION db_probe(
                first integer
            ) RETURNS integer AS $$
            SELECT first;
            $$ LANGUAGE sql IMMUTABLE;
        """

    seen_aliases = []

    def capture(sql, name, conn=None):
        seen_aliases.append(conn.alias)
        raise SqlFunError('stop after capturing the alias')

    try:
        with patch('sqlfun.utils.introspect_signature', side_effect=capture):
            with pytest.raises(Exception):
                call_command(
                    'makemigrations', '--database', 'secondary',
                    stderr=io.StringIO(), stdout=io.StringIO(),
                )
        assert seen_aliases == ['secondary']
    finally:
        DbProbe.deregister()


@pytest.mark.django_db(databases=['default', 'secondary'])
def test_database_option_reaches_post_write_bookkeeping():
    class BookkeepingProbe(SqlFun):
        app_label = 'test_project'
        sql = """
            CREATE OR REPLACE FUNCTION bookkeeping_probe(
                value integer
            ) RETURNS integer AS $$
            SELECT value;
            $$ LANGUAGE sql IMMUTABLE;
        """

    seen_aliases = []
    migration_paths = []

    def capture(sql, name, conn=None):
        seen_aliases.append(conn.alias)
        return real_introspect_signature(sql, name, conn=conn)

    try:
        with patch('sqlfun.utils.introspect_signature', side_effect=capture):
            migration_paths = make_sqlfun_migrations(
                'database_bookkeeping', database='secondary'
            )

        assert migration_paths
        assert len(seen_aliases) == len(SqlFun._registry) * 2
        assert set(seen_aliases) == {'secondary'}
    finally:
        BookkeepingProbe.deregister()
        for path in migration_paths:
            path.unlink(missing_ok=True)
