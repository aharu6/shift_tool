from pathlib import Path
import re
import tkinter
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile
from optimizer.method.staff_name_matching import (
    normalize_name_index,
    normalize_staff_name,
    validate_name_alignment,
    )
from config.sections import PRIMARY_SECTIONS
from config.floor_mapping import FLOOR_MAPPING
from tkinter import filedialog
import pandas as pd
import os
iDir = os.path.abspath(os.path.dirname(__file__))

class GetPreviousData:
    def _get_previous_year_month(year: int, month: int):
        if month == 1:
            return year - 1, 12
        return year, month - 1

    def _find_previous_month_file(file_prefix: str, year: int, month: int):
        """正規名を優先し、旧来のゼロ埋めなしファイル名も読み込む。"""
        prev_year, prev_month = GetPreviousData._get_previous_year_month(year, month)
        candidates = [
            Path(f"result/{file_prefix}_{prev_year}_{prev_month:02d}.csv"),
            Path(f"result/{file_prefix}_{prev_year}_{prev_month}.csv"),
        ]
        return next((path for path in candidates if path.exists()), candidates[0])
    
    
    def _is_int_lile(c):
        """整数のように見えるかを判定する。"""
        s = str(c).strip()
        try:
            value = float(s)
        except (TypeError, ValueError):
            return False
        return value.is_integer()


    def _normalize_day_columns(columns):
        """列名を整数の文字列に正規化する。"""
        return {
            column: str(int(float(str(column).strip())))
            for column in columns
            if GetPreviousData._is_int_lile(column)
        }

    def _cleaning_previous_month_shift(shift_df):
        """
        列名を整形する
        前月シフトのDataFrameを受け取り、列名を整形して返す。
        """
        #_load_previous_month_shiftで既に処理済みの場合は二重に列を落とさない
        if shift_df is None or shift_df.empty:
            return shift_df

        if shift_df.columns[0] != "Name":
            #1列目は何もデータが入っていないので削除、1行目は削除しない
            shift_df = shift_df.iloc[:, 1:]
            # ○月→"Name"に列名を変更
            shift_df.rename(columns={shift_df.columns[0]: "Name"}, inplace=True)
        #31日分までの列に絞る、該当の月が28日までなら28日までの列、30日までなら30日までの列に絞る
        shift_df = shift_df.iloc[:, :min(32, shift_df.shape[1])]
        shift_df = shift_df[shift_df["Name"].notna()]
        
        shift_df = normalize_name_index(
            shift_df,
            source_label = "Name",
            name_column = "Name",
            allow_index_fallback=True
        )
        
        #Name列が空の行は削除する
        shift_df = shift_df[shift_df["Name"].notna()]
        #NaNは""に置換
        shift_df.fillna("", inplace=True)
        return shift_df



    def _extract_previous_month_oncall_staff_ids(previous_month_shift):
        """前月シフトの◎から月末8日分の当直者を日付別に抽出する。"""
        if previous_month_shift is None or "Name" not in previous_month_shift.columns:
            return {}

        relative_day_columns = sorted(
            {
                int(str(column).strip())
                for column in previous_month_shift.columns
                if GetPreviousData._is_int_lile(column) and -8 <= int(str(column).strip()) <= -1
            },
            reverse=True,
        )
        if not relative_day_columns:
            return {}

        staff_names_by_day = {}
        for relative_day in relative_day_columns:
            previous_day_key = relative_day + 1
            staff_names = []
            column = str(relative_day)
            for _, row in previous_month_shift[["Name", column]].iterrows():
                if str(row[column]).strip() == "◎":
                    staff_names.append(
                        normalize_staff_name(row["Name"]).removesuffix("(◎のみ)").strip()
                    )
            if staff_names:
                staff_names_by_day[previous_day_key] = staff_names
        print(f"抽出された前月末8日分の当直者: {staff_names_by_day}")
        return staff_names_by_day



    #前月複数シフトファイル
    def _load_previous_month_shifts_files_path():
        shift_folder_path = filedialog.askdirectory(
            message = "集計する過去の当直シフト表が入ったフォルダを選択してください",
            initialdir = iDir,
        )
        return shift_folder_path

    def _confirm_incomplete_oncall_history(message):
        while True:
            answer = input(f"{message} 続行しますか？ [y/n]: ").strip().lower()
            if answer in ("y", "yes"):
                return True
            if answer in ("n", "no"):
                return False
            print("y または n を入力してください。")

    def _history_file_year_month(shift_file):
        matches = re.findall(
            r"(?<!\d)(\d{4})[年_.\- ]+(\d{1,2})(?:月)?(?!\d)",
            shift_file.stem,
        )
        dates = {(int(year), int(month)) for year, month in matches}
        if len(dates) == 1:
            year, month = next(iter(dates))
            if year >= 1 and 1 <= month <= 12:
                return year, month

        print(f"ファイル名から年月を判定できません: {shift_file.name}")
        while True:
            value = input("年月を YYYY-MM で入力してください（中止: 0）: ").strip()
            if value == "0":
                return None
            match = re.fullmatch(r"(\d{4})[-/](\d{1,2})", value)
            if match:
                year, month = map(int, match.groups())
                if year >= 1 and 1 <= month <= 12:
                    return year, month
            print("有効な年月を YYYY-MM で入力してください。")

    def _select_previous_month_history_files(shift_files):
        by_month = {}
        for shift_file in shift_files:
            year_month = GetPreviousData._history_file_year_month(shift_file)
            if year_month is None:
                return None
            by_month.setdefault(year_month, []).append(shift_file)

        selected = []
        for (year, month), files in sorted(by_month.items()):
            if len(files) == 1:
                selected.append(files[0])
                continue
            print(f"{year}年{month}月の履歴が重複しています。集計するファイルを選択してください。")
            for number, shift_file in enumerate(files, 1):
                print(f"  {number}: {shift_file.name}")
            while True:
                value = input("番号を入力してください（中止: 0）: ").strip()
                if value == "0":
                    return None
                if value.isdecimal() and 1 <= int(value) <= len(files):
                    selected.append(files[int(value) - 1])
                    break
                print("表示された番号を入力してください。")
        print("当直履歴として集計するファイル:")
        for shift_file in selected:
            print(f"  {shift_file.name}")
        return selected

    #複数シフトファイルを読み込み　ファイル一覧を取得する
    def _load_previous_month_shifts_files():
        shift_folder_path = GetPreviousData._load_previous_month_shifts_files_path()
        shift_files = (
            sorted(Path(shift_folder_path).glob("*.xlsx"))
            if shift_folder_path else []
        )
        if not shift_files:
            if GetPreviousData._confirm_incomplete_oncall_history(
                "当直履歴ファイルが選択されていません。累計履歴なしで"
            ):
                return []
            return None
        return GetPreviousData._select_previous_month_history_files(shift_files)

    #複数ファイル一覧からreadexcelで読み込み
    def _read_previous_month_shifts_files(shift_files):
        all_shifts = []
        failed_files = []
        for shift_file in shift_files:
            try:
                shift_df = pd.read_excel(shift_file)
                #1列目は何もデータが入っていないので削除し、2列目（○月など）を"Name"に統一する
                shift_df = shift_df.iloc[:, 1:]
                if shift_df.empty or len(shift_df.columns) < 2:
                    raise ValueError("スタッフ列または日付列がありません")
                shift_df.rename(columns={shift_df.columns[0]: "Name"}, inplace=True)
                shift_df.rename(columns=GetPreviousData._normalize_day_columns(shift_df.columns), inplace=True)
                day_columns = [
                    column for column in shift_df.columns[1:]
                    if GetPreviousData._is_int_lile(column)
                    and 1 <= int(column) <= 31
                ]
                if not day_columns or shift_df.columns.duplicated().any():
                    raise ValueError("日付列がないか、列名が重複しています")
                all_shifts.append(shift_df)
            except (OSError, ValueError, IndexError, KeyError, BadZipFile, ParseError) as exc:
                print(f"前月シフトファイルの読み込みに失敗しました ({shift_file}): {exc}")
                failed_files.append(shift_file)
        if failed_files and not GetPreviousData._confirm_incomplete_oncall_history(
            f"{len(failed_files)}件の当直履歴を集計できません。読み込めた履歴のみで"
        ):
            return None
        return all_shifts
    
    #複数ファイルからこれまでの当直回数をスタッフごとに合計
    def _sum_previous_month_shifts(all_shifts):
        if not all_shifts:
            print("前月のシフトデータが存在しません")
            return {}
        
        shift_counts = {}
        for shift_df in all_shifts:
            for _, row in shift_df.iterrows():
                name = normalize_staff_name(row['Name']).removesuffix("(◎のみ)").strip()
                for column in shift_df.columns[1:]:
                    if (GetPreviousData._is_int_lile(column)
                            and 1 <= int(float(str(column).strip())) <= 31
                            and str(row[column]).strip() == "◎"):
                        shift_counts[name] = shift_counts.get(name, 0) + 1
        print(f"前月までの当直回数: {shift_counts}")
        return shift_counts


    def _count_previous_months_with_two_oncalls(all_shifts):
        """スタッフごとに、当直が月2回だった過去月数を数える。"""
        two_oncall_month_counts = {}
        for shift_df in all_shifts:
            monthly_counts = {}
            for _, row in shift_df.iterrows():
                name = normalize_staff_name(row['Name']).removesuffix("(◎のみ)").strip()
                monthly_counts[name] = monthly_counts.get(name, 0) + sum(
                    1
                    for column in shift_df.columns[1:]
                    if GetPreviousData._is_int_lile(column)
                    and 1 <= int(float(str(column).strip())) <= 31
                    and str(row[column]).strip() == "◎"
                )

            for name, monthly_count in monthly_counts.items():
                if monthly_count == 2:
                    two_oncall_month_counts[name] = (
                        two_oncall_month_counts.get(name, 0) + 1
                    )

        return two_oncall_month_counts


    def _count_oncall_by_staff(shift_df, day_columns):
        """単月シフト表の◎をスタッフ別に数える。"""
        counts = {}
        for _, row in shift_df.iterrows():
            name = normalize_staff_name(row['Name']).removesuffix("(◎のみ)").strip()
            count = sum(1 for column in day_columns if str(row[column]).strip() == "◎")
            if count:
                counts[name] = counts.get(name, 0) + count
        print(f"前月の当直回数: {counts}")
        return counts

    def _load_previous_month_shift():
        shift_path = tkinter.filedialog.askopenfilename(
            title = "前月シフトファイルを選択してください",
            initialdir=iDir,
            filetypes=[("Excel files", "*.xlsx")],
        )
        
        if not Path(shift_path).exists():
            print(f"前月シフトファイルが見つかりません: {shift_path}")
            return None
        
        try:
            shift_df = pd.read_excel(shift_path)
            #1列目は何もデータが入っていないので削除し、2列目（○月など）を"Name"に統一する
            shift_df = shift_df.iloc[:, 1:]
            shift_df.rename(columns={shift_df.columns[0]: "Name"}, inplace=True)
            shift_df.rename(columns=GetPreviousData._normalize_day_columns(shift_df.columns), inplace=True)
            day_columns = [c for c in shift_df.columns if GetPreviousData._is_int_lile(c)]
        except Exception as exc:
            print(f"前月シフトファイルの読み込みに失敗しました: {exc}")
            return None
        
        
        print(f'読み込んだシフトの確認{shift_df.head()}')
        if not day_columns:
            print(f"前月シフトに日付列が見つかりません: {shift_path}")
            return None

        max_target_day = max(int(str(c).strip()) for c in day_columns)
        print(f'前月シフトの最大日付: {max_target_day}')
        #日付の変換　　　if 日付==max_target_day:日付 == -1, (max_target_day-1) == -2と扱うための補正を行う
        for offset in range(max_target_day,-1,-1):
            shift_df.rename(columns={str(max_target_day - offset): str(-offset-1)}, inplace=True)
            print(f"前月シフトの列名を変換しました: {str(max_target_day - offset)} -> {str(-offset-1)}")
        print(f"現在のシフトデータフレーム: {shift_df.head()}")
        
        #day_columnsの更新
        day_columns = [c for c in shift_df.columns if GetPreviousData._is_int_lile(c)]
        print(f"更新後のday_columns: {day_columns}")
        previous_month_oncall_counts = GetPreviousData._count_oncall_by_staff(shift_df, day_columns)
        #sections.pyを使用してフロアを数字に変換 
        
        for offset_day in range(-1,-8,-1):#過去8日間を対象
            print(f"現在のターゲット日: {offset_day}")
            if str(offset_day) in day_columns:
                last_eight_days  = str(offset_day)
                if 'Name' not in shift_df.columns:
                    print(f"前月シフトファイルにスタッフ列がないため、月初連携をスキップします: {shift_path}")
                    return None
                    
                for _, row in shift_df[['Name',last_eight_days]].iterrows():
                    cell = row[last_eight_days]
                    if pd.isna(cell):
                        continue
                    cell_text = str(cell)
                    print(f"前月シフトの対象スタッフ: {row['Name']} 日付: {last_eight_days} 内容: {cell_text}")#デバッグ用
                    #sections.pyに基づいて内容を数字にマッピング
                    for section,key in PRIMARY_SECTIONS.items():
                        if key in cell_text:
                            cell_text = cell_text.replace(key, str(section))
                            shift_df.loc[row.name, last_eight_days] = cell_text
                                                
                    print(f"前月シフトの対象スタッフ: {row['Name']} 日付: {last_eight_days} 数字に変換後の内容: {cell_text}")#デバッグ用
                
        # 過去8日間のシフトデータフレームを返す
        print(f"返却する過去8日間のシフトデータフレーム: {shift_df[['Name'] + [str(offset_day) for offset_day in range(-1,-8,-1) if str(offset_day) in shift_df.columns]]}")
        last_week_df = shift_df[['Name'] + [str(offset_day) for offset_day in range(-1,-8,-1) if str(offset_day) in shift_df.columns]]
        last_week_df.attrs['oncall_counts'] = previous_month_oncall_counts
        return last_week_df

    def _load_previous_year_end_shift(year, month):
        """前年の同月の年末年始シフトExcelを読み込む。"""
        if month not in (12, 1):
            return None
        path = filedialog.askopenfilename(
            title=f"前年{year - 1}年{month}月シフトファイルを選択してください",
            initialdir=iDir,
            filetypes=[("Excel files", "*.xlsx")],
        )
        if not path:
            raise ValueError(f"前年{month}月のシフトファイルが選択されませんでした。")
        try:
            shift_df = pd.read_excel(path)
        except (OSError, ValueError, BadZipFile) as exc:
            raise ValueError(f"前年{month}月のシフトファイルを読み込めません: {exc}") from exc
        if len(shift_df.columns) < 3:
            raise ValueError(f"前年{month}月シフトにスタッフ名または日付列がありません: {path}")
        shift_df = shift_df.iloc[:, 1:].copy()
        shift_df.rename(columns={shift_df.columns[0]: "Name"}, inplace=True)
        shift_df.rename(columns=GetPreviousData._normalize_day_columns(shift_df.columns), inplace=True)
        if not any(GetPreviousData._is_int_lile(c) for c in shift_df.columns):
            raise ValueError(f"前年{month}月シフトに日付列がありません: {path}")
        return shift_df

    def _load_previous_year_december_30_staff(year: int, previous_year_end_shift):
        """選択済みの前年12月シフトと前年スタッフ条件から30日の勤務者を抽出する。"""
        return GetPreviousData._load_previous_year_worked_staff(
            year, 12, previous_year_end_shift, (30,)
        )[30]

    def _load_previous_year_worked_staff(year: int, month: int, previous_year_end_shift, days):
        """前年のシフトとスタッフ条件から指定日の勤務者をまとめて抽出する。"""
        if previous_year_end_shift is None or "Name" not in previous_year_end_shift.columns:
            raise ValueError(f"前年{month}月シフトにスタッフ名の列がありません。")
        columns = {}
        for day in days:
            day_columns = [
                column for column in previous_year_end_shift.columns
                if GetPreviousData._is_int_lile(column) and int(float(str(column).strip())) == day
            ]
            if len(day_columns) != 1:
                raise ValueError(f"前年{month}月シフトの{day}日列が存在しないか重複しています。")
            columns[day] = day_columns[0]

        staff_path = filedialog.askopenfilename(
            title=f"前年スタッフ条件ファイルを選択してください({year - 1}年{month}月)",
            initialdir=iDir,
            filetypes=[("Excel files", "*.xlsx *.xls")],
        )
        if not staff_path:
            raise ValueError(f"前年{month}月のスタッフ条件ファイルが選択されませんでした。")
        try:
            staff_df = pd.read_excel(staff_path, sheet_name="member_list", skiprows=1)
        except (OSError, ValueError, BadZipFile) as exc:
            raise ValueError(f"前年{month}月のスタッフ条件ファイルを読み込めません: {exc}") from exc
        if not {"Name", "Floor"}.issubset(staff_df.columns):
            raise ValueError(f"前年{month}月のスタッフ条件にName列またはFloor列がありません。")
        staff_df = normalize_name_index(
            staff_df, source_label=staff_path, name_column="Name", allow_index_fallback=False
        )
        floor = staff_df["Floor"].astype(str).str.strip()
        outpatient_staff = set(
            staff_df.index[floor.isin({"外来", str(FLOOR_MAPPING["外来"]), f'{FLOOR_MAPPING["外来"]}.0'})]
        )

        worked_staff = {day: set() for day in days}
        unknown_names = set()
        off_markers = ("休", "指", "有", "夏", "慶", "育", "産", "特", "研", "学")
        for _, row in previous_year_end_shift.iterrows():
            name = normalize_staff_name(row["Name"]).removesuffix("(◎のみ)")
            if not name or name.startswith("指定休"):
                continue
            if name not in staff_df.index:
                unknown_names.add(name)
                continue
            if name in outpatient_staff:
                continue
            for day, column in columns.items():
                value = row[column]
                mark = "出" if pd.isna(value) or not str(value).strip() else str(value).strip()
                if mark != "0" and not any(marker in mark for marker in off_markers):
                    worked_staff[day].add(name)
        if unknown_names:
            raise ValueError(
                f"前年{month}月のスタッフ条件に存在しないスタッフ: " + ", ".join(sorted(unknown_names))
            )
        for day, names in worked_staff.items():
            print(f"前年{month}月{day}日の勤務者を読み込みました: {len(names)}名")
        return worked_staff

    def _load_previous_month_oncall_staff_ids(year: int, month: int):    
        prev_year, prev_month = GetPreviousData._get_previous_year_month(year, month)
        oncall_csv = GetPreviousData._find_previous_month_file("oncall_shift_wide", year, month)
        if not oncall_csv.exists():
            print(f"前月当直ファイルが見つかりません: {oncall_csv}")
            return []
        
        try:
            oncall_df = pd.read_csv(oncall_csv, encoding='utf-8-sig')
        except Exception as exc:
            print(f"前月当直ファイルの読み込みに失敗しました: {exc}")
            return []
        
        print(f"前月当直csvファイルの読み込み成功: {oncall_csv}")

        day_columns = [c for c in oncall_df.columns if str(c).strip().isdigit()]
        if not day_columns:
            raise ValueError(f"前月当直ファイルに日付列が見つかりません: {oncall_csv}")

        staff_names_dict = {}#日付：staff_name
        
        # 前月　最終日の７日前〜最終日
        for offset in range(7,-1,-1):
            target_day = max(int(str(c).strip()) for c in day_columns) - offset
            target_day = str(target_day)
            if target_day in day_columns:
                last_seven_days_column = target_day
                if 'Name' not in oncall_df.columns:
                    print(f"前月当直ファイルにスタッフ列がないため、月初連携をスキップします: {oncall_csv}")
                    return []

                for _, row in oncall_df[['Name', last_seven_days_column]].iterrows():
                    cell = row[last_seven_days_column]
                    if pd.isna(cell):
                        continue
                    cell_text = str(cell)
                    
                    if  ('当直担当' in cell_text) or('当直相方' in cell_text):
                        staff_names_dict.setdefault(int(last_seven_days_column), []).append(row['Name'])
                print(f"前月末7日間の当直者を読み込みました: {prev_year}/{prev_month:02d} 対象={staff_names_dict}")
        if not staff_names_dict:
            print(f"前月末7日間の当直者が見つかりませんでした: {oncall_csv}")
        return staff_names_dict
