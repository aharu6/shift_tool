from types import SimpleNamespace

import pandas as pd
import pytest
from ortools.sat.python import cp_model

from optimizer.method.baseshiftoptimizer import BaseShiftOptimizer
from optimizer.mode1.primary_shift.work_constraints import WorkConstraints


def _solve(
    previous, requests, worked, *, recovery=(), previous_oncall=False,
    can_oncall=True, on_leave=False,
):
    constraint = WorkConstraints.__new__(WorkConstraints)
    constraint.model = cp_model.CpModel()
    constraint.year, constraint.month, constraint.days = 2026, 9, len(requests)
    constraint.staff = pd.DataFrame(
        {"休職": [on_leave], "当直": [can_oncall]}, index=["A"]
    )
    constraint.eligible_sections = {"A": [1]}
    constraint.prev_month_oncall_staff_ids = {"A"} if previous_oncall else set()
    constraint.hope_list = pd.DataFrame(
        [requests], index=["A"], columns=range(1, len(requests) + 1)
    )
    constraint.hope_day_column_map = {day: day for day in range(1, len(requests) + 1)}
    constraint.debug_enabled = False
    work = {
        day: constraint.model.NewBoolVar(f"work_{day}")
        for day in range(1, len(requests) + 1)
    }
    constraint.optimizer = SimpleNamespace(
        prev_month_shift=pd.DataFrame({
            "Name": ["A"],
            **{str(-day): [previous[day - 1]] for day in range(1, 7)},
        }),
        _normalize_attendance_mark=BaseShiftOptimizer._normalize_attendance_mark,
    )
    constraint._get_work_day_var = lambda staff, day: work[day]
    constraint._get_had_oncall_yesterday_var = lambda staff, day: (
        constraint.model.NewConstant(int(day in recovery))
    )
    for day, value in enumerate(worked, 1):
        constraint.model.Add(work[day] == value)
    constraint.add_consecutive_work_constraints()
    return cp_model.CpSolver().Solve(constraint.model)


def test_month_boundary_request_exempts_forced_seven_day_window(capsys):
    status = _solve(["", "", "", "", "指", "指"], [1, 1, 1], [1, 1, 1])
    assert status == cp_model.OPTIMAL
    assert "2026-08-28〜2026-09-03" in capsys.readouterr().out


def test_seven_requests_within_month_are_allowed():
    assert _solve(["指"] * 6, [1] * 7, [1] * 7) == cp_model.OPTIMAL


def test_eight_requested_days_are_allowed():
    assert _solve(["指"] * 6, [1] * 8, [1] * 8) == cp_model.OPTIMAL


@pytest.mark.parametrize("requests", [[1] * 6 + [7], [7] + [1] * 6])
def test_undecided_day_does_not_extend_exempt_streak(requests):
    assert _solve(["指"] * 6, requests, [1] * 7) == cp_model.INFEASIBLE


def test_extra_undecided_day_is_still_limited_after_exempt_window():
    assert _solve(["指"] * 6, [1] * 7 + [7], [1] * 8) == cp_model.INFEASIBLE


def test_recovery_after_requested_oncall_is_included_in_exemption():
    assert _solve(
        ["指"] * 6, [1, 1, 1, 1, 1, 8, 7],
        [1, 1, 1, 1, 1, 1, 0], recovery={7},
    ) == cp_model.OPTIMAL


def test_previous_oncall_recovery_without_request_is_not_exempt():
    assert _solve(
        ["◎", "", "", "", "", ""], [7], [0],
        recovery={1}, previous_oncall=True,
    ) == cp_model.INFEASIBLE


def test_previous_oncall_recovery_and_requests_are_exempt():
    assert _solve(
        ["◎", "", "", "", "指", "指"], [7, 1, 1], [0, 1, 1],
        recovery={1}, previous_oncall=True,
    ) == cp_model.OPTIMAL


def test_combined_forced_off_request_is_not_exempt():
    assert _solve(
        ["指"] * 6, [1, 1, 1, 1, 1, 1, [1, 14]], [1] * 7,
    ) == cp_model.INFEASIBLE


def test_ineligible_oncall_request_does_not_exempt_recovery():
    assert _solve(
        ["指"] * 6, [1, 1, 1, 1, 1, 8, 7],
        [1, 1, 1, 1, 1, 1, 0], recovery={7}, can_oncall=False,
    ) == cp_model.INFEASIBLE


def test_leave_staff_requests_do_not_exempt_consecutive_work():
    assert _solve(
        ["指"] * 6, [1] * 7, [1] * 7, on_leave=True,
    ) == cp_model.INFEASIBLE
