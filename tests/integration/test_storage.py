import sqlite3

from app import storage
from app.storage import PlanStore
from tests.factories import plan, student


def test_empty_store_loads_nothing(tmp_path):
    assert PlanStore(tmp_path / "t.db").load() is None


def test_creates_missing_parent_directories(tmp_path):
    path = tmp_path / "nested" / "dir" / "t.db"
    PlanStore(path)
    assert path.exists()


def test_latest_save_wins(tmp_path):
    store = PlanStore(tmp_path / "t.db")
    store.save(plan([student(rate=50)]))
    saved_at = store.save(plan([student(rate=75)]))
    loaded, loaded_at = store.load()
    assert loaded.students[0].rate == 75
    assert loaded_at == saved_at
    assert store.version_count() == 2


def test_old_versions_are_pruned(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "KEEP_VERSIONS", 3)
    store = PlanStore(tmp_path / "t.db")
    for rate in range(10):
        store.save(plan([student(rate=rate)]))
    assert store.version_count() == 3
    assert store.load()[0].students[0].rate == 9


def test_earlier_versions_remain_recoverable(tmp_path):
    path = tmp_path / "t.db"
    store = PlanStore(path)
    store.save(plan([student(rate=50)]))
    store.save(plan([student(rate=75)]))
    with sqlite3.connect(path) as conn:
        bodies = [r[0] for r in conn.execute("SELECT body FROM plan_versions ORDER BY id")]
    assert '"rate":50.0' in bodies[0]


def test_plan_saved_in_the_old_format_still_loads(tmp_path):
    path = tmp_path / "t.db"
    PlanStore(path)
    legacy = (
        '{"settings":{"plan_start":"2026-08-01","plan_end":"2027-07-31","school_start":"2026-08-24",'
        '"school_end":"2027-06-11","monthly_target":10000.0,"breaks":[]},'
        '"students":[{"id":"x","name":"Old","rate":70.0,"school_hours":3.0,"summer_hours":1.0,'
        '"start":"2026-08-01","end":null,"included":true}]}'
    )
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO plan_versions (saved_at, body) VALUES ('2026-10-20T00:00:00+00:00', ?)", (legacy,))
    loaded, _ = PlanStore(path).load()
    assert loaded.students[0].name == "Old"
    assert loaded.settings.summer_start.isoformat() == "2027-06-12"
