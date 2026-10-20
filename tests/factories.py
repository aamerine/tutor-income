"""Small builders for test plans. 7 hrs/week = exactly 1 hour per day."""

from datetime import date, timedelta

from app.schemas import Break, Plan, Settings, Student

SCHOOL_START = date(2026, 8, 24)
SCHOOL_END = date(2027, 6, 11)  # 292 school days
SUMMER_END = date(2027, 8, 23)  # 73 summer days; 365 in total
PLAN_START = SCHOOL_START
PLAN_END = SUMMER_END


def student(id="a", rate=60.0, school=7.0, summer=7.0, start=PLAN_START, end=None, included=True, name=None):
    return Student(
        id=id,
        name=f"Student {id}" if name is None else name,
        rate=rate,
        school_hours=school,
        summer_hours=summer,
        start=start,
        end=end,
        included=included,
    )


def brk(start, end, factor=0.0, name="Break"):
    return Break(name=name, start=start, end=end, hours_factor=factor)


def plan(students=(), breaks=(), school_start=SCHOOL_START, school_end=SCHOOL_END,
         summer_start=None, summer_end=SUMMER_END, target=10_000.0):
    """summer_start defaults to the day after school_end."""
    return Plan(
        settings=Settings(
            school_start=school_start,
            school_end=school_end,
            summer_start=summer_start or school_end + timedelta(days=1),
            summer_end=summer_end,
            monthly_target=target,
            breaks=list(breaks),
        ),
        students=list(students),
    )
