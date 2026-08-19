import pytest
from django.db import connection
from django.db.migrations.state import ProjectState

from sqlfun.operations import CreateFunction

from .utils import function_exists


def _forwards(operation):
    with connection.schema_editor() as schema_editor:
        operation.database_forwards(
            'test_project', schema_editor, ProjectState(), ProjectState()
        )


def _backwards(operation):
    with connection.schema_editor() as schema_editor:
        operation.database_backwards(
            'test_project', schema_editor, ProjectState(), ProjectState()
        )


def _scalar(sql):
    with connection.cursor() as cursor:
        cursor.execute(sql)
        return cursor.fetchone()[0]


@pytest.mark.django_db
def test_create_function_creates_new_function():
    operation = CreateFunction(
        name='public.op_new_fn',
        identity_arguments='a integer',
        result_type='integer',
        sql=(
            'CREATE OR REPLACE FUNCTION op_new_fn(a integer) RETURNS integer '
            'AS $$ SELECT a; $$ LANGUAGE sql IMMUTABLE;'
        ),
    )
    _forwards(operation)
    assert function_exists('op_new_fn')
    assert _scalar('SELECT op_new_fn(7)') == 7


@pytest.mark.django_db
def test_create_function_body_change_replaces_in_place():
    v1_sql = (
        'CREATE OR REPLACE FUNCTION op_body_fn(a integer) RETURNS integer '
        'AS $$ SELECT a; $$ LANGUAGE sql IMMUTABLE;'
    )
    _forwards(CreateFunction(
        name='public.op_body_fn', identity_arguments='a integer',
        result_type='integer', sql=v1_sql,
    ))
    _forwards(CreateFunction(
        name='public.op_body_fn', identity_arguments='a integer',
        result_type='integer',
        sql=v1_sql.replace('SELECT a;', 'SELECT a + 1;'),
        previous_sql=v1_sql,
        previous_identity_arguments='a integer',
        previous_result_type='integer',
    ))
    assert _scalar('SELECT op_body_fn(7)') == 8


@pytest.mark.django_db
def test_create_function_return_type_change_drops_first():
    # plain CREATE OR REPLACE fails with "cannot change return type of
    # existing function" -- passing this test requires the drop-first path
    _forwards(CreateFunction(
        name='public.op_rettype_fn', identity_arguments='a integer',
        result_type='integer',
        sql=(
            'CREATE OR REPLACE FUNCTION op_rettype_fn(a integer) RETURNS integer '
            'AS $$ SELECT a; $$ LANGUAGE sql IMMUTABLE;'
        ),
    ))
    _forwards(CreateFunction(
        name='public.op_rettype_fn', identity_arguments='a integer',
        result_type='bigint',
        sql=(
            'CREATE OR REPLACE FUNCTION op_rettype_fn(a integer) RETURNS bigint '
            'AS $$ SELECT a; $$ LANGUAGE sql IMMUTABLE;'
        ),
        previous_sql=(
            'CREATE OR REPLACE FUNCTION op_rettype_fn(a integer) RETURNS integer '
            'AS $$ SELECT a; $$ LANGUAGE sql IMMUTABLE;'
        ),
        previous_identity_arguments='a integer',
        previous_result_type='integer',
    ))
    assert _scalar('SELECT pg_typeof(op_rettype_fn(1))::text') == 'bigint'
    assert function_exists('op_rettype_fn')  # exactly one overload remains


@pytest.mark.django_db
def test_create_function_parameter_rename_drops_first():
    # identity arguments include parameter names, so a rename is an identity
    # change; plain CREATE OR REPLACE fails with "cannot change name of
    # input parameter"
    _forwards(CreateFunction(
        name='public.op_rename_fn', identity_arguments='first integer',
        result_type='integer',
        sql=(
            'CREATE OR REPLACE FUNCTION op_rename_fn(first integer) RETURNS integer '
            'AS $$ SELECT first; $$ LANGUAGE sql IMMUTABLE;'
        ),
    ))
    _forwards(CreateFunction(
        name='public.op_rename_fn', identity_arguments='initial integer',
        result_type='integer',
        sql=(
            'CREATE OR REPLACE FUNCTION op_rename_fn(initial integer) RETURNS integer '
            'AS $$ SELECT initial; $$ LANGUAGE sql IMMUTABLE;'
        ),
        previous_sql=(
            'CREATE OR REPLACE FUNCTION op_rename_fn(first integer) RETURNS integer '
            'AS $$ SELECT first; $$ LANGUAGE sql IMMUTABLE;'
        ),
        previous_identity_arguments='first integer',
        previous_result_type='integer',
    ))
    assert _scalar('SELECT op_rename_fn(initial := 7)') == 7


@pytest.mark.django_db
def test_create_function_backwards_restores_previous_definition():
    v1_sql = (
        'CREATE OR REPLACE FUNCTION op_reverse_fn(a integer) RETURNS integer '
        'AS $$ SELECT a; $$ LANGUAGE sql IMMUTABLE;'
    )
    v2 = CreateFunction(
        name='public.op_reverse_fn', identity_arguments='a bigint',
        result_type='bigint',
        sql=(
            'CREATE OR REPLACE FUNCTION op_reverse_fn(a bigint) RETURNS bigint '
            'AS $$ SELECT a + 1; $$ LANGUAGE sql IMMUTABLE;'
        ),
        previous_sql=v1_sql,
        previous_identity_arguments='a integer',
        previous_result_type='integer',
    )
    _forwards(CreateFunction(
        name='public.op_reverse_fn', identity_arguments='a integer',
        result_type='integer', sql=v1_sql,
    ))
    _forwards(v2)
    _backwards(v2)
    assert _scalar(
        "SELECT pg_get_function_identity_arguments('op_reverse_fn'::regproc)"
    ) == 'a integer'
    assert _scalar('SELECT op_reverse_fn(7)') == 7


@pytest.mark.django_db
def test_create_function_backwards_without_previous_drops():
    operation = CreateFunction(
        name='public.op_dropback_fn', identity_arguments='a integer',
        result_type='integer',
        sql=(
            'CREATE OR REPLACE FUNCTION op_dropback_fn(a integer) RETURNS integer '
            'AS $$ SELECT a; $$ LANGUAGE sql IMMUTABLE;'
        ),
    )
    _forwards(operation)
    _backwards(operation)
    assert not function_exists('op_dropback_fn')


def test_create_function_describe_and_flags():
    operation = CreateFunction(
        name='public.op_meta_fn', identity_arguments='a integer',
        result_type='integer', sql='CREATE OR REPLACE FUNCTION ...',
    )
    assert operation.reversible
    assert 'public.op_meta_fn' in operation.describe()
    assert operation.state_forwards('test_project', None) is None
