"""Gross-revenue projection for a tutoring plan.

The model works day by day. She teaches every day of the week, so a student's
weekly hours are spread evenly across 7 days. Each day:

  hours   = weekly_hours(season) / 7 * break_factor
  revenue = hours * rate

where season is "school" inside the school year and "summer" otherwise, and
break_factor is the lowest hours_factor of any break covering that day (1 if
none). Daily figures are then rolled up into weeks, months, students, rates
and seasons. Rounding happens only on output, so the roll-ups agree exactly.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from .schemas import Plan

SCHOOL = "school"
SUMMER = "summer"


@dataclass
class _Bucket:
    hours: float = 0.0
    revenue: float = 0.0
    school_hours: float = 0.0
    school_revenue: float = 0.0
    summer_hours: float = 0.0
    summer_revenue: float = 0.0
    days: int = 0
    school_days: int = 0
    work_days: float = 0.0  # days weighted by break factor: a day off counts 0
    break_names: list[str] = field(default_factory=list)

    def add(self, season: str, hours: float, revenue: float) -> None:
        self.hours += hours
        self.revenue += revenue
        if season == SCHOOL:
            self.school_hours += hours
            self.school_revenue += revenue
        else:
            self.summer_hours += hours
            self.summer_revenue += revenue


def _r2(x: float) -> float:
    return round(x + 0.0, 2)  # + 0.0 turns -0.0 into 0.0


def _rate(revenue: float, hours: float) -> float | None:
    return _r2(revenue / hours) if hours > 1e-9 else None


def _days(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _days_in_month(d: date) -> int:
    nxt = date(d.year + d.month // 12, d.month % 12 + 1, 1)
    return (nxt - date(d.year, d.month, 1)).days


def season_on(plan: Plan, d: date) -> str:
    s = plan.settings
    return SCHOOL if s.school_start <= d <= s.school_end else SUMMER


def break_on(plan: Plan, d: date) -> tuple[float, list[str]]:
    """(hours factor, names of breaks) for a day. Overlaps take the lowest factor."""
    factor = 1.0
    names: list[str] = []
    for b in plan.settings.breaks:
        if b.start <= d <= b.end:
            factor = min(factor, b.hours_factor)
            names.append(b.name)
    return factor, names


def project(plan: Plan) -> dict[str, Any]:
    s = plan.settings
    students = [st for st in plan.students if st.included]

    months: dict[str, _Bucket] = defaultdict(_Bucket)
    month_first_day: dict[str, date] = {}
    weeks: dict[date, _Bucket] = defaultdict(_Bucket)
    per_student: dict[str, list[float]] = {st.id: [0.0, 0.0] for st in plan.students}
    seasons: dict[str, _Bucket] = {SCHOOL: _Bucket(), SUMMER: _Bucket()}
    total = _Bucket()

    for d in _days(s.plan_start, s.plan_end):
        season = season_on(plan, d)
        factor, break_names = break_on(plan, d)
        mkey = f"{d.year:04d}-{d.month:02d}"
        wkey = d - timedelta(days=d.weekday())  # Monday
        month_first_day.setdefault(mkey, d)

        for bucket in (months[mkey], weeks[wkey], seasons[season], total):
            bucket.days += 1
            bucket.school_days += season == SCHOOL
            bucket.work_days += factor
        for name in break_names:
            if name not in weeks[wkey].break_names:
                weeks[wkey].break_names.append(name)

        for st in students:
            if d < st.start or (st.end is not None and d > st.end):
                continue
            weekly = st.school_hours if season == SCHOOL else st.summer_hours
            hours = weekly / 7 * factor
            if hours == 0:
                continue
            revenue = hours * st.rate
            for bucket in (months[mkey], weeks[wkey], seasons[season], total):
                bucket.add(season, hours, revenue)
            per_student[st.id][0] += hours
            per_student[st.id][1] += revenue

    # Months, with the target prorated for partial months at the plan edges.
    month_rows = []
    target_total = 0.0
    for mkey, b in months.items():
        first = month_first_day[mkey]
        target = s.monthly_target * b.days / _days_in_month(first)
        target_total += target
        month_rows.append(
            {
                "month": mkey,
                "label": first.strftime("%b %Y"),
                "days": b.days,
                "revenue": _r2(b.revenue),
                "school_revenue": _r2(b.school_revenue),
                "summer_revenue": _r2(b.summer_revenue),
                "hours": _r2(b.hours),
                "effective_rate": _rate(b.revenue, b.hours),
                "target": _r2(target),
                "gap": _r2(b.revenue - target),
            }
        )

    daily_target = s.monthly_target * 12 / 365
    week_rows = [
        {
            "week_start": wkey.isoformat(),
            "days": b.days,
            "season": SCHOOL if b.school_days * 2 > b.days else SUMMER,
            "breaks": b.break_names,
            "revenue": _r2(b.revenue),
            "hours": _r2(b.hours),
            "target": _r2(daily_target * b.days),
        }
        for wkey, b in weeks.items()
    ]

    student_rows = []
    for st in plan.students:
        hours, revenue = per_student[st.id]
        student_rows.append(
            {
                "id": st.id,
                "name": st.name,
                "rate": st.rate,
                "included": st.included,
                "hours": _r2(hours),
                "revenue": _r2(revenue),
                "share": round(revenue / total.revenue, 4) if total.revenue else 0.0,
            }
        )

    by_rate: dict[float, list[float]] = defaultdict(lambda: [0.0, 0.0, 0])
    for st in students:
        hours, revenue = per_student[st.id]
        bucket = by_rate[st.rate]
        bucket[0] += hours
        bucket[1] += revenue
        bucket[2] += 1
    rate_rows = [
        {
            "rate": rate,
            "students": int(n),
            "hours": _r2(hours),
            "revenue": _r2(revenue),
            "share": round(revenue / total.revenue, 4) if total.revenue else 0.0,
        }
        for rate, (hours, revenue, n) in sorted(by_rate.items())
    ]

    # Revenue scales linearly with hours, so scaling every student's hours by
    # `scale` hits the target exactly while keeping the same rate mix.
    scale = target_total / total.revenue if total.revenue > 1e-9 else None

    def season_summary(b: _Bucket) -> dict[str, Any]:
        weeks_n = b.days / 7
        working_weeks = b.work_days / 7
        # Hours in a regular (non-break) week, which is how she thinks about her load.
        regular = b.hours / working_weeks if working_weeks > 1e-9 else 0.0
        return {
            "days": b.days,
            "working_weeks": round(working_weeks, 4),
            "revenue": _r2(b.revenue),
            "hours": _r2(b.hours),
            "avg_weekly_hours": _r2(b.hours / weeks_n) if weeks_n else 0.0,
            "avg_weekly_revenue": _r2(b.revenue / weeks_n) if weeks_n else 0.0,
            "regular_weekly_hours": _r2(regular),
            "required_regular_weekly_hours": _r2(regular * scale) if scale is not None else None,
            "effective_rate": _rate(b.revenue, b.hours),
        }

    plan_weeks = total.days / 7

    return {
        "totals": {
            "days": total.days,
            "weeks": _r2(plan_weeks),
            "revenue": _r2(total.revenue),
            "hours": _r2(total.hours),
            "effective_rate": _rate(total.revenue, total.hours),
            "avg_monthly_revenue": _r2(total.revenue / total.days * 365 / 12),
            "avg_weekly_hours": _r2(total.hours / plan_weeks),
            "target": _r2(target_total),
            "gap": _r2(total.revenue - target_total),
            "months_below_target": sum(1 for m in month_rows if m["gap"] < 0),
            "included_students": len(students),
        },
        "seasons": {
            SCHOOL: season_summary(seasons[SCHOOL]),
            SUMMER: season_summary(seasons[SUMMER]),
        },
        "gap_analysis": {
            # Average rate needed to hit the target working the same hours.
            "required_rate_at_current_hours": _rate(target_total, total.hours),
            # Multiply all hours by this to hit the target at the current rate mix.
            # Each season's required_regular_weekly_hours applies it.
            "hours_scale_to_target": round(scale, 6) if scale is not None else None,
        },
        "months": month_rows,
        "weeks": week_rows,
        "students": student_rows,
        "rates": rate_rows,
    }
