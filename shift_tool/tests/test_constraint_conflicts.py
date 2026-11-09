"""CP-SAT の assumption core を使った制約競合の診断テスト。"""

import json

from ortools.sat.python import cp_model

from optimizer.mode1.constraint_diagnostics import TrackedCpModel


def _add_named_assumption(model, constraint, name):
    """制約を名前付き assumption で有効化し、後で追跡できるようにする。"""
    assumption = model.NewBoolVar(f"assumption_{name}")
    model.Add(constraint).OnlyEnforceIf(assumption)
    model.AddAssumption(assumption)
    return assumption


def find_conflicting_constraints(model, named_assumptions):
    """モデルが infeasible のとき、最小ではないが十分な競合制約名を返す。"""
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    if status != cp_model.INFEASIBLE:
        return status, []

    names_by_index = {
        assumption.Index(): name
        for name, assumption in named_assumptions.items()
    }
    core = solver.SufficientAssumptionsForInfeasibility()
    return status, [names_by_index[index] for index in core]


def test_sufficient_assumptions_identifies_conflicting_oncall_requests():
    """
    当直希望と休み希望が競合する場合に、SufficientAssumptionsForInfeasibility が正しく競合制約を特定することを確認するテスト。
    """
    model = cp_model.CpModel()
    oncall = model.NewBoolVar("oncall_Name1_Name2_day1")

    named_assumptions = {
        "当直希望: Name1/Name2 1日": _add_named_assumption(
            model,
            oncall == 1,
            "oncall_request",
        ),
        "休み希望: Name1 1日": _add_named_assumption(
            model,
            oncall == 0,
            "day_off_request",
        ),
        "無関係な制約: Name2 は当直可能": _add_named_assumption(
            model,
            oncall <= 1,
            "unrelated_constraint",
        ),
    }

    status, conflicts = find_conflicting_constraints(model, named_assumptions)

    assert status == cp_model.INFEASIBLE
    assert set(conflicts) == {
        "当直希望: Name1/Name2 1日",
        "休み希望: Name1 1日",
    }


def _add_oncall_request(model, variable):
    # 当直希望を追加する制約をモデルに追加する
    model.Add(variable == 1)


def _add_day_off_request(model, variable):
    # 休み希望を追加する制約をモデルに追加する
    model.Add(variable == 0)


def _add_unrelated_rule(model, variable):
    # 無関係な制約をモデルに追加する
    model.Add(variable <= 1)


def test_tracked_model_reports_conflicting_constraint_groups(tmp_path):
    # TrackedCpModel を使用して、競合制約グループの報告をテストする
    model = TrackedCpModel()
    oncall = model.NewBoolVar("oncall_Name1_Name2_day1")
    _add_oncall_request(model, oncall)
    _add_day_off_request(model, oncall)
    _add_unrelated_rule(model, oncall)

    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    conflicting_groups = model.conflicting_constraint_groups(solver)
    diagnostic_path = model.write_constraint_diagnostics(
        year=2026,
        month=10,
        solver=solver,
        output_dir=tmp_path,
    )

    assert status == cp_model.INFEASIBLE
    expected_groups = {
        "test_constraint_conflicts.py:_add_oncall_request",
        "test_constraint_conflicts.py:_add_day_off_request",
    }
    assert {g.rsplit(":", 1)[0] for g in conflicting_groups} == expected_groups

    records = [
        json.loads(line)
        for line in diagnostic_path.read_text(encoding="utf-8").splitlines()
    ]
    assert {g.rsplit(":", 1)[0] for g in records[0]["groups"]} == expected_groups
    assert {
        record["group"].rsplit(":", 1)[0]
        for record in records
        if record["type"] == "constraint"
    } == expected_groups


def test_tracked_model_exports_constraint_names_and_inputs(tmp_path):
    """TrackedCpModel が制約名と入力を正しくエクスポートすることを確認するテスト。"""
    model = TrackedCpModel()
    oncall = model.NewBoolVar("oncall_Name1_Name2_day1")
    model.Add(oncall == 1)
    latest_oncall = model.NewBoolVar("latest_oncall")
    model.AddMaxEquality(latest_oncall, [oncall])

    diagnostic_path = model.write_constraint_diagnostics(
        year=2026,
        month=10,
        output_dir=tmp_path,
    )

    lines = diagnostic_path.read_text(encoding="utf-8").splitlines()
    core_record = json.loads(lines[0])
    variable_record = json.loads(lines[1])
    constraint_records = [json.loads(line) for line in lines[2:]]
    constraints_by_name = {
        constraint["name"].split(":")[1]: constraint
        for constraint in constraint_records
    }

    assert core_record["groups"] == []
    assert {variable["name"] for variable in variable_record["variables"]} >= {
        "oncall_Name1_Name2_day1",
        "latest_oncall",
    }
    assert "test_tracked_model_exports_constraint_names_and_inputs" in (
        constraints_by_name
    )
    assert all(constraint["inputs"] for constraint in constraint_records)