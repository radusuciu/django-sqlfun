import pytest

from sqlfun.introspection import Signature, introspect_signature
from sqlfun.naming import SqlFunError, extract_function_name


def _sig(sql):
    return introspect_signature(sql, extract_function_name(sql))


@pytest.mark.django_db
def test_simple_signature():
    sig = _sig('CREATE FUNCTION isig_simple(a integer) RETURNS integer '
               'AS $$ SELECT a; $$ LANGUAGE sql;')
    assert sig.name == 'public.isig_simple'
    assert sig.identity_arguments == 'a integer'
    assert sig.result_type == 'integer'
    assert sig.drop_clause == 'public.isig_simple(a integer)'


@pytest.mark.django_db
def test_type_aliases_are_canonicalized():
    a = _sig('CREATE FUNCTION isig_alias(a int) RETURNS int AS $$ SELECT a; $$ LANGUAGE sql;')
    b = _sig('CREATE FUNCTION isig_alias(a integer) RETURNS integer AS $$ SELECT a; $$ LANGUAGE sql;')
    assert a == b


@pytest.mark.django_db
def test_out_params_without_returns():
    sig = _sig('CREATE FUNCTION isig_out(IN a integer, OUT s integer, OUT p integer) '
               'AS $$ SELECT a, a; $$ LANGUAGE sql;')
    # On modern PostgreSQL, OUT params ARE included in the identity
    # arguments; DROP FUNCTION still succeeds with this full string.
    assert sig.identity_arguments == 'a integer, OUT s integer, OUT p integer'


@pytest.mark.django_db
def test_return_type_named_like_keyword():
    sig = _sig("CREATE FUNCTION isig_cost(a integer) RETURNS numeric "
               "AS $$ SELECT a::numeric; $$ LANGUAGE sql;")
    assert sig.result_type == 'numeric'


@pytest.mark.django_db
def test_body_dependency_not_required():
    # references a table that does not exist; check_function_bodies=off lets it introspect
    sig = _sig('CREATE FUNCTION isig_nodep(a integer) RETURNS integer '
               'AS $$ SELECT a FROM a_missing_table LIMIT 1; $$ LANGUAGE sql;')
    assert sig.identity_arguments == 'a integer'


@pytest.mark.django_db
def test_name_mismatch_raises():
    with pytest.raises(SqlFunError):
        introspect_signature(
            'CREATE FUNCTION isig_real(a integer) RETURNS integer AS $$ SELECT a; $$ LANGUAGE sql;',
            'isig_wrong_name',
        )


@pytest.mark.django_db
def test_introspection_is_rolled_back():
    from django.db import connection
    _sig('CREATE FUNCTION isig_rolledback(a integer) RETURNS integer '
         'AS $$ SELECT a; $$ LANGUAGE sql;')
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM pg_proc WHERE proname = 'isig_rolledback'")
        assert cursor.fetchone()[0] == 0


@pytest.mark.django_db
def test_return_type_change_with_live_function():
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute(
            'CREATE FUNCTION isig_live(a integer) RETURNS integer '
            'AS $$ SELECT a; $$ LANGUAGE sql;'
        )
    sig = _sig(
        'CREATE OR REPLACE FUNCTION isig_live(a integer) RETURNS bigint '
        'AS $$ SELECT a::bigint; $$ LANGUAGE sql;'
    )
    assert sig.result_type == 'bigint'
    assert sig.identity_arguments == 'a integer'


@pytest.mark.django_db
def test_parameter_count_change_with_live_function():
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute(
            'CREATE FUNCTION isig_overload(a integer) RETURNS integer '
            'AS $$ SELECT a; $$ LANGUAGE sql;'
        )
    sig = _sig(
        'CREATE OR REPLACE FUNCTION isig_overload(a integer, b integer) RETURNS integer '
        'AS $$ SELECT a + b; $$ LANGUAGE sql;'
    )
    assert sig.identity_arguments == 'a integer, b integer'


@pytest.mark.django_db
def test_live_function_untouched_after_introspection():
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute(
            'CREATE FUNCTION isig_untouched(a integer) RETURNS integer '
            'AS $$ SELECT a; $$ LANGUAGE sql;'
        )
    _sig(
        'CREATE OR REPLACE FUNCTION isig_untouched(a integer) RETURNS bigint '
        'AS $$ SELECT a::bigint; $$ LANGUAGE sql;'
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_get_function_result(oid) FROM pg_proc WHERE proname = 'isig_untouched'"
        )
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 'integer'
