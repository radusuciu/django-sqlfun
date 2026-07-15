import pytest

from sqlfun import SqlFun, SqlFunParseError as ReexportedSqlFunParseError
from sqlfun.parsing import (
    Parameter,
    SqlFunParseError,
    parse_function_signature,
)


def test_parses_simple_function():
    signature = parse_function_signature("""
        CREATE OR REPLACE FUNCTION first_of_two(
            first integer,
            second integer
        ) RETURNS integer as $$
        SELECT first;
        $$
        LANGUAGE sql
        IMMUTABLE;
    """)
    assert signature.name == 'first_of_two'
    assert signature.parameters == (
        Parameter(definition='first integer'),
        Parameter(definition='second integer'),
    )
    assert signature.returns == 'integer'


def test_parses_create_without_or_replace():
    signature = parse_function_signature(
        'CREATE FUNCTION no_replace(a integer) RETURNS integer AS $$ SELECT a; $$ LANGUAGE sql;'
    )
    assert signature.name == 'no_replace'


def test_parses_function_with_no_parameters():
    signature = parse_function_signature(
        'CREATE FUNCTION nullary() RETURNS integer AS $$ SELECT 1; $$ LANGUAGE sql;'
    )
    assert signature.parameters == ()
    assert signature.returns == 'integer'


def test_parses_parameterized_types_with_nested_parens_and_commas():
    signature = parse_function_signature(
        'CREATE FUNCTION money_fn(amount numeric(10, 2)) RETURNS numeric(10, 2) '
        'AS $$ SELECT amount; $$ LANGUAGE sql;'
    )
    assert signature.parameters == (Parameter(definition='amount numeric(10,2)'),)
    assert signature.returns == 'numeric(10,2)'


def test_parses_schema_qualified_name():
    signature = parse_function_signature(
        'CREATE FUNCTION public.qualified(a integer) RETURNS integer AS $$ SELECT a; $$ LANGUAGE sql;'
    )
    assert signature.name == 'public.qualified'


def test_equal_signatures_despite_formatting_differences():
    compact = parse_function_signature(
        'create function fmt(first integer,second integer) returns integer as $$ select 1; $$ language sql;'
    )
    spread = parse_function_signature("""
        CREATE OR REPLACE FUNCTION fmt(
            first   INTEGER,
            second  INTEGER
        ) RETURNS INTEGER AS $$ SELECT 2; $$ LANGUAGE sql;
    """)
    assert compact == spread


def test_different_parameter_type_is_a_different_signature():
    a = parse_function_signature(
        'CREATE FUNCTION t(a integer) RETURNS integer AS $$ SELECT a; $$ LANGUAGE sql;'
    )
    b = parse_function_signature(
        'CREATE FUNCTION t(a bigint) RETURNS integer AS $$ SELECT a; $$ LANGUAGE sql;'
    )
    assert a != b


def test_different_parameter_name_is_a_different_signature():
    a = parse_function_signature(
        'CREATE FUNCTION t(a integer) RETURNS integer AS $$ SELECT a; $$ LANGUAGE sql;'
    )
    b = parse_function_signature(
        'CREATE FUNCTION t(b integer) RETURNS integer AS $$ SELECT b; $$ LANGUAGE sql;'
    )
    assert a != b


def test_different_return_type_is_a_different_signature():
    a = parse_function_signature(
        'CREATE FUNCTION t(a integer) RETURNS integer AS $$ SELECT a; $$ LANGUAGE sql;'
    )
    b = parse_function_signature(
        'CREATE FUNCTION t(a integer) RETURNS bigint AS $$ SELECT a; $$ LANGUAGE sql;'
    )
    assert a != b


def test_missing_create_function_raises():
    with pytest.raises(SqlFunParseError):
        parse_function_signature('SELECT 1;')


def test_missing_parameter_list_raises():
    with pytest.raises(SqlFunParseError):
        parse_function_signature('CREATE FUNCTION broken RETURNS integer AS $$ SELECT 1; $$;')


def test_missing_returns_clause_raises():
    with pytest.raises(SqlFunParseError):
        parse_function_signature('CREATE FUNCTION broken(a integer) AS $$ SELECT a; $$ LANGUAGE sql;')


def test_unbalanced_parentheses_raise():
    with pytest.raises(SqlFunParseError):
        parse_function_signature('CREATE FUNCTION broken(a integer RETURNS integer')


def test_default_values_are_stripped_and_ignored_for_equality():
    with_default = parse_function_signature(
        "CREATE FUNCTION d(a integer DEFAULT 5, b text DEFAULT 'x,y (z)') "
        'RETURNS integer AS $$ SELECT a; $$ LANGUAGE sql;'
    )
    with_eq_default = parse_function_signature(
        'CREATE FUNCTION d(a integer = 10, b text = NULL) '
        'RETURNS integer AS $$ SELECT a; $$ LANGUAGE sql;'
    )
    without_default = parse_function_signature(
        'CREATE FUNCTION d(a integer, b text) '
        'RETURNS integer AS $$ SELECT a; $$ LANGUAGE sql;'
    )
    assert with_default == with_eq_default == without_default
    assert with_default.parameters == (
        Parameter(definition='a integer'),
        Parameter(definition='b text'),
    )


def test_parameter_modes_are_parsed():
    signature = parse_function_signature(
        'CREATE FUNCTION m(IN a integer, OUT b integer, INOUT c text, VARIADIC nums integer[]) '
        'RETURNS integer AS $$ SELECT 1; $$ LANGUAGE sql;'
    )
    assert signature.parameters == (
        Parameter(definition='a integer', mode='in'),
        Parameter(definition='b integer', mode='out'),
        Parameter(definition='c text', mode='inout'),
        Parameter(definition='nums integer[]', mode='variadic'),
    )


def test_drop_clause_excludes_out_params_and_keeps_modes():
    signature = parse_function_signature(
        'CREATE FUNCTION m(IN a integer, OUT b integer, INOUT c text, VARIADIC nums integer[]) '
        'RETURNS integer AS $$ SELECT 1; $$ LANGUAGE sql;'
    )
    assert signature.drop_clause == 'm(a integer, inout c text, variadic nums integer[])'


def test_drop_clause_for_simple_function():
    signature = parse_function_signature("""
        CREATE OR REPLACE FUNCTION first_of_two(
            first integer,
            second integer
        ) RETURNS integer as $$ SELECT first; $$ LANGUAGE sql IMMUTABLE;
    """)
    assert signature.drop_clause == 'first_of_two(first integer, second integer)'


def test_drop_clause_strips_defaults():
    signature = parse_function_signature(
        'CREATE FUNCTION d(a integer DEFAULT 5) RETURNS integer AS $$ SELECT a; $$ LANGUAGE sql;'
    )
    assert signature.drop_clause == 'd(a integer)'


def test_parses_returns_table():
    signature = parse_function_signature("""
        CREATE FUNCTION tab(a integer) RETURNS TABLE (
            id integer,
            label text
        ) AS $$ SELECT a, 'x'; $$ LANGUAGE sql;
    """)
    assert signature.returns == 'table(id integer,label text)'


def test_parses_returns_setof():
    signature = parse_function_signature(
        'CREATE FUNCTION s(a integer) RETURNS SETOF integer AS $$ SELECT a; $$ LANGUAGE sql;'
    )
    assert signature.returns == 'setof integer'


def test_parses_multi_word_return_type():
    signature = parse_function_signature(
        'CREATE FUNCTION ts(a integer) RETURNS timestamp with time zone '
        'AS $$ SELECT now(); $$ LANGUAGE sql;'
    )
    assert signature.returns == 'timestamp with time zone'


def test_quoted_identifiers_preserve_case():
    signature = parse_function_signature(
        'CREATE FUNCTION "MixedCase"("Arg" integer) RETURNS integer '
        'AS $$ SELECT 1; $$ LANGUAGE sql;'
    )
    assert signature.name == '"MixedCase"'
    assert signature.parameters == (Parameter(definition='"Arg" integer'),)


def test_body_containing_parens_and_commas_does_not_confuse_parser():
    signature = parse_function_signature("""
        CREATE OR REPLACE FUNCTION tricky(a integer) RETURNS integer AS $$
            SELECT coalesce(a, greatest(1, 2), least(3, 4));
        $$ LANGUAGE sql;
    """)
    assert signature.parameters == (Parameter(definition='a integer'),)
    assert signature.returns == 'integer'


def test_get_function_name_from_sql_handles_schema_qualified_names():
    class SchemaQualified(SqlFun):
        app_label = 'test_project'
        sql = (
            'CREATE FUNCTION public.my_func(a integer) RETURNS integer '
            'AS $$ SELECT a; $$ LANGUAGE sql;'
        )

    try:
        assert SchemaQualified.get_function_name_from_sql() == 'public.my_func'
    finally:
        SchemaQualified.deregister()


def test_get_function_name_from_sql_raises_parse_error_naming_the_class():
    class Broken(SqlFun):
        app_label = 'test_project'
        sql = 'CREATE FUNCTION broken_no_parens RETURNS integer'

    try:
        with pytest.raises(SqlFunParseError, match='Broken'):
            Broken.get_function_name_from_sql()
    finally:
        Broken.deregister()


def test_returns_null_on_null_input_does_not_corrupt_return_type():
    signature = parse_function_signature(
        'CREATE FUNCTION strict_fn(a integer) RETURNS integer '
        'RETURNS NULL ON NULL INPUT AS $$ SELECT a; $$ LANGUAGE sql;'
    )
    assert signature.returns == 'integer'


def test_sqlfun_parse_error_is_a_value_error():
    assert issubclass(SqlFunParseError, ValueError)


def test_sqlfun_parse_error_is_importable_from_sqlfun():
    assert ReexportedSqlFunParseError is SqlFunParseError
