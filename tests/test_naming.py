from unittest.mock import patch

import pytest

from sqlfun.naming import (
    SqlFunError,
    ensure_or_replace,
    extract_function_name,
    normalize_identity,
    split_qualified,
)


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


@pytest.mark.parametrize('written, expected', [
    ('"odd . name"', '"odd . name"'),
    ('"my schema" . "my fn"', '"my schema"."my fn"'),
    ('schema . fn', 'schema.fn'),
    ('"a.b" . "c . d"', '"a.b"."c . d"'),
])
def test_quoted_identifier_interiors_survive_extraction(written, expected):
    sql = f'CREATE FUNCTION {written}(a int) RETURNS int AS $$ SELECT a; $$ LANGUAGE sql;'
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
    from sqlfun.utils import get_migration_operations

    original_sql = """
        -- CREATE FUNCTION decoy()
        CREATE OR REPLACE FUNCTION inspection_copy_fn() RETURNS text AS $$
        SELECT '-- comment-like body text';
        $$ LANGUAGE sql;
    """

    class InspectionCopy(SqlFun):
        app_label = 'test_project'
        sql = original_sql

    seen_sql = []

    def capture(sql, name, conn=None):
        seen_sql.append(sql)
        return Signature(identity_arguments='', result_type='text')

    try:
        with patch('sqlfun.utils.introspect_signature', side_effect=capture):
            get_migration_operations()
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


@pytest.mark.parametrize('sql', [
    (
        'CREATE FUNCTION actual_fn() RETURNS integer '
        'AS $$ SELECT 1; $$ LANGUAGE sql; '
        '-- CREATE OR REPLACE FUNCTION'
    ),
    (
        'CREATE FUNCTION actual_fn() RETURNS text AS $$ '
        "SELECT 'CREATE OR REPLACE FUNCTION'; "
        '$$ LANGUAGE sql;'
    ),
    (
        '-- CREATE OR REPLACE FUNCTION decoy()\n'
        'CREATE FUNCTION actual_fn() RETURNS integer '
        'AS $$ SELECT 1; $$ LANGUAGE sql;'
    ),
])
def test_ensure_or_replace_ignores_phrase_outside_header(sql):
    with pytest.raises(SqlFunError, match='OR REPLACE'):
        ensure_or_replace(sql)


def test_ensure_or_replace_accepts_real_header_after_comments():
    ensure_or_replace(
        '/* deployment comment */\n'
        'CREATE OR REPLACE FUNCTION actual_fn() RETURNS integer AS $$\n'
        '-- body comment\n'
        'SELECT 1;\n'
        '$$ LANGUAGE sql;'
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


@pytest.mark.parametrize('name, expected', [
    ('CAFÉ', '"cafÉ"'),
    ('café', '"café"'),
    ('Straße.Fn', '"straße".fn'),
])
def test_identity_folds_only_ascii_letters(name, expected):
    # PostgreSQL leaves non-ASCII letters alone when folding unquoted names
    assert normalize_identity(name) == expected


def test_split_qualified_folds_only_ascii_letters():
    assert split_qualified('Schéma.CAFÉ') == ('schéma', 'cafÉ')


def test_query_compile_does_not_reparse_sql():
    from sqlfun import SqlFun

    class Cached(SqlFun):
        app_label = 'test_project'
        sql = 'CREATE OR REPLACE FUNCTION cached_name_fn(a int) RETURNS int AS $$ SELECT a; $$ LANGUAGE sql;'

    try:
        assert Cached.get_function_name_from_sql() == 'cached_name_fn'
        with patch('sqlfun.naming.sqlparse.format') as format_sql:
            assert Cached.get_function_name_from_sql() == 'cached_name_fn'
        format_sql.assert_not_called()

        # reassigning sql is still honoured
        Cached.sql = Cached.sql.replace('cached_name_fn', 'recached_name_fn')
        assert Cached.get_function_name_from_sql() == 'recached_name_fn'
    finally:
        Cached.deregister()
