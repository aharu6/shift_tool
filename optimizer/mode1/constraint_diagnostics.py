import json
from contextlib import contextmanager
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from ortools.sat.python import cp_model


class TrackedCpModel(cp_model.CpModel):
    """Keep source locations on constraints and export their expressions on failure."""

    def __init__(self):
        super().__init__()
        self._constraint_name_counts = defaultdict(int)
        self._assumptions_by_group = {}
        self._group_by_assumption_index = {}
        self._ungated_constraint_indices = set()
        self._group_override = None

    def _constraint_group(self, caller):
        if self._group_override:
            return self._group_override
        source = Path(caller.f_code.co_filename).name
        return f"{source}:{caller.f_code.co_name}:L{caller.f_lineno}"

    @contextmanager
    def group_scope(self, label):
        """この範囲で追加する制約を、label 名の別グループとして扱う。"""
        previous = self._group_override
        self._group_override = label
        try:
            yield
        finally:
            self._group_override = previous

    def _track_constraint(self, constraint, caller, gate_with_assumption):
        group = self._constraint_group(caller)
        location = (group, caller.f_lineno)
        self._constraint_name_counts[location] += 1
        occurrence = self._constraint_name_counts[location]
        constraint.WithName(
            f"{group}|{caller.f_lineno}|{occurrence}"
        )
        if gate_with_assumption:
            assumption = self._assumptions_by_group.get(group)
            if assumption is None:
                assumption = self.NewBoolVar(f"diagnostic_assumption_{group}")
                self.AddAssumption(assumption)
                self._assumptions_by_group[group] = assumption
                self._group_by_assumption_index[assumption.Index()] = group
            constraint.OnlyEnforceIf(assumption)
        else:
            self._ungated_constraint_indices.add(constraint.Index())
        return constraint

    def Add(self, ct):
        return self._track_constraint(
            super().Add(ct),
            sys._getframe(1),
            gate_with_assumption=True,
        )

    def AddBoolAnd(self, *literals):
        return self._track_constraint(
            super().AddBoolAnd(*literals),
            sys._getframe(1),
            gate_with_assumption=True,
        )

    def AddBoolOr(self, *literals):
        return self._track_constraint(
            super().AddBoolOr(*literals),
            sys._getframe(1),
            gate_with_assumption=True,
        )

    # CP-SAT does not support enforcement literals on lin_max constraints.
    def AddMaxEquality(self, target, exprs):
        return self._track_constraint(
            super().AddMaxEquality(target, exprs),
            sys._getframe(1),
            gate_with_assumption=False,
        )

    def AddMinEquality(self, target, exprs):
        return self._track_constraint(
            super().AddMinEquality(target, exprs),
            sys._getframe(1),
            gate_with_assumption=False,
        )

    def conflicting_constraint_groups(self, solver):
        core = solver.SufficientAssumptionsForInfeasibility()
        groups = []
        for literal in core:
            assumption_index = literal if literal >= 0 else -literal - 1
            group = self._group_by_assumption_index.get(
                assumption_index,
                f"unknown_assumption_{assumption_index}",
            )
            if group not in groups:
                groups.append(group)
        return groups

    def minimize_conflicting_groups(self, groups, time_limit=60.0):
        """グループを1つずつ外して再求解し、最小の競合グループ集合を求める。

        外しても INFEASIBLE のままならそのグループは競合に不要。
        タイムアウト（UNKNOWN）の場合は安全側で残す。
        """
        group_to_literal = {
            group: assumption.Index()
            for group, assumption in self._assumptions_by_group.items()
        }
        proto = cp_model.cp_model_pb2.CpModelProto()
        proto.CopyFrom(self.Proto())
        proto.ClearField("assumptions")
        proto.ClearField("objective")
        proto.ClearField("floating_point_objective")
        proto.ClearField("search_strategy")

        def is_infeasible(candidates):
            trial = cp_model.CpModel()
            trial.Proto().CopyFrom(proto)
            trial.Proto().assumptions.extend(group_to_literal[g] for g in candidates)
            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = time_limit
            solver.parameters.num_workers = 8
            return solver.Solve(trial) == cp_model.INFEASIBLE

        current = [g for g in groups if g in group_to_literal]
        if not is_infeasible(current):
            return current
        for group in list(current):
            candidate = [g for g in current if g != group]
            if is_infeasible(candidate):
                current = candidate
        return current

    @staticmethod
    def _constraint_group_from_name(name):
        parts = name.split("|")
        if len(parts) < 3:
            return None
        return parts[0]

    def write_constraint_diagnostics(
        self,
        year,
        month,
        solver=None,
        output_dir="logs",
    ):
        """制約の診断情報をログに出力します

        Args:
            year (int): The year for the diagnostic log.
            month (int): The month for the diagnostic log.
            solver (cp_model.CpSolver, optional): Infeasible solver result.
            output_dir (str, optional): Directory to save the log. Defaults to "logs".

        Returns:
            Path: The path to the diagnostic log file.
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        diagnostic_path = output_path / (
            f"constraint_diagnostics_{year}_{month:02d}_{timestamp}.jsonl"
        )

        model_proto = self.Proto()
        core_groups = (
            self.conflicting_constraint_groups(solver)
            if solver is not None
            else []
        )
        if core_groups:
            print("競合制約グループ（十分な assumption core、最小とは限りません）:")
            for group in core_groups:
                print(f"  - {group}")
            print("競合グループを最小化中...")
            core_groups = self.minimize_conflicting_groups(core_groups)
            print("最小化した競合制約グループ（これ以上外せない集合）:")
            for group in core_groups:
                print(f"  - {group}")
        else:
            print(
                "競合制約グループを特定できませんでした。"
                "未計装の制約もしくは assumption 以外の制約が原因の可能性があります。"
            )

        core_group_set = set(core_groups)
        variable_names = [
            {"index": index, "name": variable.name}
            for index, variable in enumerate(model_proto.variables)
        ]
        with diagnostic_path.open("w", encoding="utf-8") as diagnostic_file:
            diagnostic_file.write(
                json.dumps(
                    {
                        "type": "infeasibility_core",
                        "groups": core_groups,
                        "note": "The core is sufficient but not necessarily minimal.",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            diagnostic_file.write(
                json.dumps(
                    {"type": "variable_names", "variables": variable_names},
                    ensure_ascii=False,
                )
                + "\n"
            )
            for index, constraint in enumerate(model_proto.constraints):
                group = self._constraint_group_from_name(constraint.name)
                is_ungated = index in self._ungated_constraint_indices
                if (
                    solver is not None
                    and group not in core_group_set
                    and not is_ungated
                ):
                    continue
                diagnostic_file.write(
                    json.dumps(
                        {
                            "type": "constraint",
                            "index": index,
                            "name": constraint.name,
                            "group": group,
                            "gated_by_assumption": not is_ungated,
                            "inputs": str(constraint),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        print(f"制約診断ログを出力しました: {diagnostic_path}")
        return diagnostic_path
