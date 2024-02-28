import pytest
from tenacity import retry, wait_fixed, stop_after_attempt


pytest_plugins = ["docker_compose"]


@pytest.fixture(scope="session")
@retry(wait=wait_fixed(2), stop=stop_after_attempt(3))
def wait_for_postgres(request, session_scoped_container_getter):
    """Wait for postgres container to be ready."""
    container = session_scoped_container_getter.get("postgres")
    is_ready = "accepting connections" in container.execute(
        ["pg_isready", "-h", "localhost", "-U", "postgres"]
    )
    assert is_ready


@pytest.fixture(scope="session")
def django_db_setup(wait_for_postgres, django_db_setup):
    pass
