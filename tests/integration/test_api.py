import hashlib
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import STATIC_DIR, create_app
from app.storage import PlanStore
from tests.factories import brk, plan, student

CHART_JS_SHA256 = "48444a82d4edcb5bec0f1965faacdde18d9c17db3063d042abada2f705c9f54a"  # chart.js 4.5.1


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "tutor.db"


@pytest.fixture
def client(db_path):
    with TestClient(create_app(db_path)) as c:
        yield c


def sample_plan():
    return plan(
        [student("a", rate=60), student("b", rate=85, school=3, summer=0, end=date(2027, 5, 31))],
        [brk(date(2026, 12, 21), date(2027, 1, 3), name="Winter")],
    ).model_dump(mode="json")


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_empty_database_serves_default_plan_without_saving(client, db_path):
    body = client.get("/api/plan").json()
    assert body["saved_at"] is None
    assert body["plan"]["settings"]["monthly_target"] == 10_000
    assert body["plan"]["students"] == []
    assert PlanStore(db_path).version_count() == 0


def test_put_saves_and_returns_projection(client, db_path):
    data = sample_plan()
    res = client.put("/api/plan", json=data)
    assert res.status_code == 200
    body = res.json()
    assert body["plan"] == data
    assert body["saved_at"]
    assert body["projection"]["totals"]["included_students"] == 2
    assert client.get("/api/plan").json()["plan"] == data
    assert PlanStore(db_path).version_count() == 1


def test_saved_plan_survives_app_restart(client, db_path):
    data = sample_plan()
    client.put("/api/plan", json=data)
    with TestClient(create_app(db_path)) as fresh:
        assert fresh.get("/api/plan").json()["plan"] == data


def test_get_projection_matches_put_response(client):
    put = client.put("/api/plan", json=sample_plan()).json()
    assert client.get("/api/projection").json() == put["projection"]


def test_post_projection_previews_without_saving(client, db_path):
    res = client.post("/api/projection", json=sample_plan())
    assert res.status_code == 200
    assert res.json()["totals"]["revenue"] > 0
    assert PlanStore(db_path).version_count() == 0


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["students"][0].update(rate=-10),
        lambda d: d["students"][0].update(end="2020-01-01"),
        lambda d: d["settings"].update(summer_start="2027-06-20"),
        lambda d: d["settings"].update(summer_end="2027-06-01"),
        lambda d: d["settings"]["breaks"][0].update(hours_factor=2),
        lambda d: d["students"][0].update(start="not-a-date"),
        lambda d: d["students"].append(dict(d["students"][0])),
        lambda d: d.update(extra=True),
    ],
)
def test_invalid_plans_are_rejected_and_not_saved(client, db_path, mutate):
    client.put("/api/plan", json=sample_plan())
    bad = sample_plan()
    mutate(bad)
    res = client.put("/api/plan", json=bad)
    assert res.status_code == 422
    assert res.json()["detail"]
    assert PlanStore(db_path).version_count() == 1
    assert client.get("/api/plan").json()["plan"] == sample_plan()


def test_export_downloads_saved_plan_that_can_be_restored(client, db_path, tmp_path):
    data = sample_plan()
    client.put("/api/plan", json=data)
    res = client.get("/api/export")
    assert res.status_code == 200
    assert res.headers["content-disposition"].startswith('attachment; filename="tutor-plan-')
    assert res.json() == data

    with TestClient(create_app(tmp_path / "other.db")) as other:
        assert other.put("/api/plan", json=res.json()).status_code == 200
        assert other.get("/api/plan").json()["plan"] == data


def test_old_backup_without_summer_dates_can_be_restored(client):
    legacy = sample_plan()
    settings = legacy["settings"]
    settings.pop("summer_start")
    settings.pop("summer_end")
    settings.update(plan_start="2026-08-01", plan_end="2027-07-31")
    res = client.put("/api/plan", json=legacy)
    assert res.status_code == 200
    saved = client.get("/api/plan").json()["plan"]["settings"]
    assert saved["summer_start"] == "2027-06-12"
    assert saved["summer_end"] == "2027-08-23"
    assert "plan_start" not in saved


def test_index_and_static_assets_are_served(client):
    index = client.get("/")
    assert index.status_code == 200
    assert "<title>Jessica's Tutoring Planner</title>" in index.text
    for asset in (
        "/static/app.js",
        "/static/styles.css",
        "/static/vendor/chart-4.5.1.umd.min.js",
        "/static/fonts/fraunces-latin-full-normal.woff2",
        "/static/fonts/fraunces-latin-full-italic.woff2",
        "/static/fonts/nunito-latin-wght-normal.woff2",
    ):
        assert client.get(asset).status_code == 200, asset


def test_vendored_chart_js_is_unmodified():
    data = (STATIC_DIR / "vendor" / "chart-4.5.1.umd.min.js").read_bytes()
    assert hashlib.sha256(data).hexdigest() == CHART_JS_SHA256


def test_index_references_existing_assets():
    html = (STATIC_DIR / "index.html").read_text()
    for ref in ("/static/app.js", "/static/styles.css", "/static/vendor/chart-4.5.1.umd.min.js"):
        assert ref in html
        assert (STATIC_DIR / ref.removeprefix("/static/")).is_file()
