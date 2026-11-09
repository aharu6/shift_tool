from pathlib import Path
import tkinter
from staff_name_matching import (
    normalize_name_index,
    normalize_staff_name,
    validate_name_alignment,
    )
from config.sections import PRIMARY_SECTIONS
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
            message = "直近12か月分の当直シフト表だけが入ったフォルダを選択してください",
            initialdir = iDir,
        )
        return shift_folder_path
        
    #複数シフトファイルを読み込み　ファイル一覧を取得する
    def _load_previous_month_shifts_files():
        shift_folder_path = GetPreviousData._load_previous_month_shifts_files_path()
        if not shift_folder_path:
            return []
        shift_files = sorted(Path(shift_folder_path).glob("*.xlsx"))
        return shift_files

    #複数ファイル一覧からreadexcelで読み込み
    def _read_previous_month_shifts_files(shift_files):
        all_shifts = []
        for shift_file in shift_files:
            try:
                shift_df = pd.read_excel(shift_file)
                #1列目は何もデータが入っていないので削除し、2列目（○月など）を"Name"に統一する
                shift_df = shift_df.iloc[:, 1:]
                shift_df.rename(columns={shift_df.columns[0]: "Name"}, inplace=True)
                shift_df.rename(columns=GetPreviousData._normalize_day_columns(shift_df.columns), inplace=True)
                all_shifts.append(shift_df)
            except Exception as exc:
                print(f"前月シフトファイルの読み込みに失敗しました ({shift_file}): {exc}")
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
                    if str(row[column]).strip() == "◎":
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
                    if str(row[column]).strip() == "◎"
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
        """前年度の年末年始のシフト読み込み
        形式：excelファイル
        形式は前月_見本.xlsxに準ずる
        startcol等が異なればエラーを返して停止させる
        - 前年度12月または1月のシフト表作成時にのみ有効とする
        """
        if month not in [12,1]:
            return None
        
        prev_year = year -1 
        if month == 12:    
            year_end_excel_path = tkinter.filedialog.askopenfilename(
                title=f"前年12月シフトファイルを選択してください",
                filetypes=[("Excel files", "*.xlsx")],
            )
            if not Path(year_end_excel_path).exists():
                raise ValueError(f"前年12月シフトファイルが存在しません: {year_end_excel_path}")
            try:
                shift_df = pd.read_excel(year_end_excel_path)
                #1れつめは何もデータが入っていないので削除し、２列目（○月など）を”Name”に統一する
                shift_df = shift_df.iloc[:,1:]
                shift_df.rename(columns={shift_df.columns[0]:"Name"},inplace=True)
                shift_df.rename(columns=GetPreviousData._normalize_day_columns(shift_df), inplace=True)
                day_columns = [c for c in shift_df.columns if GetPreviousData._is_int_lile(c)]
                    
            except Exception as exc:
                raise ValueError(f"前年12月シフトファイルの読み込みに失敗しました: {exc}")
            
            print(f"読み込んだ前年12月シフトの確認{shift_df.head()}")
            if not day_columns:
                raise ValueError(f"前年12月シフトファイルに日付列が見つかりません: {year_end_excel_path}")
            
            return shift_df
        
            
        elif month==1:
            year_start_excel_path = Path(f"result/Shift_cleaned_{year}_01.xlsx")
            if not year_start_excel_path.exists():
                raise ValueError(f"前年1月シフトファイルが存在しません")
                    

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


    def _load_previous_december_31_staff(year:int):
        """昨年12月31日の勤務者を読み込む"""
        shift_csv = Path(f"result/Shift_cleaned_{year -1}_12.csv")
        if not shift_csv.exists():
            print(f"前年12月シフトファイルが見つかりません:{shift_csv}")
            return set()
        
        try:
            shift_df = pd.read_csv(shift_csv,encoding="utf-8-sig")
        except Exception as e:
            print(f"前年12月シフトファイルの読み込みに失敗しました:{e}")
            return set()
        
        """昨年のスタッフ条件.xlsxを参照する"""
        staff_old_list_df =tkinter.filedialog.askopenfilename(
            title=f"前年スタッフ条件ファイルを選択してください({year-1}年12月)",
            filetypes=[("Excel files", "*.xlsx *.xls")],
        )
        try:
            staff_old_list_df = pd.read_excel(staff_old_list_df,sheet_name="member_list",skiprows=1)
        except Exception as e:
            raise ValueError(f"{e}前年スタッフ条件ファイルの読み込みに失敗しました\n"
                            "ファイルが存在しないか、ファイル名が間違っている可能性があります")
            
        staff_column = next(
            (column for column in ("Name","スタッフ") if column in shift_df.columns),
            None,
        )
        day_column = next(
            (column for column in shift_df.columns if str(column).strip() =="31"),
            None,
        )
        if staff_column is None or day_column is None:
            raise ValueError(f"前年12月31日シフト列が見つかりません。\n"
                            "読み込む前年のシフト表の列名が正しいか確認してください。")
        
        worked_staff = set()
        outpatient_staff = set(
            staff_old_list_df.loc[
                staff_old_list_df['Floor'].astype(str).str.strip().eq("外来"),
                'Name',
            ].map(normalize_staff_name)
        )
        for _, row in shift_df[[staff_column,day_column]].iterrows():
            staff_name = normalize_staff_name(row[staff_column])
            if not staff_name:
                continue
            shift_value = row[day_column]
            if pd.isna(shift_value):
                shift_value = "出"
            
            if staff_name in outpatient_staff:
                shift_value = float('nan')
                
            shift_text = "" if pd.isna(shift_value) else str(shift_value).strip()
            if shift_text and not any(marker in shift_text for marker in ("休","休み" ,"指", "有", "夏", "慶","慶弔","育","育休","特")):
                worked_staff.add(staff_name)
                
        return worked_staff

    def _load_previous_january_staff_conditions(year: int) -> pd.DataFrame:
        """前年1月のスタッフ条件を1回だけ読み込む。"""
        staff_conditions_path = tkinter.filedialog.askopenfilename(
            title=f"前年スタッフ条件ファイルを選択してください({year-1}年1月)",
            filetypes=[("Excel files", "*.xlsx *.xls")],
        )
        try:
            return pd.read_excel(
                staff_conditions_path,
                sheet_name="member_list",
                skiprows=1,
            )
        except Exception as exc:
            raise ValueError(
                f"{exc}: 前年1月のスタッフ条件ファイルを読み込めません。"
            ) from exc



    def _load_previous_january_staff(
        year: int,
        day: int,
        staff_df: pd.DataFrame | None = None,
    ) -> set[str]:
        """前年1月の指定日に勤務したスタッフ名を読み込む。"""
        shift_csv = Path(f"result/Shift_cleaned_{year - 1}_01.csv")
        if not shift_csv.exists():
            print(f"前年1月シフトファイルが見つかりません: {shift_csv}")
            return set()

        try:
            shift_df = pd.read_csv(shift_csv, encoding="utf-8-sig")
        except Exception as exc:
            print(f"前年1月シフトファイルの読み込みに失敗しました: {exc}")
            return set()

        if staff_df is None:
            staff_df =GetPreviousData._load_previous_january_staff_conditions(year)

        staff_column = next(
            (column for column in ("Name", "スタッフ") if column in shift_df.columns),
            None,
        )
        day_column = next(
            (
                column
                for column in shift_df.columns
                if str(column).strip() == str(day)
            ),
            None,
        )

        if staff_column is None or day_column is None:
            print(
                f"前年1月シフトファイルにスタッフ列または{day}日列がありません: "
                f"{shift_csv}"
            )
            return set()

        outpatient_staff = set(
            staff_df.loc[
                staff_df["Floor"].astype(str).str.strip().eq("外来"),
                "Name",
            ].map(normalize_staff_name)
        )

        worked_staff = set()

        for _, row in shift_df[[staff_column, day_column]].iterrows():
            staff_name = normalize_staff_name(row[staff_column])
            if not staff_name or staff_name in outpatient_staff:
                continue

            shift_value = row[day_column]
            if pd.isna(shift_value):
                shift_value = "出"

            shift_text = str(shift_value).strip()
            if shift_text and not any(
                marker in shift_text
                for marker in _PREVIOUS_JANUARY_WORK_MARKERS
            ):
                worked_staff.add(staff_name)

        print(
            f"前年1月{day}日の勤務者を読み込みました: "
            f"{sorted(worked_staff)}"
        )
        return worked_staff
