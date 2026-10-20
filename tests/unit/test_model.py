from datetime import date, timedelta

import pytest

from app.model import project
from tests.factories import PLAN_END, PLAN_START, brk, plan, student

SCHOOL_DAYS = 292
SUMMER_DAYS = 365 - SCHOOL_DAYS


def test_year_round_student_earns_rate_times_hours():
    p = project(plan([student(rate=60, school=7, summer=7)]))
    t = p["totals"]
    assert t["days"] == 365
    assert t["hours"] == pytest.approx(365)
    assert t["revenue"] == pytest.approx(365 * 60)
    assert t["effective_rate"] == 60
    assert t["avg_weekly_hours"] == pytest.approx(7)
    assert t["avg_monthly_revenue"] == pytest.approx(365 * 60 / 12)


def test_school_and_summer_hours_apply_by_season():
    p = project(plan([student(rate=50, school=14, summer=0)]))
    assert p["totals"]["hours"] == pytest.approx(2 * SCHOOL_DAYS)
    assert p["seasons"]["school"]["days"] == SCHOOL_DAYS
    assert p["seasons"]["school"]["revenue"] == pytest.approx(2 * SCHOOL_DAYS * 50)
    assert p["seasons"]["school"]["avg_weekly_hours"] == pytest.approx(14)
    assert p["seasons"]["summer"]["days"] == SUMMER_DAYS
    assert p["seasons"]["summer"]["revenue"] == 0
    assert p["seasons"]["summer"]["effective_rate"] is None


def test_summer_only_student():
    p = project(plan([student(rate=80, school=0, summer=7)]))
    assert p["totals"]["revenue"] == pytest.approx(SUMMER_DAYS * 80)
    assert p["months"][0]["revenue"] == 0  # Aug 2026 is school year
    june = next(m for m in p["months"] if m["month"] == "2027-06")
    assert june["school_revenue"] == 0
    assert june["summer_revenue"] == pytest.approx(19 * 80)  # Jun 12–30
    assert p["months"][-1]["summer_revenue"] == pytest.approx(23 * 80)  # Aug 1–23 2027


def test_season_boundary_is_the_day_after_school_ends():
    p = project(plan([student(rate=10, school=7, summer=14)]))
    june = next(m for m in p["months"] if m["month"] == "2027-06")
    assert june["school_revenue"] == pytest.approx(11 * 10)  # Jun 1–11 at 1 hr/day
    assert june["summer_revenue"] == pytest.approx(19 * 20)  # Jun 12–30 at 2 hrs/day


def test_summer_end_controls_plan_length():
    short = project(plan([student()], summer_end=date(2027, 7, 31)))
    assert short["totals"]["days"] == 365 - 23
    assert short["months"][-1]["month"] == "2027-07"
    assert short["seasons"]["summer"]["days"] == SUMMER_DAYS - 23


def test_student_start_and_end_are_inclusive():
    s = student(start=date(2026, 9, 10), end=date(2026, 9, 19))
    p = project(plan([s]))
    assert p["totals"]["hours"] == pytest.approx(10)
    sep = next(m for m in p["months"] if m["month"] == "2026-09")
    assert sep["hours"] == pytest.approx(10)


def test_student_outside_plan_earns_nothing_but_is_listed():
    s = student(start=date(2028, 1, 1))
    p = project(plan([s]))
    assert p["totals"]["revenue"] == 0
    assert p["students"] == [
        {"id": "a", "name": "Student a", "rate": 60.0, "included": True, "hours": 0, "revenue": 0, "share": 0.0}
    ]


def test_student_started_before_plan_counts_from_plan_start():
    p = project(plan([student(start=date(2020, 1, 1))]))
    assert p["totals"]["hours"] == pytest.approx(365)
    assert project(plan([student(start=date(2026, 8, 1))]))["totals"]["hours"] == pytest.approx(365)


def test_full_break_removes_those_days():
    b = brk(date(2026, 12, 21), date(2027, 1, 3), factor=0)  # 14 days
    p = project(plan([student(rate=60)], breaks=[b]))
    assert p["totals"]["hours"] == pytest.approx(365 - 14)


def test_partial_break_scales_hours():
    b = brk(date(2026, 11, 23), date(2026, 11, 29), factor=0.5)  # 7 days
    p = project(plan([student(rate=60)], breaks=[b]))
    assert p["totals"]["hours"] == pytest.approx(365 - 3.5)


def test_overlapping_breaks_use_lowest_factor():
    a = brk(date(2026, 11, 1), date(2026, 11, 10), factor=0.5, name="Half")
    b = brk(date(2026, 11, 6), date(2026, 11, 10), factor=0, name="Off")
    p = project(plan([student()], breaks=[a, b]))
    # Nov 1–5 at half (2.5 hrs lost), Nov 6–10 fully off (5 hrs lost)
    assert p["totals"]["hours"] == pytest.approx(365 - 2.5 - 5)


def test_excluded_student_is_left_out_of_totals():
    p = project(plan([student("a", rate=60), student("b", rate=100, included=False)]))
    assert p["totals"]["revenue"] == pytest.approx(365 * 60)
    assert p["totals"]["included_students"] == 1
    b = next(s for s in p["students"] if s["id"] == "b")
    assert b["included"] is False
    assert b["revenue"] == 0
    assert [r["rate"] for r in p["rates"]] == [60]


def test_rollups_agree_with_totals():
    students = [
        student("a", rate=55, school=5, summer=2),
        student("b", rate=72.5, school=3.5, summer=0, start=date(2026, 10, 3)),
        student("c", rate=90, school=1, summer=4, end=date(2027, 5, 1)),
    ]
    breaks = [brk(date(2026, 12, 21), date(2027, 1, 3)), brk(date(2027, 3, 15), date(2027, 3, 21), 0.25)]
    p = project(plan(students, breaks))
    total = p["totals"]["revenue"]
    assert sum(m["revenue"] for m in p["months"]) == pytest.approx(total, abs=0.05)
    assert sum(w["revenue"] for w in p["weeks"]) == pytest.approx(total, abs=0.05)
    assert sum(s["revenue"] for s in p["students"]) == pytest.approx(total, abs=0.05)
    assert sum(r["revenue"] for r in p["rates"]) == pytest.approx(total, abs=0.05)
    assert p["seasons"]["school"]["revenue"] + p["seasons"]["summer"]["revenue"] == pytest.approx(total, abs=0.05)
    assert sum(s["share"] for s in p["students"]) == pytest.approx(1, abs=0.001)
    for m in p["months"]:
        assert m["school_revenue"] + m["summer_revenue"] == pytest.approx(m["revenue"], abs=0.02)


def test_months_cover_plan_with_labels_and_targets():
    p = project(plan([student(rate=60)]))
    months = p["months"]
    assert [m["month"] for m in months][:3] == ["2026-08", "2026-09", "2026-10"]
    assert months[-1]["month"] == "2027-08"
    assert len(months) == 13
    assert months[0]["label"] == "Aug 2026"
    assert months[-1]["label"] == "Aug 2027"
    assert months[0]["days"] == 8  # Aug 24–31
    assert months[0]["revenue"] == pytest.approx(8 * 60)
    assert months[1]["revenue"] == pytest.approx(30 * 60)
    assert all(m["target"] == 10_000 for m in months[1:-1])
    assert months[1]["gap"] == pytest.approx(30 * 60 - 10_000)
    assert months[1]["effective_rate"] == 60
    # 8 + 23 days of August make one full month, so 12 months of target in total
    assert p["totals"]["target"] == pytest.approx(120_000, abs=0.01)
    assert p["totals"]["months_below_target"] == 13


def test_partial_months_prorate_the_target():
    p = project(plan([student()], school_start=date(2026, 8, 16), summer_end=date(2027, 8, 15)))
    months = p["months"]
    assert len(months) == 13
    assert months[0]["days"] == 16
    assert months[0]["target"] == pytest.approx(10_000 * 16 / 31, abs=0.01)
    assert months[-1]["target"] == pytest.approx(10_000 * 15 / 31, abs=0.01)


def test_leap_february_and_december_rollover():
    p = project(plan([student()], school_start=date(2027, 8, 23), school_end=date(2028, 6, 9),
                     summer_end=date(2028, 8, 22)))
    by_month = {m["month"]: m for m in p["months"]}
    assert by_month["2028-02"]["days"] == 29
    assert by_month["2028-02"]["target"] == 10_000
    assert by_month["2027-12"]["days"] == 31
    assert by_month["2027-12"]["target"] == 10_000
    assert p["totals"]["days"] == 366


def test_weeks_start_on_monday_and_cover_every_day():
    b = brk(date(2026, 11, 23), date(2026, 11, 29), name="Thanksgiving")
    p = project(plan([student()], breaks=[b]))
    weeks = p["weeks"]
    assert sum(w["days"] for w in weeks) == 365
    assert all(date.fromisoformat(w["week_start"]).weekday() == 0 for w in weeks)
    assert weeks[0]["week_start"] == "2026-08-24"  # a Monday
    assert weeks[0]["days"] == 7
    assert weeks[-1]["week_start"] == "2027-08-23"
    assert weeks[-1]["days"] == 1
    assert weeks[-1]["season"] == "summer"
    thanksgiving = next(w for w in weeks if w["week_start"] == "2026-11-23")
    assert thanksgiving["breaks"] == ["Thanksgiving"]
    assert thanksgiving["revenue"] == 0
    assert thanksgiving["season"] == "school"
    assert next(w for w in weeks if w["week_start"] == "2027-07-05")["season"] == "summer"
    assert sum(w["target"] for w in weeks) == pytest.approx(120_000, abs=1)


DEFAULT_BREAKS = [
    brk(date(2026, 11, 23), date(2026, 11, 29), name="Thanksgiving week"),
    brk(date(2026, 12, 21), date(2027, 1, 3), name="Winter break"),
    brk(date(2027, 3, 15), date(2027, 3, 21), name="Spring break"),
]


def test_school_only_schedule_short_of_target():
    """Regression: 50 hrs in a regular school week, nothing in summer, 4 break weeks.

    The what-if slider once divided the target by 50 hrs x 52 weeks and claimed
    $46.03/hr would do, though she is short at $53.65/hr. Figures below are
    computed by hand from the calendar, not from the model.
    """
    p = project(plan([student(rate=53.65, school=50, summer=0)], breaks=DEFAULT_BREAKS))
    school, summer, g = p["seasons"]["school"], p["seasons"]["summer"], p["gap_analysis"]
    working_weeks = (292 - 28) / 7  # school days minus break days
    hours = 50 * working_weeks  # 1,885.71
    revenue = hours * 53.65  # 101,168.57

    assert school["working_weeks"] == pytest.approx(working_weeks, abs=1e-4)
    assert school["regular_weekly_hours"] == pytest.approx(50)
    assert school["avg_weekly_hours"] == pytest.approx(hours / (292 / 7), abs=0.01)  # 45.21, breaks included
    assert summer["regular_weekly_hours"] == 0
    assert p["totals"]["revenue"] == pytest.approx(revenue, abs=0.01)
    assert p["totals"]["gap"] == pytest.approx(revenue - 120_000, abs=0.01)
    assert p["totals"]["avg_weekly_hours"] == pytest.approx(hours / (365 / 7), abs=0.01)  # 36.16

    assert g["required_rate_at_current_hours"] == pytest.approx(63.64, abs=0.005)
    assert g["hours_scale_to_target"] == pytest.approx(120_000 / revenue, abs=1e-6)
    assert school["required_regular_weekly_hours"] == pytest.approx(59.31, abs=0.005)
    assert summer["required_regular_weekly_hours"] == 0

    # The page's slider: rate = target / (N x school working weeks + summer hours).
    # At her real 50 hrs it must agree with the model, and must not be the old $46.03.
    slider_rate = 120_000 / (50 * school["working_weeks"] + summer["hours"])
    assert slider_rate == pytest.approx(g["required_rate_at_current_hours"], abs=0.01)
    assert slider_rate > p["totals"]["effective_rate"]


def test_gap_analysis_when_above_target_shows_hours_to_spare():
    p = project(plan([student(rate=60, school=50, summer=50)]))
    revenue = 365 * 50 / 7 * 60  # 156,428.57
    scale = 120_000 / revenue
    assert p["totals"]["gap"] == pytest.approx(revenue - 120_000, abs=0.01)
    assert p["gap_analysis"]["hours_scale_to_target"] == pytest.approx(scale, abs=1e-4)
    for season in ("school", "summer"):
        assert p["seasons"][season]["regular_weekly_hours"] == pytest.approx(50)
        assert p["seasons"][season]["required_regular_weekly_hours"] == pytest.approx(50 * scale, abs=0.01)  # 38.36


def test_required_hours_scale_each_season_separately():
    p = project(plan([student(rate=60, school=40, summer=10)], breaks=DEFAULT_BREAKS))
    k = p["gap_analysis"]["hours_scale_to_target"]
    assert p["seasons"]["school"]["required_regular_weekly_hours"] == pytest.approx(40 * k, abs=0.01)
    assert p["seasons"]["summer"]["required_regular_weekly_hours"] == pytest.approx(10 * k, abs=0.01)
    # Scaling every hour by k at the same rates lands exactly on the target.
    assert p["totals"]["revenue"] * k == pytest.approx(p["totals"]["target"], abs=1)


def test_partial_break_counts_as_part_of_a_working_week():
    p = project(plan([student(school=14)], breaks=[brk(date(2026, 11, 23), date(2026, 11, 29), 0.5)]))
    school = p["seasons"]["school"]
    assert school["working_weeks"] == pytest.approx((292 - 3.5) / 7, abs=1e-4)
    assert school["regular_weekly_hours"] == pytest.approx(14)


def test_regular_week_ignores_breaks_but_averages_in_partial_enrolment():
    # A student only there for half the school year halves the regular-week average.
    half = date(2026, 8, 24) + timedelta(days=145)
    p = project(plan([student(school=14, end=half)], breaks=DEFAULT_BREAKS))
    school = p["seasons"]["school"]
    assert school["regular_weekly_hours"] == pytest.approx(school["hours"] / school["working_weeks"], abs=0.01)
    assert school["regular_weekly_hours"] < 14


def test_empty_plan_has_no_rates_and_no_division_errors():
    p = project(plan([]))
    t = p["totals"]
    assert t["revenue"] == 0
    assert t["effective_rate"] is None
    assert t["months_below_target"] == 13
    assert p["gap_analysis"] == {"required_rate_at_current_hours": None, "hours_scale_to_target": None}
    assert p["seasons"]["school"]["required_regular_weekly_hours"] is None
    assert p["seasons"]["school"]["regular_weekly_hours"] == 0
    assert p["rates"] == []
    assert all(m["effective_rate"] is None for m in p["months"])


def test_zero_target_is_never_below():
    p = project(plan([], target=0))
    assert p["totals"]["months_below_target"] == 0


def test_rates_group_students_by_rate():
    p = project(plan([student("a", rate=80), student("b", rate=60), student("c", rate=60, school=14, summer=14)]))
    rates = p["rates"]
    assert [r["rate"] for r in rates] == [60, 80]
    assert rates[0]["students"] == 2
    assert rates[0]["hours"] == pytest.approx(365 * 3)
    assert rates[0]["revenue"] == pytest.approx(365 * 3 * 60)
    assert rates[0]["share"] == pytest.approx(180 / 260, abs=1e-4)
    assert rates[1]["share"] == pytest.approx(80 / 260, abs=1e-4)


def test_effective_rate_is_hours_weighted():
    p = project(plan([student("a", rate=40, school=21, summer=21), student("b", rate=100)]))
    # 3 hrs/day at $40 + 1 hr/day at $100 -> $220 over 4 hrs = $55/hr
    assert p["totals"]["effective_rate"] == 55


def test_fractional_rates_and_hours():
    p = project(plan([student(rate=62.5, school=3.5, summer=3.5)]))
    assert p["totals"]["revenue"] == pytest.approx(365 * 0.5 * 62.5, abs=0.01)


def test_summer_end_is_inclusive():
    one_week = plan([student()], school_end=PLAN_START + timedelta(days=4), summer_end=PLAN_START + timedelta(days=6))
    p = project(one_week)
    assert p["totals"]["hours"] == pytest.approx(7)
    assert p["seasons"]["school"]["days"] == 5
    assert p["seasons"]["summer"]["days"] == 2
    assert project(plan([student()]))["weeks"][-1]["week_start"] == PLAN_END.isoformat()
