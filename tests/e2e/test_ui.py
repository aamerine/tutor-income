"""Browser tests: edits must redraw totals and charts without any save button."""

import re

from playwright.sync_api import expect

from tests.e2e.helpers import make_student


def student_input(page, row, field):
    return page.locator("#students-body tr").nth(row).locator(f'[data-field="{field}"]')


def chart_values(page, chart, dataset=0):
    return page.evaluate(f"() => state.charts.{chart}.data.datasets[{dataset}].data")


def test_empty_plan_shows_zero_and_hint(page, seed):
    seed()
    expect(page.locator("#t-revenue")).to_have_text("$0")
    expect(page.locator("#students-empty")).to_be_visible()
    expect(page.locator("#gap-summary")).to_contain_text("Add your students")
    expect(page.locator("#jar-pct")).to_have_text("0% of the way there")
    expect(page.locator("#save-status")).to_have_text("All changes saved")


def test_adding_a_student_updates_totals_live_and_persists(page, seed, saved_plan):
    seed()
    page.click("#add-student")
    student_input(page, 0, "name").fill("Alice")
    student_input(page, 0, "rate").fill("60")
    student_input(page, 0, "school_hours").fill("7")
    student_input(page, 0, "summer_hours").fill("7")

    expect(page.locator("#t-revenue")).to_have_text("$21,900")
    expect(page.locator("#t-rate")).to_have_text("$60.00")
    expect(page.locator("#students-body tr").first.locator(".out-share")).to_have_text("100%")
    expect(page.locator("#save-status")).to_contain_text("Saved")
    assert saved_plan()["students"][0]["name"] == "Alice"

    page.reload()
    expect(student_input(page, 0, "name")).to_have_value("Alice")
    expect(page.locator("#t-revenue")).to_have_text("$21,900")


def test_changing_rate_redraws_charts(page, seed):
    seed([make_student("a", "Alice", rate=60)])
    expect(page.locator("#t-revenue")).to_have_text("$21,900")
    assert chart_values(page, "monthly", 0)[0] == 8 * 60  # Aug 24–31 2026, school year

    student_input(page, 0, "rate").fill("120")
    expect(page.locator("#t-revenue")).to_have_text("$43,800")
    page.wait_for_function("() => state.charts.monthly.data.datasets[0].data[0] === 8 * 120")
    assert chart_values(page, "monthly", 1)[-1] == 23 * 120  # Aug 1–23 2027, summer
    assert chart_values(page, "rates") == [43800]
    assert page.evaluate("() => state.charts.rates.data.labels") == ["$120/hr"]


def test_summer_hours_shape_the_weekly_curve(page, seed):
    seed([make_student("a", "Alice", school=14, summer=0)])
    weekly = chart_values(page, "weeklyHours")
    assert max(weekly) == 14
    assert weekly[-1] == 0  # late July is summer
    student_input(page, 0, "summer_hours").fill("7")
    page.wait_for_function("() => state.charts.weeklyHours.data.datasets[0].data.at(-1) === 1")  # final week has 1 day


def test_unticking_a_student_removes_them_from_totals(page, seed, saved_plan):
    seed([make_student("a", "Alice", rate=60), make_student("b", "Bob", rate=100)])
    expect(page.locator("#t-revenue")).to_have_text("$58,400")
    student_input(page, 1, "included").uncheck()
    expect(page.locator("#t-revenue")).to_have_text("$21,900")
    expect(page.locator("#students-body tr").nth(1)).to_have_class(re.compile("excluded"))
    expect(page.locator("#save-status")).to_contain_text("Saved")
    assert saved_plan()["students"][1]["included"] is False


def test_invalid_input_is_flagged_and_not_saved(page, seed, saved_plan):
    seed([make_student("a", "Alice", rate=60)])
    rate = student_input(page, 0, "rate")
    rate.fill("")
    expect(rate).to_have_attribute("aria-invalid", "true")
    expect(page.locator("#form-error")).to_contain_text("Rate must be a number")
    expect(page.locator("#save-status")).to_contain_text("Not saved")
    page.wait_for_timeout(600)  # longer than the save delay
    assert saved_plan()["students"][0]["rate"] == 60

    rate.fill("75")
    expect(rate).not_to_have_attribute("aria-invalid", "true")
    expect(page.locator("#form-error")).to_be_hidden()
    expect(page.locator("#t-revenue")).to_have_text("$27,375")
    expect(page.locator("#save-status")).to_contain_text("Saved")
    assert saved_plan()["students"][0]["rate"] == 75


def test_end_date_before_start_is_flagged(page, seed):
    seed([make_student("a", "Alice")])
    end = student_input(page, 0, "end")
    end.fill("2026-07-01")
    expect(end).to_have_attribute("aria-invalid", "true")
    expect(page.locator("#form-error")).to_contain_text("Alice: end date is before start date")
    end.fill("2026-09-02")
    expect(page.locator("#t-revenue")).to_have_text("$600")  # Aug 24 – Sep 2


def test_break_reduces_income(page, seed):
    seed([make_student("a", "Alice", rate=60)])
    page.click("#add-break")
    row = page.locator("#breaks-body tr").first
    row.locator('[data-field="name"]').fill("Vacation")
    row.locator('[data-field="start"]').fill("2026-12-21")
    row.locator('[data-field="end"]').fill("2026-12-27")
    expect(page.locator("#t-revenue")).to_have_text("$21,480")  # 7 days off = $420
    row.locator('[data-field="hours_factor"]').fill("50")
    expect(page.locator("#t-revenue")).to_have_text("$21,690")


def test_monthly_target_change_updates_gap(page, seed):
    seed([make_student("a", "Alice", rate=60, school=50, summer=50)])
    # 50 hrs/wk all year at $60 clears $120k; 50 x 120,000 / 156,428.57 = 38.4 hrs needed
    expect(page.locator("#gap-summary")).to_contain_text("could cut back to about 38.4 hrs in a regular school week (now 50)")
    expect(page.locator("#gap-summary")).to_contain_text("and about 38.4 hrs in a regular summer week (now 50)")
    page.fill('[data-path="settings.monthly_target"]', "20000")
    expect(page.locator("#gap-summary")).to_contain_text("short of the target")
    expect(page.locator("#t-monthly-sub")).to_contain_text("under")


BREAKS = [
    {"name": "Thanksgiving week", "start": "2026-11-23", "end": "2026-11-29", "hours_factor": 0},
    {"name": "Winter break", "start": "2026-12-21", "end": "2027-01-03", "hours_factor": 0},
    {"name": "Spring break", "start": "2027-03-15", "end": "2027-03-21", "hours_factor": 0},
]


def test_whatif_slider_uses_regular_school_weeks(page, seed):
    """Regression: 50 hrs/week in school weeks only, $53.65/hr, short of target.

    The slider used to treat 50 hrs as worked all 52 weeks and showed $46.03/hr.
    """
    seed([make_student("a", "Alice", rate=53.65, school=50, summer=0)], BREAKS)
    expect(page.locator("#t-revenue")).to_have_text("$101,169")
    expect(page.locator("#jar-pct")).to_have_text("84% of the way there")  # 101,169 / 120,000
    expect(page.locator("#jar-text")).to_have_text("$101,169 of $120,000 for the year")
    expect(page.locator("#t-hours")).to_have_text("50")
    expect(page.locator("#t-hours-sub")).to_contain_text("Whole-year average 36.2")
    expect(page.locator("#whatif-hours-out")).to_have_text("50")
    # 1,885.71 hours a year -> $120,000 / 1,885.71 = $63.64
    expect(page.locator("#whatif-result")).to_contain_text("average $63.64/hr")
    expect(page.locator("#gap-summary")).to_contain_text("about 59.3 hrs in a regular school week (now 50)")
    expect(page.locator("#gap-summary")).to_contain_text("or an average of $63.64/hr")
    expect(page.locator("#gap-summary")).not_to_contain_text("summer week")

    page.locator("#whatif-hours").fill("60")
    # 60 hrs x 37.71 working weeks = 2,262.86 hours -> $53.03
    expect(page.locator("#whatif-result")).to_contain_text("average $53.03/hr")


def test_whatif_slider_counts_planned_summer_hours(page, seed):
    seed([make_student("a", "Alice", rate=60, school=7, summer=7)])
    page.locator("#whatif-hours").fill("40")
    # 40 hrs x 292/7 school weeks + 73 summer hours = 1,741.57 hours -> $68.90
    expect(page.locator("#whatif-result")).to_contain_text("average $68.90/hr")
    expect(page.locator("#whatif-result")).to_contain_text("(7 hrs/week in summer)")


def test_delete_needs_confirmation(page, seed, saved_plan):
    seed([make_student("a", "Alice"), make_student("b", "Bob")])
    delete = page.locator("#students-body tr").nth(1).locator("button")
    delete.click()
    expect(delete).to_have_text("Delete?")
    assert len(saved_plan()["students"]) == 2
    delete.click()
    expect(page.locator("#students-body tr")).to_have_count(1)
    expect(page.locator("#t-revenue")).to_have_text("$21,900")
    expect(page.locator("#save-status")).to_contain_text("Saved")
    assert [s["name"] for s in saved_plan()["students"]] == ["Alice"]


def test_backup_download_and_restore(page, seed, saved_plan, tmp_path):
    seed([make_student("a", "Alice")])
    with page.expect_download() as dl:
        page.click("#export-btn")
    backup = tmp_path / "backup.json"
    dl.value.save_as(backup)

    student_input(page, 0, "name").fill("Changed")
    expect(page.locator("#save-status")).to_contain_text("Saved")

    page.set_input_files("#import-file", str(backup))
    expect(page.locator("#save-status")).to_have_text("Backup restored")
    expect(student_input(page, 0, "name")).to_have_value("Alice")
    assert saved_plan()["students"][0]["name"] == "Alice"


def test_no_console_errors(page, seed):
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    seed([make_student("a", "Alice")])
    page.click("#add-student")
    student_input(page, 1, "rate").fill("90")
    expect(page.locator("#save-status")).to_contain_text("Saved")
    assert errors == []


def test_school_end_and_summer_start_stay_linked(page, seed, saved_plan):
    seed([make_student("a", "Alice", rate=60, school=7, summer=14)])
    school_end = page.locator('[data-path="settings.school_end"]')
    summer_start = page.locator('[data-path="settings.summer_start"]')
    # 292 school days at 1 hr + 73 summer days at 2 hrs, $60/hr
    expect(page.locator("#t-revenue")).to_have_text("$26,280")

    school_end.fill("2027-05-28")
    expect(summer_start).to_have_value("2027-05-29")
    # 14 days move from school (1 hr/day) to summer (2 hrs/day): +$840
    expect(page.locator("#t-revenue")).to_have_text("$27,120")
    expect(page.locator("#save-status")).to_contain_text("Saved")
    saved = saved_plan()["settings"]
    assert (saved["school_end"], saved["summer_start"]) == ("2027-05-28", "2027-05-29")

    summer_start.fill("2027-06-12")
    expect(school_end).to_have_value("2027-06-11")
    expect(page.locator("#t-revenue")).to_have_text("$26,280")


def test_summer_end_sets_the_length_of_the_year(page, seed):
    seed([make_student("a", "Alice", rate=60)])
    summer_end = page.locator('[data-path="settings.summer_end"]')
    summer_end.fill("2027-08-16")
    expect(page.locator("#t-revenue")).to_have_text("$21,480")  # 7 fewer days
    summer_end.fill("2027-06-01")
    expect(summer_end).to_have_attribute("aria-invalid", "true")
    expect(page.locator("#form-error")).to_contain_text("Summer end must be on or after summer start")


def test_jar_celebrates_reaching_the_target(page, seed):
    seed([make_student("a", "Alice", rate=60, school=50, summer=50)])
    expect(page.locator("#jar-pct")).to_have_text("Target reached! ✿")
    expect(page.locator("#jar")).to_have_attribute("aria-valuenow", "100")


def test_page_is_personalized_and_fonts_load(page, seed):
    seed()
    expect(page).to_have_title("Jessica's Tutoring Planner")
    expect(page.locator("#greeting")).to_contain_text("Jessica")
    page.wait_for_function("() => document.fonts.status === 'loaded'")
    assert page.evaluate("() => document.fonts.check('600 16px Fraunces') && document.fonts.check('16px Nunito')")
