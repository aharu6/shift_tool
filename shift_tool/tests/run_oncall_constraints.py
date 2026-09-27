"""当直制約だけを適用して、モデルの可否を確認する実行用スクリプト。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import jpholiday
import pandas as pd
from ortools.sat.python import cp_model

from optimizer.night_shift.oncall_constraints import OncallConstraints
from optimizer.shift_optimizer import ShiftOptimizer
from staff_name_matching import normalize_name_index
def _project_path(path_text: str) -> Path:
    path = Path(path_text).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="当直変数と当直制約だけでCP-SATモデルを検証します。"
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


def _format_default_path(prefix: str, year: int, month: int) -> Path:
    return PROJECT_ROOT / f"{prefix}_{year}_{month}.xlsx"


def _print_selected_oncalls(optimizer: ShiftOptimizer, solver: cp_model.CpSolver) -> None:
    selected = []
    for (staff1, staff2, day), variable in optimizer.night_shifts.items():
        if solver.Value(variable):
            selected.append((day, staff1, staff2))

    print("\n===== 当直割り当て =====")
    if not selected:
        print("割り当てはありません。")
        return
    for day, staff1, staff2 in sorted(selected):
        print(f"{day:2d}日: {staff1} / {staff2}")


def main() -> int:
    args = _parse_args()
    if not 1 <= args.month <= 12:
        raise SystemExit("month は 1 から 12 の範囲で指定してください。")

    staff_file = _project_path(
        args.staff_file
        or _format_default_path(f"スタッフ条件_テスト", args.year, args.month)
    )
    hope_file =Path(PROJECT_ROOT /"10月 出欠確認.xlsx")
    
    for input_file in (staff_file, hope_file):
        if not input_file.exists():
            raise SystemExit(f"入力ファイルが見つかりません: {input_file}")

    hope_list = pd.read_excel(hope_file, skiprows=1)
    #1列目は何もデータが入っていないので削除,1行目は削除しない
    hope_list = hope_list.iloc[:, 1:]
    #⚪︎月→"Name"に変更
    hope_list.rename(columns={hope_list.columns[0]: "Name"}, inplace=True)
    #31日分までの列に絞る,該当付きが28日までなら28日までの列,30日までなら30日までの列に絞る
    hope_list = hope_list.iloc[:, :min(32, hope_list.shape[1])]
    hope_list = hope_list[hope_list["Name"].notna()]
    hope_list = normalize_name_index(
        hope_list,
        source_label=hope_file,
        name_column="Name",
        allow_index_fallback=True,
    )
    #"Name"列が空の行は削除する
    hope_list = hope_list[hope_list["Name"].notna()]
    #NaNは"なし”に置換する
    hope_list = hope_list.replace(pd.NA, "なし")
    
    optimizer = ShiftOptimizer(
        year=args.year,
        month=args.month,
        holidays=jpholiday.month_holidays(args.year, args.month),
        staff_list_pass=str(staff_file),
        hope_list=hope_list,
        previous_month_oncall_staff_ids={},
    )
    optimizer.create_variables()

    # 他の制約クラスは初期化せず、当直制約だけをこのモデルへ追加する。
    oncall_constraints = OncallConstraints(optimizer.model, optimizer)
    oncall_constraints.apply()

    validation_message = optimizer.model.Validate()
    print("===== 当直制約のみのモデル検証 =====")
    print(f"対象: {args.year}年{args.month}月")
    print(f"スタッフ条件: {staff_file}")
    print(f"希望リスト: {hope_file}")
    print(f"当直ペア変数: {len(optimizer.night_shifts)}個")
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
        _print_selected_oncalls(optimizer, solver)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())