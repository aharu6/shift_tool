"""MeetingConstraintsを単独で検証する実行用スクリプト。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import jpholiday
import pandas as pd
from ortools.sat.python import cp_model

from optimizer.mode2.concurrent_shift.meeting_constraints import MeetingConstraints
from optimizer.mode1.shift_optimizer import ShiftOptimizer
from staff_name_matching import normalize_name_index


PROBES = {
    "apply": "apply",
    "porifa": "get_porifa_week_num",
    "manager": "fixed_manager_meeting",
    "general": "general_meeting",
    "safety": "fixed_medical_safety_working_group",
    "yakushin": "yakushin",
    "second-friday": "second_friday_conference",
    "day16to23": "day16to23",
}


def _project_path(path_text: str) -> Path:
    path = Path(path_text).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def _format_default_path(prefix: str, year: int, month: int) -> Path:
    return PROJECT_ROOT / f"{prefix}_{year}_{month}.xlsx"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MeetingConstraintsだけを適用または個別メソッド実行して検証します。"
    )
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--month", type=int, default=12)
    parser.add_argument(
        "--probe",
        choices=tuple(PROBES),
        default="apply",
        help="検証する入口。既定値apply。会議メソッドは個別指定できます。",
    )
    parser.add_argument(
        "--staff-file",
        default=None,
        help="スタッフ条件Excel。省略時はスタッフ条件_テスト_YYYY_M.xlsxを使用",
    )
    parser.add_argument(
        "--hope-file",
        default=None,
        help="希望リストExcel。省略時は希望リスト_テスト_YYYY_M.xlsxを使用",
    )
    parser.add_argument("--max-time", type=float, default=60.0)
    return parser.parse_args()


def _run_probe(
    meeting_constraints: MeetingConstraints, probe: str
) -> object:
    method_name = PROBES[probe]
    result = getattr(meeting_constraints, method_name)()
    print(f"Probe: {method_name}")
    if result is not None:
        print(f"Probe result: {result}")
    return result


def main() -> int:
    args = _parse_args()
    if not 1 <= args.month <= 12:
        raise SystemExit("month は 1 から 12 の範囲で指定してください。")

    staff_file = _project_path(
        args.staff_file
        or _format_default_path("スタッフ条件_テスト", args.year, args.month)
    )
    hope_file = _project_path(
        args.hope_file
        or _format_default_path("希望リスト_テスト", args.year, args.month)
    )
    for input_file in (staff_file, hope_file):
        if not input_file.exists():
            raise SystemExit(f"入力ファイルが見つかりません: {input_file}")

    hope_list = pd.read_excel(hope_file, skiprows=1)
    hope_list = hope_list.iloc[:, 1:]
    hope_list.rename(columns={hope_list.columns[0]: "Name"}, inplace=True)
    hope_list = hope_list.iloc[:, :min(32, hope_list.shape[1])]
    hope_list = hope_list[hope_list["Name"].notna()]
    hope_list = normalize_name_index(
        hope_list,
        source_label=hope_file,
        name_column="Name",
        allow_index_fallback=True,
    )
    hope_list = hope_list[hope_list["Name"].notna()].replace(pd.NA, "なし")
    optimizer = ShiftOptimizer(
        year=args.year,
        month=args.month,
        holidays=jpholiday.month_holidays(args.year, args.month),
        staff_list_pass=str(staff_file),
        hope_list=hope_list,
        previous_month_oncall_staff_ids={},
    )
    optimizer.create_variables()

    meeting_constraints = MeetingConstraints(optimizer.model, optimizer)
    constraints_before = len(optimizer.model.Proto().constraints)
    result = _run_probe(meeting_constraints, args.probe)
    constraints_after = len(optimizer.model.Proto().constraints)

    if isinstance(result, list):
        penalty_count = len(result)
    else:
        penalty_count = 0

    optimizer.finalize_objective()
    validation_message = optimizer.model.Validate()
    print("===== MeetingConstraints単独のモデル検証 =====")
    print(f"対象: {args.year}年{args.month}月")
    print(f"Probe: {args.probe}")
    print(f"スタッフ条件: {staff_file}")
    print(f"希望リスト: {hope_file}")
    print(f"制約数: {constraints_before} -> {constraints_after}")
    print(f"ペナルティ変数数: {penalty_count}")
    print(f"Validation Message: {validation_message or 'OK'}")
    print(optimizer.model.ModelStats())

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = args.max_time
    status = solver.Solve(optimizer.model)
    print("\n===== ソルバー結果 =====")
    print(f"Solver Status: {solver.StatusName(status)}")
    print(f"status code: {status}")
    print(f"wall_time: {solver.WallTime():.3f}s")
    print(solver.ResponseStats())
    return 0 if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else 1


if __name__ == "__main__":
    raise SystemExit(main())