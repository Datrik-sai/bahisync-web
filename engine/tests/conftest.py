import pytest

from tests.fixtures.make_statements import build_all


@pytest.fixture(scope="session")
def fixtures():
    return build_all()
