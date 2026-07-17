import pytest

from sqlfun.naming import SqlFunError, extract_function_name


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
