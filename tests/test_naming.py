from unittest.mock import patch

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


@pytest.mark.parametrize('comment', [
    '-- CREATE FUNCTION decoy()\n',
    '/* CREATE FUNCTION decoy() */\n',
])
def test_leading_comment_cannot_supply_function_name(comment):
    sql = (
        f'{comment}CREATE FUNCTION real_fn() RETURNS integer '
        'AS $$ SELECT 1; $$ LANGUAGE sql;'
    )

    assert extract_function_name(sql) == 'real_fn'


def test_quoted_identifier_with_escaped_quote_is_extracted_intact():
    sql = (
        'CREATE FUNCTION "a""b"() RETURNS integer '
        'AS $$ SELECT 1; $$ LANGUAGE sql;'
    )

    assert extract_function_name(sql) == '"a""b"'


def test_non_create_first_token_does_not_match_later_definition():
    sql = (
        "SELECT 'CREATE FUNCTION decoy()'; "
        'CREATE FUNCTION real_fn() RETURNS integer '
        'AS $$ SELECT 1; $$ LANGUAGE sql;'
    )

    with pytest.raises(SqlFunError):
        extract_function_name(sql)


def test_header_inspection_does_not_change_sql_passed_to_introspection():
    from sqlfun import SqlFun
    from sqlfun.introspection import Signature
    from sqlfun.utils import _introspect_registered

    original_sql = """
        -- CREATE FUNCTION decoy()
        CREATE FUNCTION inspection_copy_fn() RETURNS text AS $$
        SELECT '-- comment-like body text';
        $$ LANGUAGE sql;
    """

    class InspectionCopy(SqlFun):
        app_label = 'test_project'
        sql = original_sql

    seen_sql = []

    def capture(sql, name, conn=None):
        seen_sql.append(sql)
        return Signature(name='public.inspection_copy_fn',
                         identity_arguments='', result_type='text')

    try:
        with patch('sqlfun.utils.introspect_signature', side_effect=capture):
            _introspect_registered()
        assert seen_sql[-1] == original_sql
    finally:
        InspectionCopy.deregister()


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
