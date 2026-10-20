"""Shared constants and builders for the browser tests."""

import os

BASE_URL = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8000")

# 365 days (Aug 24 2026 – Aug 23 2027), no breaks, so 7 hrs/week at $60 is exactly $21,900.
BASE_SETTINGS = {
    "school_start": "2026-08-24",
    "school_end": "2027-06-11",
    "summer_start": "2027-06-12",
    "summer_end": "2027-08-23",
    "monthly_target": 10000,
    "breaks": [],
}


def make_student(id, name, rate=60, school=7, summer=7, included=True):
    return {
        "id": id,
        "name": name,
        "rate": rate,
        "school_hours": school,
        "summer_hours": summer,
        "start": "2026-08-01",
        "end": None,
        "included": included,
    }
