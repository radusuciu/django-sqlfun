import pytest

from sqlfun.parsing import (
    FunctionSignature,
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
