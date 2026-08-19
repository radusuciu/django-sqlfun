import pytest
from django.db import connection
from django.db.migrations.state import ProjectState

from sqlfun.operations import CreateFunction, DropFunction

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


@pytest.mark.django_db
def test_drop_function_drops_and_reverses():
    sql = (
        'CREATE OR REPLACE FUNCTION op_todrop_fn(a integer) RETURNS integer '
        'AS $$ SELECT a; $$ LANGUAGE sql IMMUTABLE;'
    )
    _forwards(CreateFunction(
        name='public.op_todrop_fn', identity_arguments='a integer',
        result_type='integer', sql=sql,
    ))
    drop = DropFunction(
        name='public.op_todrop_fn', identity_arguments='a integer', sql=sql,
    )
    _forwards(drop)
    assert not function_exists('op_todrop_fn')

    _backwards(drop)
    assert function_exists('op_todrop_fn')
    assert _scalar('SELECT op_todrop_fn(7)') == 7


@pytest.mark.django_db
def test_drop_function_is_idempotent_when_function_absent():
    drop = DropFunction(
        name='public.op_never_existed_fn',
        identity_arguments='a integer',
        sql=(
            'CREATE OR REPLACE FUNCTION op_never_existed_fn(a integer) '
            'RETURNS integer AS $$ SELECT a; $$ LANGUAGE sql IMMUTABLE;'
        ),
    )
    _forwards(drop)  # must not raise: DROP ... IF EXISTS


def test_drop_function_describe_and_flags():
    drop = DropFunction(
        name='public.op_meta_drop_fn', identity_arguments='a integer',
        sql='CREATE OR REPLACE FUNCTION ...',
    )
    assert drop.reversible
    assert 'public.op_meta_drop_fn' in drop.describe()


def test_operations_survive_migration_writer_round_trip():
    from django.db import migrations as dj_migrations
    from django.db.migrations.writer import MigrationWriter

    create = CreateFunction(
        name='public.op_writer_fn', identity_arguments='a integer',
        result_type='integer',
        sql=(
            'CREATE OR REPLACE FUNCTION op_writer_fn(a integer)\n'
            'RETURNS integer AS $$ SELECT a; $$ LANGUAGE sql IMMUTABLE;'
        ),
        previous_sql=(
            'CREATE OR REPLACE FUNCTION op_writer_fn(a integer)\n'
            'RETURNS integer AS $$ SELECT a - 1; $$ LANGUAGE sql IMMUTABLE;'
        ),
        previous_identity_arguments='a integer',
        previous_result_type='integer',
    )
    drop = DropFunction(
        name='public.op_writer_gone_fn', identity_arguments='b text',
        sql=(
            'CREATE OR REPLACE FUNCTION op_writer_gone_fn(b text) '
            'RETURNS text AS $$ SELECT b; $$ LANGUAGE sql IMMUTABLE;'
        ),
    )
    migration_cls = type('Migration', (dj_migrations.Migration,), {
        'dependencies': [],
        'operations': [create, drop],
    })
    source = MigrationWriter(migration_cls('0001_writer_probe', 'test_project')).as_string()
    assert 'sqlfun.operations.CreateFunction' in source
    assert 'sqlfun.operations.DropFunction' in source

    namespace = {}
    exec(compile(source, '<round-trip>', 'exec'), namespace)
    loaded = namespace['Migration']('0001_writer_probe', 'test_project')

    loaded_create, loaded_drop = loaded.operations
    assert isinstance(loaded_create, CreateFunction)
    assert loaded_create.name == create.name
    assert loaded_create.identity_arguments == create.identity_arguments
    assert loaded_create.result_type == create.result_type
    assert loaded_create.sql == create.sql
    assert loaded_create.previous_sql == create.previous_sql
    assert loaded_create.previous_identity_arguments == 'a integer'
    assert loaded_create.previous_result_type == 'integer'
    assert isinstance(loaded_drop, DropFunction)
    assert loaded_drop.name == drop.name
    assert loaded_drop.identity_arguments == drop.identity_arguments
    assert loaded_drop.sql == drop.sql
