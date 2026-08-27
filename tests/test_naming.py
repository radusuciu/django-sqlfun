import pytest

from sqlfun.naming import SqlFunError, extract_function_name, ensure_or_replace, normalize_identity


@pytest.mark.parametrize('sql, expected', [
    ('CREATE FUNCTION foo(a int) RETURNS int AS $$ SELECT a; $$ LANGUAGE sql;', 'foo'),
    ('create or replace function Bar (a int) returns int as $$ select a; $$ language sql;', 'Bar'),
    ('CREATE FUNCTION public.my_func(a int) RETURNS int AS $$ SELECT a; $$ LANGUAGE sql;', 'public.my_func'),
    ('CREATE FUNCTION "MixedCase"("Arg" int) RETURNS int AS $$ SELECT 1; $$ LANGUAGE sql;', '"MixedCase"'),
    ('CREATE FUNCTION public . spaced (a int) RETURNS int AS $$ SELECT a; $$ LANGUAGE sql;', 'public.spaced'),
    ('CREATE FUNCTION nullary() RETURNS int AS $$ SELECT 1; $$ LANGUAGE sql;', 'nullary'),
])
def test_extracts_name(sql, expected):
    assert extract_function_name(sql) == expected


def test_missing_create_function_raises():
    with pytest.raises(SqlFunError):
        extract_function_name('SELECT 1;')


def test_missing_parameter_list_raises():
    with pytest.raises(SqlFunError):
        extract_function_name('CREATE FUNCTION broken RETURNS int AS $$ SELECT 1; $$;')


def test_class_name_extraction():
    from sqlfun import SqlFun

    class SchemaQualified(SqlFun):
        app_label = 'test_project'
        sql = 'CREATE FUNCTION public.core_probe(a int) RETURNS int AS $$ SELECT a; $$ LANGUAGE sql;'

    try:
        assert SchemaQualified.get_function_name_from_sql() == 'public.core_probe'
    finally:
        SchemaQualified.deregister()


def test_class_name_extraction_error_names_class():
    from sqlfun import SqlFun
    from sqlfun.naming import SqlFunError

    class Broken(SqlFun):
        app_label = 'test_project'
        sql = 'CREATE FUNCTION broken_no_parens RETURNS int'

    try:
        with pytest.raises(SqlFunError, match='Broken'):
            Broken.get_function_name_from_sql()
    finally:
        Broken.deregister()


def test_ensure_or_replace_accepts_or_replace():
    ensure_or_replace(
        'CREATE OR REPLACE FUNCTION ok_fn(a int) RETURNS int '
        'AS $$ SELECT a; $$ LANGUAGE sql;'
    )


def test_ensure_or_replace_rejects_plain_create():
    with pytest.raises(SqlFunError, match='OR REPLACE'):
        ensure_or_replace(
            'CREATE FUNCTION plain_fn(a int) RETURNS int '
            'AS $$ SELECT a; $$ LANGUAGE sql;'
        )


@pytest.mark.django_db
def test_registered_class_without_or_replace_fails_makemigrations():
    from django.core.management import call_command
    from django.core.management.base import CommandError

    from sqlfun import SqlFun

    class PlainCreate(SqlFun):
        app_label = 'test_project'
        sql = (
            'CREATE FUNCTION plain_create_fn(a integer) RETURNS integer '
            'AS $$ SELECT a; $$ LANGUAGE sql;'
        )

    try:
        with pytest.raises(CommandError, match='PlainCreate'):
            call_command('makemigrations', 'test_project', '--dry-run')
    finally:
        PlainCreate.deregister()


def test_identity_unqualified_stays_unqualified():
    assert normalize_identity('my_fn') == 'my_fn'


def test_identity_case_folds_unquoted_names():
    assert normalize_identity('My_Fn') == 'my_fn'


def test_identity_keeps_explicit_schema():
    assert normalize_identity('billing.fn') == 'billing.fn'
    assert normalize_identity('Billing . Fn') == 'billing.fn'


def test_identity_preserves_quoted_case():
    assert normalize_identity('"MyFn"') == '"MyFn"'
    assert normalize_identity('"My Schema"."MyFn"') == '"My Schema"."MyFn"'


def test_identity_unquotes_safe_quoted_names():
    # '"my_fn"' and 'my_fn' are the same object in PostgreSQL
    assert normalize_identity('"my_fn"') == 'my_fn'


def test_identity_requotes_embedded_quotes():
    assert normalize_identity('"a""b"') == '"a""b"'
