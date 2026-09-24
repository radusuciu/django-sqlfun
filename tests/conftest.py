import pytest


pytest_plugins = ['docker_compose']


@pytest.fixture(scope='session')
def django_db_setup(session_scoped_container_getter, django_db_setup):
    pass
