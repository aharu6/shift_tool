from types import SimpleNamespace

import pandas as pd
import pytest
from ortools.sat.python import cp_model

from optimizer.method.baseshiftoptimizer import BaseShiftOptimizer
from optimizer.mode1.primary_shift.work_constraints import WorkConstraints
from optimizer.mode1.shift_optimizer import ShiftOptimizer


def _constraint(previous, requests, *, previous_oncall=False, outpatient=False):
    constraint = WorkConstraints.__new__(WorkConstraints)
    constraint.model = cp_model.CpModel()
    constraint.year, constraint.month, constraint.days = 2026, 1, 7
    constraint.staff = pd.DataFrame({"休職": [False]}, index=["山田太郎"])
    constraint.get_eligible_sections = {"山田太郎": [16] if outpatient else [1]}
    constraint.prev_month_oncall_staff_ids = {"山田太郎"} if previous_oncall else set()
    constraint.hope_list = pd.DataFrame([requests], index=["山田太郎"], columns=range(1, 8))
    constraint.hope_day_column_map = {day: day for day in range(1, 8)}
    constraint.debug_enabled = False
    constraint.optimizer = SimpleNamespace(
        prev_month_shift=pd.DataFrame({
            "Name": ["山田　太郎"],
            **{str(-day): [previous[day - 1]] for day in range(1, 7)},
        }),
        _normalize_attendance_mark=BaseShiftOptimizer._normalize_attendance_mark,
    )
    return constraint


def test_month_boundary_seven_day_work_request_reports_staff_dates_and_reasons():
    constraint = _constraint(["", "", "○", "◎", "研", ""], [1, 7, 7, 7, 7, 7, 7])
    with pytest.raises(ValueError) as error:
        constraint.validate_consecutive_work_requests()
    message = str(error.value)
    assert "山田太郎" in message
    assert "2025-12-26" in message and "2026-01-01" in message
    assert "前月" in message and "出勤希望" in message
    assert "当直明け" in message


def test_six_day_streak_does_not_raise():
    constraint = _constraint(["", "", "", "", "", "指"], [1, 7, 7, 7, 7, 7, 7])
    constraint.validate_consecutive_work_requests()


def test_recovery_after_previous_month_oncall_is_included():
    constraint = _constraint(["◎", "", "", "", "", ""], [7, 7, 7, 7, 7, 7, 7], previous_oncall=True)
    with pytest.raises(ValueError, match="当直明け"):
        constraint.validate_consecutive_work_requests()


def test_recovery_after_requested_oncall_is_included():
    constraint = _constraint(["", "", "", "", "", "指"], [8, 7, 7, 7, 7, 7, 7])
    with pytest.raises(ValueError) as error:
        constraint.validate_consecutive_work_requests()
    assert "当直希望" in str(error.value)
    assert "当直明け" in str(error.value)


@pytest.mark.parametrize("requests", [[7, 7, 7, 7, 7, 7, 7], [14, 7, 7, 7, 7, 7, 7]])
def test_undecided_or_leave_day_is_not_reported_as_forced_work(requests):
    _constraint([""] * 6, requests).validate_consecutive_work_requests()


def test_outpatient_is_excluded_as_in_model():
    _constraint([""] * 6, [1, 7, 7, 7, 7, 7, 7], outpatient=True).validate_consecutive_work_requests()


def test_leave_staff_work_request_is_not_treated_as_forced_work():
    constraint = _constraint([""] * 6, [1, 7, 7, 7, 7, 7, 7])
    constraint.staff.loc["山田太郎", "休職"] = True
    constraint.validate_consecutive_work_requests()


def test_previous_oncall_recovery_is_counted_even_for_leave_staff():
    constraint = _constraint(["◎", "", "", "", "", ""], [7] * 7, previous_oncall=True)
    constraint.staff.loc["山田太郎", "休職"] = True
    with pytest.raises(ValueError, match="前月末当直の明け"):
        constraint.validate_consecutive_work_requests()


def test_ineligible_staff_oncall_request_does_not_force_recovery():
    constraint = _constraint(["", "", "", "", "", "指"], [8, 7, 7, 7, 7, 7, 7])
    constraint.staff.loc["山田太郎", "当直"] = False
    constraint.validate_consecutive_work_requests()


def test_forced_off_in_combined_request_takes_precedence():
    constraint = _constraint([""] * 6, [7, 7, 7, 7, 7, 7, 7])
    constraint.hope_list = constraint.hope_list.astype(object)
    constraint.hope_list.at["山田太郎", 1] = [1, 14]
    constraint.validate_consecutive_work_requests()


def test_month_only_seven_day_streak_is_not_reported_by_boundary_check():
    constraint = _constraint(["指"] * 6, [1] * 7)
    constraint.validate_consecutive_work_requests()


def test_multiple_windows_for_one_staff_are_reported():
    constraint = _constraint([""] * 6, [1, 1, 7, 7, 7, 7, 7])
    with pytest.raises(ValueError) as error:
        constraint.validate_consecutive_work_requests()
    assert str(error.value).count("山田太郎:") == 2
    assert "2026-01-02" in str(error.value)


def test_multiple_conflicts_are_reported_together():
    constraint = _constraint([""] * 6, [1, 7, 7, 7, 7, 7, 7])
    constraint.staff.loc["佐藤花子"] = [False]
    constraint.get_eligible_sections["佐藤花子"] = [1]
    constraint.hope_list.loc["佐藤花子"] = [1, 7, 7, 7, 7, 7, 7]
    constraint.optimizer.prev_month_shift.loc[1] = ["佐藤花子", "", "", "", "", "", ""]
    with pytest.raises(ValueError) as error:
        constraint.validate_consecutive_work_requests()
    assert "山田太郎" in str(error.value)
    assert "佐藤花子" in str(error.value)


def test_optimizer_reports_conflict_before_building_other_constraints():
    constraint = _constraint([""] * 6, [1, 7, 7, 7, 7, 7, 7])
    optimizer = ShiftOptimizer.__new__(ShiftOptimizer)
    optimizer.work_constraints = constraint
    with pytest.raises(ValueError, match="山田太郎"):
        optimizer.apply_all_constraints()
