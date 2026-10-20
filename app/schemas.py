"""Data shapes for a tutoring income plan, with validation rules.

A plan is one document: calendar settings, break periods, and students.
The whole plan is saved and projected as a unit.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_PLAN_DAYS = 731  # two years; longer plans are almost certainly a typo
MAX_WEEKLY_HOURS = 80


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Break(_Strict):
    """A period where hours drop, e.g. winter break or a vacation.

    `hours_factor` is the fraction of normal hours still worked:
    0 = fully off, 0.5 = half load, 1 = no change.
    """

    name: str = Field(min_length=1, max_length=100)
    start: date
    end: date
    hours_factor: float = Field(default=0.0, ge=0, le=1)

    @model_validator(mode="after")
    def _end_after_start(self) -> Break:
        if self.end < self.start:
            raise ValueError(f"break '{self.name}': end date is before start date")
        return self


class Student(_Strict):
    """One student (or family) with a fixed hourly rate.

    Hours are per week and differ between the school year and summer.
    `end` is inclusive; None means the student continues indefinitely.
    `included` lets a student be toggled out of the projection for what-ifs.
    """

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=100)
    rate: float = Field(ge=0, le=10_000)
    school_hours: float = Field(ge=0, le=MAX_WEEKLY_HOURS)
    summer_hours: float = Field(ge=0, le=MAX_WEEKLY_HOURS)
    start: date
    end: date | None = None
    included: bool = True

    @model_validator(mode="after")
    def _end_after_start(self) -> Student:
        if self.end is not None and self.end < self.start:
            raise ValueError(f"student '{self.name}': end date is before start date")
        return self


def _one_year_later(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:  # Feb 29
        return d.replace(year=d.year + 1, day=28)


class Settings(_Strict):
    """The school calendar, which is also the modeled period.

    The plan runs from school_start through summer_end. Days in
    [school_start, school_end] use each student's school-year hours and days in
    [summer_start, summer_end] use summer hours. Summer must begin the day after
    school ends, so every day belongs to exactly one season.
    """

    school_start: date
    school_end: date
    summer_start: date
    summer_end: date
    monthly_target: float = Field(ge=0, le=1_000_000)
    breaks: list[Break] = Field(default_factory=list, max_length=100)

    @model_validator(mode="before")
    @classmethod
    def _upgrade_v1(cls, data: Any) -> Any:
        """Convert plans saved before summer dates existed.

        Those had plan_start/plan_end and treated every non-school day as summer.
        Summer becomes the day after school ends through the day before the
        same date a year after school started, i.e. one full cycle.
        """
        if not isinstance(data, dict) or "plan_start" not in data or "summer_start" in data:
            return data
        data = dict(data)
        data.pop("plan_start")
        data.pop("plan_end", None)
        try:
            school_start = date.fromisoformat(str(data["school_start"]))
            school_end = date.fromisoformat(str(data["school_end"]))
        except (KeyError, ValueError):
            return data  # let normal validation report the problem
        data["summer_start"] = (school_end + timedelta(days=1)).isoformat()
        data["summer_end"] = (_one_year_later(school_start) - timedelta(days=1)).isoformat()
        return data

    @model_validator(mode="after")
    def _check_ranges(self) -> Settings:
        if self.school_end <= self.school_start:
            raise ValueError("school year end must be after school year start")
        if self.summer_start != self.school_end + timedelta(days=1):
            raise ValueError("summer must start the day after the school year ends")
        if self.summer_end < self.summer_start:
            raise ValueError("summer end must be on or after summer start")
        if (self.summer_end - self.school_start).days + 1 > MAX_PLAN_DAYS:
            raise ValueError("school year plus summer cannot be longer than two years")
        return self

    @property
    def plan_start(self) -> date:
        return self.school_start

    @property
    def plan_end(self) -> date:
        return self.summer_end


class Plan(_Strict):
    settings: Settings
    students: list[Student] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def _unique_ids(self) -> Plan:
        ids = [s.id for s in self.students]
        if len(ids) != len(set(ids)):
            raise ValueError("student ids must be unique")
        return self


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The nth (1-based) given weekday (Mon=0) of a month."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def default_plan(today: date, monthly_target: float = 10_000.0) -> Plan:
    """A starting plan for the school year containing `today`.

    School starts the 4th Monday of August and ends the 2nd Friday of June;
    summer runs until the day before next year's school start. These are
    typical US approximations and are meant to be edited.
    """
    year = today.year if today.month >= 8 else today.year - 1
    school_end = _nth_weekday(year + 1, 6, 4, 2)
    thanksgiving = _nth_weekday(year, 11, 3, 4)
    thanksgiving_week = thanksgiving - timedelta(days=3)  # the Monday before
    winter_start = date(year, 12, 22) - timedelta(days=date(year, 12, 22).weekday())
    spring_start = _nth_weekday(year + 1, 3, 0, 3)
    return Plan(
        settings=Settings(
            school_start=_nth_weekday(year, 8, 0, 4),
            school_end=school_end,
            summer_start=school_end + timedelta(days=1),
            summer_end=_nth_weekday(year + 1, 8, 0, 4) - timedelta(days=1),
            monthly_target=monthly_target,
            breaks=[
                Break(
                    name="Thanksgiving week",
                    start=thanksgiving_week,
                    end=thanksgiving_week + timedelta(days=6),
                    hours_factor=0.0,
                ),
                Break(
                    name="Winter break",
                    start=winter_start,
                    end=winter_start + timedelta(days=13),
                    hours_factor=0.0,
                ),
                Break(
                    name="Spring break",
                    start=spring_start,
                    end=spring_start + timedelta(days=6),
                    hours_factor=0.0,
                ),
            ],
        ),
        students=[],
    )
