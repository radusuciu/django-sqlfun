import subprocess

import pytest
from tenacity import retry, wait_fixed, stop_after_attempt, RetryError


pytest_plugins = ["docker_compose"]


def pytest_addoption(parser):
    parser.addoption(
        "--ci",
        action="store_true",
        default=False,
        help="Run tests as if in a CI environment",
    )


def wait_for_postgres_from_compose(session_scoped_container_getter):
    """Wait for the postgres container to be ready."""
    container = session_scoped_container_getter.get("postgres")
    is_ready = "accepting connections" in container.execute(
        ["pg_isready", "-h", "localhost", "-U", "postgres"]
    )
    assert is_ready


def wait_for_postgres_from_ci():
    """Wait for the postgres service to be ready."""
    is_ready = (
        subprocess.run(["pg_isready", "-h", "localhost", "-U", "postgres"]).returncode
        == 0
    )
    assert is_ready


@pytest.fixture(scope="session")
@retry(wait=wait_fixed(2), stop=stop_after_attempt(3))
def wait_for_postgres(request, session_scoped_container_getter):
    """Wait for postgres to be ready.

    Chooses a different strategy depending on whether the tests are running with containerized postgres locally
    or a postgres service in a CI environment.
    """
    if request.config.getoption("--ci"):
        return wait_for_postgres_from_ci()
    else:
        return wait_for_postgres_from_compose(session_scoped_container_getter)


@pytest.fixture(scope="session")
def django_db_setup(wait_for_postgres, django_db_setup):
    pass
