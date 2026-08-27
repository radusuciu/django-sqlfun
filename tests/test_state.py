import textwrap

from sqlfun.state import FunctionState, get_replayed_state

from .utils import remove_test_migration, write_test_migration


def _create_op(name, body, result_type='integer', identity='a integer',
               previous=None):
    previous_kwargs = ''
    if previous is not None:
        previous_kwargs = f'''
                previous_sql={previous['sql']!r},
                previous_identity_arguments={previous['identity']!r},
                previous_result_type={previous['result_type']!r},'''
    sql = (
        f'CREATE OR REPLACE FUNCTION {name}({identity}) '
        f'RETURNS {result_type} AS $$ {body} $$ LANGUAGE sql IMMUTABLE;'
    )
    return f'''sqlfun.operations.CreateFunction(
                name={name!r},
                identity_arguments={identity!r},
                result_type={result_type!r},
                sql={sql!r},{previous_kwargs}
            )''', sql


def _migration(dependencies, operations_src, replaces=None):
    replaces_line = f'    replaces = {replaces!r}\n        ' if replaces else ''
    return textwrap.dedent(f'''\
        import sqlfun.operations
        from django.db import migrations


        class Migration(migrations.Migration):
        {replaces_line}    dependencies = {dependencies!r}
            operations = [
                {operations_src},
            ]
        ''')


def test_replay_collects_created_function():
    op_src, sql = _create_op('state_created_fn', 'SELECT a;')
    path = write_test_migration(
        'test_project', '0901_state_created',
        _migration([('test_project', '0001_initial')], op_src),
    )
    try:
        state = get_replayed_state()
        assert state['state_created_fn'] == FunctionState(
            sql=sql,
            identity_arguments='a integer',
            result_type='integer',
            app_label='test_project',
        )
    finally:
        remove_test_migration('test_project', path)


def test_replay_last_write_wins_across_migrations():
    op_v1_src, v1_sql = _create_op('state_replaced_fn', 'SELECT a;')
    op_v2_src, v2_sql = _create_op(
        'state_replaced_fn', 'SELECT a + 1;',
        previous={'sql': v1_sql, 'identity': 'a integer',
                  'result_type': 'integer'},
    )
    path_v1 = write_test_migration(
        'test_project', '0902_state_replaced_v1',
        _migration([('test_project', '0001_initial')], op_v1_src),
    )
    path_v2 = write_test_migration(
        'test_project', '0903_state_replaced_v2',
        _migration([('test_project', '0902_state_replaced_v1')], op_v2_src),
    )
    try:
        state = get_replayed_state()
        assert state['state_replaced_fn'].sql == v2_sql
    finally:
        remove_test_migration('test_project', path_v2)
        remove_test_migration('test_project', path_v1)


def test_replay_drop_removes_entry():
    op_src, sql = _create_op('state_dropped_fn', 'SELECT a;')
    drop_src = f'''sqlfun.operations.DropFunction(
                name='state_dropped_fn',
                identity_arguments='a integer',
                sql={sql!r},
            )'''
    path_create = write_test_migration(
        'test_project', '0904_state_dropped_create',
        _migration([('test_project', '0001_initial')], op_src),
    )
    path_drop = write_test_migration(
        'test_project', '0905_state_dropped_drop',
        _migration([('test_project', '0904_state_dropped_create')], drop_src),
    )
    try:
        assert 'state_dropped_fn' not in get_replayed_state()
    finally:
        remove_test_migration('test_project', path_drop)
        remove_test_migration('test_project', path_create)


def test_replay_uses_squashed_replacement():
    op_v1_src, v1_sql = _create_op('state_squashed_fn', 'SELECT a;')
    op_v2_src, v2_sql = _create_op(
        'state_squashed_fn', 'SELECT a + 1;',
        previous={'sql': v1_sql, 'identity': 'a integer',
                  'result_type': 'integer'},
    )
    op_squashed_src, squashed_sql = _create_op('state_squashed_fn', 'SELECT a + 1;')
    path_v1 = write_test_migration(
        'test_project', '0906_state_squash_v1',
        _migration([('test_project', '0001_initial')], op_v1_src),
    )
    path_v2 = write_test_migration(
        'test_project', '0907_state_squash_v2',
        _migration([('test_project', '0906_state_squash_v1')], op_v2_src),
    )
    path_squashed = write_test_migration(
        'test_project', '0908_state_squashed',
        _migration(
            [('test_project', '0001_initial')],
            op_squashed_src,
            replaces=[('test_project', '0906_state_squash_v1'),
                      ('test_project', '0907_state_squash_v2')],
        ),
    )
    try:
        # with connection=None the loader always substitutes the squashed
        # migration for the ones it replaces
        assert get_replayed_state()['state_squashed_fn'].sql == squashed_sql
    finally:
        remove_test_migration('test_project', path_squashed)
        remove_test_migration('test_project', path_v2)
        remove_test_migration('test_project', path_v1)


def test_replay_ignores_foreign_operations():
    # migrations full of RunSQL/CreateModel contribute nothing
    assert 'bad_sum' not in get_replayed_state()
