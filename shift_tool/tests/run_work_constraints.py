"""日勤の専属業務制約だけを適用して、モデルの可否を確認する実行用スクリプト。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import jpholiday
import pandas as pd
from ortools.sat.python import cp_model

from optimizer.concurrent_shift.meeting_constraints import MeetingConstraints
from optimizer.primary_shift.work_constraints import WorkConstraints
from optimizer.primary_shift.work_requests import WorkRequests
from optimizer.shift_optimizer import ShiftOptimizer
from staff_name_matching import normalize_name_index


def _project_path(path_text: str) -> Path:
    path = Path(path_text).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def _format_default_path(prefix: str, year: int, month: int) -> Path:
    return PROJECT_ROOT / f"{prefix}_{year}_{month}.xlsx"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="日勤の専属業務変数と関連制約だけでCP-SATモデルを検証します。"
    )
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--month", type=int, default=9)
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


def _print_selected_work(
    optimizer: ShiftOptimizer, solver: cp_model.CpSolver
) -> None:
    selected = []
    for (staff, day, section), variable in optimizer.shifts.items():
        if solver.Value(variable):
            selected.append((day, staff, section))

    print("\n===== 専属業務割り当て =====")
    if not selected:
        print("割り当てはありません。")
        return
    for day, staff, section in sorted(selected):
        print(f"{day:2d}日: {staff} -> 専属業務 {section}")


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

    # 当直・兼務の制約クラスは適用せず、日勤の専属業務関連だけを追加する。
    work_requests = WorkRequests(optimizer.model, optimizer)
    work_constraints = WorkConstraints(optimizer.model, optimizer)
    meeting_constraints = MeetingConstraints(optimizer.model, optimizer)
    work_requests.apply()
    work_constraints.apply()
    meeting_constraints.apply()
    optimizer.finalize_objective()

    validation_message = optimizer.model.Validate()
    print("===== 日勤専属業務制約のみのモデル検証 =====")
    print(f"対象: {args.year}年{args.month}月")
    print(f"スタッフ条件: {staff_file}")
    print(f"希望リスト: {hope_file}")
    print(f"専属業務変数: {len(optimizer.shifts)}個")
    print(f"目的項数: {len(optimizer.objective_terms)}個")
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

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        _print_selected_work(optimizer, solver)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())