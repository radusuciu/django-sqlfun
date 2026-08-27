import io
from unittest.mock import patch

import pytest
from django.core.management import call_command

from sqlfun import SqlFun
from sqlfun.naming import SqlFunError


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
