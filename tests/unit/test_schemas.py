from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas import Plan, default_plan
from tests.factories import brk, plan, student


def test_valid_plan_round_trips_through_json():
    p = plan([student(end=date(2027, 1, 1))], [brk(date(2026, 12, 21), date(2027, 1, 3), 0.25)])
    assert Plan.model_validate_json(p.model_dump_json()) == p


def test_student_may_start_and_end_same_day():
    student(start=date(2026, 9, 1), end=date(2026, 9, 1))


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"end": date(2026, 7, 1)}, "end date is before start date"),
        ({"rate": -1}, "greater than or equal to 0"),
        ({"school": 81}, "less than or equal to 80"),
        ({"summer": -0.5}, "greater than or equal to 0"),
        ({"name": ""}, "at least 1 character"),
    ],
)
def test_invalid_students_are_rejected(kwargs, message):
    with pytest.raises(ValidationError, match=message):
        student(**kwargs)


def test_break_end_before_start_is_rejected():
    with pytest.raises(ValidationError, match="end date is before start date"):
        brk(date(2026, 12, 10), date(2026, 12, 1))


@pytest.mark.parametrize("factor", [-0.1, 1.1])
def test_break_factor_must_be_a_fraction(factor):
    with pytest.raises(ValidationError):
        brk(date(2026, 12, 1), date(2026, 12, 2), factor)


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"school_end": date(2026, 8, 1)}, "school year end must be after"),
        ({"summer_start": date(2027, 6, 14)}, "summer must start the day after the school year ends"),
        ({"summer_start": date(2027, 6, 10)}, "summer must start the day after the school year ends"),
        ({"summer_start": date(2027, 6, 11)}, "summer must start the day after the school year ends"),
        ({"summer_end": date(2027, 6, 11)}, "summer end must be on or after summer start"),
        ({"summer_end": date(2028, 8, 24)}, "longer than two years"),
        ({"target": -5}, "greater than or equal to 0"),
    ],
)
def test_invalid_settings_are_rejected(kwargs, message):
    with pytest.raises(ValidationError, match=message):
        plan(**kwargs)


def test_two_year_plan_is_allowed():
    plan(summer_end=date(2028, 8, 23))


def test_one_day_summer_is_allowed():
    plan(summer_end=date(2027, 6, 12))


def test_plan_period_runs_school_start_to_summer_end():
    s = plan().settings
    assert (s.plan_start, s.plan_end) == (date(2026, 8, 24), date(2027, 8, 23))


LEGACY = {
    "plan_start": "2026-08-01",
    "plan_end": "2027-07-31",
    "school_start": "2026-08-24",
    "school_end": "2027-06-11",
    "monthly_target": 10000.0,
    "breaks": [{"name": "Winter break", "start": "2026-12-21", "end": "2027-01-03", "hours_factor": 0.0}],
}


def test_plans_saved_before_summer_dates_are_upgraded():
    legacy_student = student().model_dump(mode="json")
    p = Plan.model_validate({"settings": LEGACY, "students": [legacy_student]})
    s = p.settings
    assert s.school_start == date(2026, 8, 24)
    assert s.school_end == date(2027, 6, 11)
    assert s.summer_start == date(2027, 6, 12)
    assert s.summer_end == date(2027, 8, 23)  # a full year from school start
    assert s.monthly_target == 10_000
    assert s.breaks[0].name == "Winter break"
    assert p.students[0].model_dump(mode="json") == legacy_student
    assert "plan_start" not in p.model_dump()["settings"]


def test_upgrade_handles_a_leap_day_school_start():
    legacy = {**LEGACY, "school_start": "2028-02-29", "school_end": "2028-06-09", "plan_end": "2028-12-31"}
    assert Plan.model_validate({"settings": legacy}).settings.summer_end == date(2029, 2, 27)


def test_upgrade_leaves_invalid_legacy_data_to_normal_validation():
    with pytest.raises(ValidationError):
        Plan.model_validate({"settings": {**LEGACY, "school_end": "garbage"}})


def test_duplicate_student_ids_are_rejected():
    with pytest.raises(ValidationError, match="unique"):
        plan([student("a"), student("a")])


def test_unknown_fields_are_rejected():
    data = plan([student()]).model_dump(mode="json")
    data["students"][0]["colour"] = "red"
    with pytest.raises(ValidationError, match="Extra inputs"):
        Plan.model_validate(data)


def test_default_plan_mid_school_year():
    p = default_plan(date(2026, 10, 19))
    s = p.settings
    assert s.school_start == date(2026, 8, 24)  # 4th Monday of August
    assert s.school_end == date(2027, 6, 11)  # 2nd Friday of June
    assert s.summer_start == date(2027, 6, 12)
    assert s.summer_end == date(2027, 8, 22)  # day before 4th Monday of Aug 2027
    assert s.monthly_target == 10_000
    breaks = {b.name: (b.start, b.end) for b in s.breaks}
    assert breaks["Thanksgiving week"] == (date(2026, 11, 23), date(2026, 11, 29))  # Thanksgiving is Nov 26
    assert breaks["Winter break"] == (date(2026, 12, 21), date(2027, 1, 3))
    assert breaks["Spring break"] == (date(2027, 3, 15), date(2027, 3, 21))
    assert p.students == []


@pytest.mark.parametrize(
    "today, start_year",
    [(date(2027, 6, 30), 2026), (date(2027, 7, 31), 2026), (date(2027, 8, 1), 2027), (date(2027, 1, 1), 2026)],
)
def test_default_plan_picks_the_current_school_year(today, start_year):
    assert default_plan(today).settings.school_start.year == start_year
