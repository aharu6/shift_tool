import sys
from pathlib import Path

import pandas as pd
from ortools.sat.python import cp_model

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from optimizer.mode1.primary_shift.work_constraints import WorkConstraints


class _StubOptimizer:
    def __init__(self, work_vars):
        self._work_vars = work_vars

    def get_primary_work_var(self, staff, day):
        return self._work_vars.get((staff, day))


def _build_constraint(staff_floors, hopes, year=2026, month=12, chemo_staff=None):
    """WorkConstraints を __new__ で組み立て、化療下限制約だけを適用する。

    staff_floors: {名前: Floor値}（FLOOR_MAPPINGの値。化療フロアは6）
    chemo_staff: 化療（セクション9）に配置可能なスタッフの集合。
        省略時は staff_floors の全員を化療配置可能とする。
    hopes: {名前: {日: 希望値}}（希望値はHOPE_MAPPING後の数値）
    対象月の全日分の出勤変数を用意する。
    """
    if chemo_staff is None:
        chemo_staff = set(staff_floors)
    model = cp_model.CpModel()
    days = 31
    work_vars = {}
    for staff in staff_floors:
        for day in range(1, days + 1):
            work_vars[(staff, day)] = model.NewBoolVar(f"work_{staff}_{day}")

    constraint = WorkConstraints.__new__(WorkConstraints)
    constraint.model = model
    constraint.staff = pd.DataFrame(
        {
            "Floor": list(staff_floors.values()),
            "Floor2": [None] * len(staff_floors),
            "Floor3": [None] * len(staff_floors),
        },
        index=list(staff_floors.keys()),
    )
    constraint.days = days
    constraint.year = year
    constraint.month = month
    constraint.holiday_dates = set()
    constraint.debug_enabled = False
    constraint.eligible_sections = {
        staff: ([9] if staff in chemo_staff else []) for staff in staff_floors
    }
    hope_frame = pd.DataFrame(index=list(staff_floors.keys()), columns=range(1, days + 1))
    for staff, by_day in hopes.items():
        for day, value in by_day.items():
            hope_frame.loc[staff, day] = value
    constraint.hope_list = hope_frame
    constraint.hope_day_column_map = constraint._build_hope_day_column_map()
    constraint.optimizer = _StubOptimizer(work_vars)
    constraint.add_chemo_weekday_attendance_floor()
    return model, work_vars


def _solve_with_attendance(model, work_vars, attending, day):
    """指定日に attending のスタッフだけ出勤させて解けるか返す。

    固定制約をモデルへ追加するため、検証ごとにモデルを作り直すこと。
    """
    for (staff, var_day), var in work_vars.items():
        if var_day == day:
            model.Add(var == (1 if staff in attending else 0))
    solver = cp_model.CpSolver()
    return solver.Solve(model)


CHEMO5 = {"化療A": 6, "化療B": 6, "化療C": 6, "化療D": 6, "化療E": 6}
WEDNESDAY = 2  # 2026-12-02 は水曜


def test_weekday_floor_is_four_without_leave_hopes():
    model, work_vars = _build_constraint(CHEMO5, {})
    status = _solve_with_attendance(
        model, work_vars, {"化療A", "化療B", "化療C"}, WEDNESDAY
    )
    assert status == cp_model.INFEASIBLE

    model, work_vars = _build_constraint(CHEMO5, {})
    status = _solve_with_attendance(
        model, work_vars, {"化療A", "化療B", "化療C", "化療D"}, WEDNESDAY
    )
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_paid_leave_hope_reduces_floor_by_one():
    hopes = {"化療A": {WEDNESDAY: 4}}
    model, work_vars = _build_constraint(CHEMO5, hopes)
    status = _solve_with_attendance(
        model, work_vars, {"化療B", "化療C", "化療D"}, WEDNESDAY
    )
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    model, work_vars = _build_constraint(CHEMO5, hopes)
    status = _solve_with_attendance(
        model, work_vars, {"化療B", "化療C"}, WEDNESDAY
    )
    assert status == cp_model.INFEASIBLE


def test_half_day_paid_leave_counts_as_half_person():
    # 半日有休（AM有PM出のような複合希望）が2人 → 1人分差し引いて下限3
    hopes = {
        "化療A": {WEDNESDAY: [4, 1]},
        "化療B": {WEDNESDAY: [4, 1]},
    }
    model, work_vars = _build_constraint(CHEMO5, hopes)
    status = _solve_with_attendance(
        model, work_vars, {"化療A", "化療B", "化療C"}, WEDNESDAY
    )
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    model, work_vars = _build_constraint(CHEMO5, hopes)
    status = _solve_with_attendance(
        model, work_vars, {"化療A", "化療B"}, WEDNESDAY
    )
    assert status == cp_model.INFEASIBLE


def test_maternity_leave_lowers_base_to_three():
    hopes = {"化療A": {WEDNESDAY: 3}}  # 育休希望 → 基準3名
    model, work_vars = _build_constraint(CHEMO5, hopes)
    status = _solve_with_attendance(
        model, work_vars, {"化療B", "化療C", "化療D"}, WEDNESDAY
    )
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    model, work_vars = _build_constraint(CHEMO5, hopes)
    status = _solve_with_attendance(
        model, work_vars, {"化療B", "化療C"}, WEDNESDAY
    )
    assert status == cp_model.INFEASIBLE


def test_floor_is_capped_by_attendable_count():
    # 指希望2名 + 有休1名 → 出勤可能2名。下限は min(4-1, 2) = 2 になる
    hopes = {
        "化療A": {WEDNESDAY: 14},
        "化療B": {WEDNESDAY: 14},
        "化療C": {WEDNESDAY: 4},
    }
    model, work_vars = _build_constraint(CHEMO5, hopes)
    status = _solve_with_attendance(
        model, work_vars, {"化療D", "化療E"}, WEDNESDAY
    )
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_no_floor_on_sunday():
    sunday = 6  # 2026-12-06 は日曜
    model, work_vars = _build_constraint(CHEMO5, {})
    status = _solve_with_attendance(model, work_vars, set(), sunday)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_no_floor_on_year_end_weekday():
    year_end = 30  # 2026-12-30 は水曜だが年末年始の専用ルール対象
    model, work_vars = _build_constraint(CHEMO5, {})
    status = _solve_with_attendance(model, work_vars, set(), year_end)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
