import pytest

from tests.e2e.helpers import BASE_SETTINGS, BASE_URL


@pytest.fixture
def seed(page):
    """Returns a function that replaces the saved plan and opens the app."""

    def _seed(students=(), breaks=()):
        plan = {"settings": {**BASE_SETTINGS, "breaks": list(breaks)}, "students": list(students)}
        res = page.request.put(f"{BASE_URL}/api/plan", data=plan)
        assert res.ok, res.text()
        page.goto(BASE_URL + "/")
        page.wait_for_function("() => state.projection !== null")

    return _seed


@pytest.fixture
def saved_plan(page):
    return lambda: page.request.get(f"{BASE_URL}/api/plan").json()["plan"]
