"""CP-SAT の assumption core を使った制約競合の診断テスト。"""

from ortools.sat.python import cp_model


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