##このmain.pyはシフトツールのテスト用スクリプトです。
##通常tkinterやintで作成年月のファイル選択を行うが、テスト用に固定パスを使用しているバージョンです。
##制約：それ以外は元のmain.pyから変更しないこと

import calendar
import random
from optimizer.mode1.shift_optimizer import ShiftOptimizer
from tkinter import filedialog
from ortools.sat.python import cp_model
from required_staff import RequiredStaff
import pandas as pd
pd.set_option('display.max_columns', None)
pd.set_option('display.max_rows', None)
pd.set_option('display.width', None)
pd.set_option('display.max_colwidth', None)
from config.sections import PRIMARY_SECTIONS
from config.concurrent_sections import CONCURRENT_SECTIONS
import datetime
import jpholiday
import sys
from pathlib import Path
from mk_staff_column import MkStafflist
from requests.mk_requests import MkRequests
from staff_name_matching import (
    normalize_name_index,
    normalize_name_list,
    normalize_staff_name,
    validate_name_alignment,
)
import tkinter.filedialog
import os
from openpyxl import load_workbook
from openpyxl.styles import Border
from create_calender import CalendarCreator
from run_log import RunLog,TeeStream
from get_previous_data import GetPreviousData

iDir = os.path.abspath(os.path.dirname(__file__))

def _find_previous_month_file(file_prefix: str, year: int, month: int):
    """正規名を優先し、旧来のゼロ埋めなしファイル名も読み込む。"""
    prev_year, prev_month = GetPreviousData._get_previous_year_month(year, month)
    candidates = [
        Path(f"result/{file_prefix}_{prev_year}_{prev_month:02d}.csv"),
        Path(f"result/{file_prefix}_{prev_year}_{prev_month}.csv"),
    ]
    return next((path for path in candidates if path.exists()), candidates[0])

def _is_int_lile(c):
    s = str(c).strip()
    try:
        value = float(s)
    except (TypeError, ValueError):
        return False
    return value.is_integer()


def _normalize_day_columns(columns):
    return {
        column: str(int(float(str(column).strip())))
        for column in columns
        if _is_int_lile(column)
    }


def _cleaning_previous_month_shift(shift_df):
    #_load_previous_month_shiftで既に処理済みの場合は二重に列を落とさない
    if shift_df is None or shift_df.empty:
        return shift_df

    if shift_df.columns[0] != "Name":
        #1列目は何もデータが入っていないので削除、1行目は削除しない
        shift_df = shift_df.iloc[:, 1:]
        #○月→"Name"に列名を変更
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
            if _is_int_lile(column) and -8 <= int(str(column).strip()) <= -1
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
    shift_folder_path = "/Users/aizawaharuka/Documents/GitHub/shift_tool/読み込み用ファイル/前月までのシフトデータ"
    #filedialog.askdirectory(
    #    message = "直近12か月分の当直シフト表だけが入ったフォルダを選択してください",
    #    initialdir = iDir,
    #)
    return shift_folder_path
    
#複数シフトファイルを読み込み　ファイル一覧を取得する
def _load_previous_month_shifts_files():
    shift_folder_path = _load_previous_month_shifts_files_path()
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
            shift_df.rename(columns=_normalize_day_columns(shift_df.columns), inplace=True)
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
    shift_path = "/Users/aizawaharuka/Documents/GitHub/shift_tool/読み込み用ファイル/前月までのシフトデータ/9月休暇管理.xlsx"
    #tkinter.filedialog.askopenfilename(
    #    title = "前月シフトファイルを選択してください",
    #    initialdir=iDir,
    #    filetypes=[("Excel files", "*.xlsx")],
    #)
    
    if not Path(shift_path).exists():
        print(f"前月シフトファイルが見つかりません: {shift_path}")
        return None
    
    try:
        shift_df = pd.read_excel(shift_path)
        #1列目は何もデータが入っていないので削除し、2列目（○月など）を"Name"に統一する
        shift_df = shift_df.iloc[:, 1:]
        shift_df.rename(columns={shift_df.columns[0]: "Name"}, inplace=True)
        shift_df.rename(columns=_normalize_day_columns(shift_df.columns), inplace=True)
        day_columns = [c for c in shift_df.columns if _is_int_lile(c)]
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
    day_columns = [c for c in shift_df.columns if _is_int_lile(c)]
    print(f"更新後のday_columns: {day_columns}")
    previous_month_oncall_counts = _count_oncall_by_staff(shift_df, day_columns)
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

def _load_previous_month_oncall_staff_ids(year: int, month: int):    
    prev_year, prev_month = GetPreviousData._get_previous_year_month(year, month)
    oncall_csv = _find_previous_month_file("oncall_shift_wide", year, month)
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

def _load_previous_year_end_shift(year, month):
    """前年度の年末年始のシフト読み込み
    形式：csvファイル,excelファイル
    startcol等が異なればエラーを返して停止させる
    - 前年度12月または1月のシフト表作成時にのみ有効とする
    """
    if month not in [12,1]:
        return None
    
    prev_year = year -1 
    year_end_csv = Path(f"result/Shift_cleaned_{prev_year}_12.csv")
    year_start_csv = Path(f"result/Shift_cleaned_{year}_01.csv")
    year_end_excel = Path(f"result/Shift_cleaned_{prev_year}_12.xlsx")
    year_start_excel = Path(f"result/Shift_cleaned_{year}_01.xlsx")
    
    if not year_end_csv.exists() and not year_end_excel.exists():
        print(f"前年度年末シフトファイルが見つかりません: {year_end_csv} または {year_end_excel}")
        return None
    if not year_start_csv.exists() and not year_start_excel.exists():
        print(f"当年度年始シフトファイルが見つかりません: {year_start_csv} または {year_start_excel}")
        return None

    if year_end_csv.exists():
        try:
            year_end_shift = pd.read_csv(year_end_csv)
            print(f"前年12月シフトファイルを読み込みました: {year_end_csv}")
        except Exception as exc:
            print(f" {exc}\n"
                "前年12月シフトファイルの読み込みに失敗しました。\n行列が異なる可能性があります。\n前年12月シフトファイルを見直してください。\n"
                f"[csvファイルを使用したい場合]:\n"
                "CSVの1行目は、次の形式にしてください。\n"
                "\n"
                
                "Shift_cleaned_sample.csvの1行目は、次の形式にしてください。\n"
                "\n"
                "Name,1,2,3,4,5,6,7\n"
                "1列目の見出しは必ず「Name」にしてください。\n"
                "現在は「Name」以外になっているため、読み込みできません。\n"
                "\n"
                
                "1列目の見出しを「Name」に変更し、UTF-8形式のCSVとして保存してから再実行してください。\n"
                "\n"
                
                "2行目以降に曜日の列（月・火・水・木・金・土・日)のような記載がある場合は行ごと削除してください。\n"
                "\n"
                
                "読み込むファイルの形式は以下の様に整えてください\n"
                "[1行目] Name,1,2,3,4,5,6,7\n"
                "[2行目以降] スタッフ名,「◎」や「指」「休」等のシフト情報\n"
                "\n"
                
                "不明な際は「読み込み用ファイルの見本フォルダ」に格納されているShift_cleaned_sample.csvを参照してください。"
                )
            return None
        
    else:
        year_end_shift = pd.read_excel(year_end_excel)
    #12月25日以降を取得
    end_cols = [col for col in year_end_shift.columns if col.isdigit() and int(col) >= 25]
    #先頭の列名をNameへ統一する
    year_end_shift.rename(columns={year_end_shift.columns[0]: 'Name'}, inplace=True)
    year_end_shift = year_end_shift.loc[:, ['Name'] + end_cols]  # 12月25日以降の列のみを保持
    
    
    if year_start_csv.exists():
        year_start_shift = pd.read_csv(year_start_csv)
    else:
        year_start_shift = pd.read_excel(year_start_excel)
    # 1月1日から7日までを取得
    start_cols = [col for col in year_start_shift.columns if col.isdigit() and int(col) <= 7]
    #先頭の列名をNameへ統一する
    year_start_shift.rename(columns={year_start_shift.columns[0]: 'Name'}, inplace=True)
    year_start_shift = year_start_shift.loc[:, ['Name'] + start_cols]  # 1月1日から7日までの列のみを保持
    
    print(f"前年度年末年始シフトのプレビュー{pd.concat([year_end_shift, year_start_shift], ignore_index=True)}")
    return pd.concat([year_end_shift, year_start_shift], ignore_index=True)


def _load_previous_year_december_30_staff(year: int):
    """前年12月30日に勤務したスタッフ名を読み込む。"""
    shift_candidates = [
        Path(f"result/Shift_cleaned_{year - 1}_12.csv"),
        Path(f"result/Shift_wide_{year - 1}_12.csv"),
    ]
    shift_csv = next((path for path in shift_candidates if path.exists()), None)
    if shift_csv is None:
        print(f"前年12月シフトファイルが見つかりません: {shift_candidates}")
        return set()

    try:
        shift_df = pd.read_csv(shift_csv, encoding="utf-8-sig")
    except Exception as exc:
        print(f"前年12月シフトファイルの読み込みに失敗しました: {exc}")
        return set()
    """昨年のスタッフ条件.xlsxを参照する"""
    staff_old_list_pass = Path(f"スタッフ条件_テスト_{year - 1}_12.xlsx")#TODO:テスト」を除外する
    print(f"前年スタッフ条件ファイルを読み込みました: {staff_old_list_pass}")
    try:
        staff_old_list_df = pd.read_excel(staff_old_list_pass, sheet_name="member_list", skiprows=1)
        print(f"前年スタッフ条件ファイルのプレビュー:\n{staff_old_list_df.head()}")
    except Exception as exc:
        print(f"前年スタッフ条件ファイルを読み込めないため、外来除外なしで判定します: {exc}")
        staff_old_list_df = None
    
    staff_column = next(
        (column for column in ("Name", "スタッフ") if column in shift_df.columns),
        None,
    )
    day_column = next(
        (column for column in shift_df.columns if str(column).strip() == "30"),
        None,
    )
    if staff_column is None or day_column is None:
        print(f"前年12月シフトファイルにスタッフ列または30日列がありません: {shift_csv}")
        return set()

    worked_staff = set()
    outpatient_staff = set()
    if staff_old_list_df is not None and {'Floor', 'Name'}.issubset(staff_old_list_df.columns):
        outpatient_staff = set(
            staff_old_list_df.loc[
                staff_old_list_df['Floor'].astype(str).str.strip().eq("外来"),
                'Name',
            ].map(normalize_staff_name)
        )
    for _, row in shift_df[[staff_column, day_column]].iterrows():
        staff_name = normalize_staff_name(row[staff_column])
        if not staff_name:
            continue
        shift_value = row[day_column]
        #空白の部分NaNは”出”に変換する
        if pd.isna(shift_value):
            shift_value = "出"
        #スタッフ条件.xlsxを参照して、「外来」部門スタッフの"出"は再びNaNに変換する
        #外来部門スタッフは12/30の「出」を無視する
        if staff_name in outpatient_staff:
            print(f"外来部門スタッフの勤務情報を無視します: {staff_name}")
            shift_value = float('nan')
        print(f"スタッフ: {staff_name}, シフト値: {shift_value}")
        shift_text = "" if pd.isna(shift_value) else str(shift_value).strip()#外来部門の情報は無視する
        if shift_text and not any(marker in shift_text for marker in ("休","休み" ,"指", "有", "夏", "慶","慶弔","育","育休","特","研","学")):
            print(f"勤務情報: {shift_text}")
            worked_staff.add(staff_name)
    print(f"前年12月30日の勤務者を読み込みました: {sorted(worked_staff)}")
    return worked_staff

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
    staff_old_list_df = "/Users/aizawaharuka/Documents/GitHub/shift_tool/読み込み用ファイル/スタッフ条件/スタッフ条件_テスト_2025_12.xlsx"
    #tkinter.filedialog.askopenfilename(
    #    title=f"前年スタッフ条件ファイルを選択してください({year-1}年12月)",
    #    filetypes=[("Excel files", "*.xlsx *.xls")],
    #)
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

_PREVIOUS_JANUARY_WORK_MARKERS = (
    "休", "休み", "指", "有", "夏",
    "慶", "慶弔", "育", "育休", "特",
)


def _load_previous_january_staff_conditions(year: int) -> pd.DataFrame:
    """前年1月のスタッフ条件を1回だけ読み込む。"""
    staff_conditions_path = "/Users/aizawaharuka/Documents/GitHub/shift_tool/読み込み用ファイル/スタッフ条件/スタッフ条件_テスト_2025_01.xlsx"
    #tkinter.filedialog.askopenfilename(
    #    title=f"前年スタッフ条件ファイルを選択してください({year-1}年1月)",
    #    filetypes=[("Excel files", "*.xlsx *.xls")],
    #)
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
        staff_df = _load_previous_january_staff_conditions(year)

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

def _load_previous_january_1_staff(year: int):
    return _load_previous_january_staff(year, 1)


def _load_previous_january_2_staff(year: int):
    return _load_previous_january_staff(year, 2)


def _load_previous_january_3_staff(year: int):
    return _load_previous_january_staff(year, 3)

def _print_fairness_summary(df_result: pd.DataFrame):
    """専属業務・当直の偏りサマリを表示する。"""
    print("\n===== 公平性サマリ =====")

    primary_df = df_result[df_result['専属業務'].isin(['休み', '明け']) == False]
    if primary_df.empty:
        print("専属業務: 対象データなし")
    else:
        primary_counts = primary_df.groupby(['専属業務', 'Name']).size().unstack(fill_value=0)
        for section_name, row in primary_counts.iterrows():
            max_count = int(row.max())
            min_count = int(row.min())
            diff = max_count - min_count
            print(f"専属業務[{section_name}] max={max_count} min={min_count} diff={diff}")

    oncall_series = df_result.groupby('Name')['当直'].apply(
        lambda values: sum(1 for val in values if ('当直担当' in val or '当直相方' in val))
    )
    if oncall_series.empty:
        print("当直: 対象データなし")
    else:
        oncall_max = int(oncall_series.max())
        oncall_min = int(oncall_series.min())
        oncall_diff = oncall_max - oncall_min
        print(f"当直回数 max={oncall_max} min={oncall_min} diff={oncall_diff}")


def _cleanup_weekly_df(week_df: pd.DataFrame, staff_info=None,year:int=None,month:int=None,) -> pd.DataFrame:
    """
    TODO:第二段階で使うかも
    週ごとのシフト結果を整形する。
    - 外来行は当直者のみ表示
    - 当直者名の末尾に◎を付与する
    - 兼務業務内容を反映する
    - 監査AMの記載があるスタッフは専属業務名を「監査AM」に変更する
    week_df:
        index: 専属業務
        columns: 日付（曜日）
        values: スタッフ名
    staff_info:Shiftoptimizer.staff
    week_df_original:改行編集前の元データ
    """
    source_df = week_df.copy()
    # 緩和回診のAM担当を「専属業務」列に反映する
    palliative_care_mask = source_df['兼務業務'].str.contains('緩和回診', na=False)
    week_df.loc[palliative_care_mask, 'Name'] = (
        'AM' + source_df.loc[palliative_care_mask, 'Name'].astype(str)
    )
    
    #専属業務列に[休み、明け]を含むデータは除外する
    #監査があるスタッフを専属業務名に反映する
    audit_am_rows = source_df[source_df['兼務業務'].str.contains('監査_AM',na=False)].copy()
    audit_am_rows['専属業務'] = '監査_AM'
    week_df = pd.concat([week_df, audit_am_rows], ignore_index=True)
    audit_pm_rows = source_df[source_df['兼務業務'].str.contains('監査_PM',na=False)].copy()
    audit_pm_rows['専属業務'] = '監査_PM'
    week_df = pd.concat([week_df, audit_pm_rows], ignore_index=True)
    
    ###兼務業務名の反映
    #RI兼務業務があるスタッフは専属業務　RI行を追加作成、書き換えではなく、RI行を追加する
    ri_rows = source_df[source_df['兼務業務'].str.contains('RI',na=False)].copy()
    ri_rows['専属業務'] = 'RI'
    week_df = pd.concat([week_df, ri_rows], ignore_index=True)
    #心不全回診
    heart_team_rows = source_df[source_df['兼務業務'].str.contains('心不全回診',na=False)].copy()
    heart_team_rows['専属業務'] = '心不全回診'
    week_df = pd.concat([week_df, heart_team_rows], ignore_index=True)
    #役職者会議
    exective_meeting_rows = source_df[source_df['兼務業務'].str.contains('役職者会議',na=False)].copy()
    exective_meeting_rows['専属業務'] = '役職者会議'
    week_df = pd.concat([week_df, exective_meeting_rows], ignore_index=True)    
    #医薬品安全使用WG
    safety_wg_rows = source_df[source_df['兼務業務'].str.contains('医薬品安全使用WG',na=False)].copy()
    safety_wg_rows['専属業務'] = '医薬品安全使用WG'
    week_df = pd.concat([week_df, safety_wg_rows], ignore_index=True)
    
    #緩和回診の午後担当を「その他」表示用の行として追加
    palliative_care_rows = source_df.loc[palliative_care_mask].copy()
    palliative_care_rows['専属業務'] = '緩和回診'
    palliative_care_rows['兼務業務'] = '緩和回診'
    palliative_care_rows['Name'] = (
        'PM' + palliative_care_rows['Name'].astype(str)
    )
    week_df = pd.concat([week_df, palliative_care_rows], ignore_index=True)
    
    
    #認知症せん妄ラウンド
    dementia_round_rows = source_df[source_df['兼務業務'].str.contains('認知症せん妄ラウンド',na=False)].copy()
    dementia_round_rows['専属業務'] = '認知症せん妄ラウンド'
    week_df = pd.concat([week_df, dementia_round_rows], ignore_index=True)
    #感染管理,AST
    infection_control_rows = source_df[source_df['兼務業務'].str.contains('感染管理,AST',na=False)].copy()
    infection_control_rows['専属業務'] = '感染管理,AST'
    week_df = pd.concat([week_df, infection_control_rows], ignore_index=True)
    #金曜日のポリファーマシー
    dates = pd.to_datetime(
    source_df["日付"].map(
            lambda value: f"{year}-{month}-{str(value).split('/')[-1]}"
        ),
        format="%Y-%m-%d",
        errors="coerce",
    )

    friday_rows = source_df[
        source_df["兼務業務"].str.contains("ポリファーマシー", na=False)
        & (dates.dt.day_name(locale="ja_JP") == "金曜日")
    ].copy()
    friday_rows['専属業務'] = 'ポリファーマシーチーム'
    week_df = pd.concat([week_df, friday_rows], ignore_index=True)
    return week_df

def _add_section_name(week_df:pd.DataFrame, section_name:str):
    week_df.loc[section_name]=week_df.loc[section_name].apply(
        lambda cell:(
            f'{section_name}:\n{cell}'
            if pd.notna(cell) and str(cell).strip()
            else cell
        )
    )
    return week_df

def change_porifa(df_result: pd.DataFrame, year: int,month: int):
    # ポリファーマシー（火曜日）は専任
    # 対象の火曜日日付を抽出,month,year情報から
    max_day = calendar.monthrange(year, month)[1]
    tuesday_days = [day for day in range(1,max_day+1) if pd.Timestamp(year=year, month=month, day=day).day_name(locale='ja_JP') == '火曜日']
    
    # 火曜日のポリファーマシーを専任にコピー
    for day in tuesday_days:
        df_result.loc[
            (df_result['日付'] == day) & (df_result['兼務業務'].str.contains('ポリファーマシー', na=False)),
            '専属業務'
        ] = 'ポリファーマシーチーム'
    return df_result
    
def mk_weekly_shift_schedule(df_result: pd.DataFrame, year: int, month: int, weekly_dir: Path,staff_info=None):
    """週ごとのシフト結果をまとめたxlsxファイルを作成する。

    ``df_result`` の日付を表示用の ``MM/DD (曜日)`` 形式に整え、
    後続処理で週単位に集計・保存できる形に変換する。元のDataFrameを
    直接更新するため、この関数の呼び出し後は日付列が文字列になる点に注意する。
    """
    files = []
    
    # ポリファーマシー（火曜日）は専任にコピーする
    df_result = change_porifa(df_result, year, month)
    
    # 週ごとに分割して保存する前に、日付を日時型へ変換する。
    # 不正な値はエラーにせずNaTにすることで、他の日付の処理を継続する。
    #df_result['日付']には%dの情報しかないので、　yearとmonthを指定して、日付を作成する。
    #あとで日付型を日判定に使う場合もあるので、元の日時型を保持しておく場合はここでコピーしておく。
    df_result['日付_datetime'] = df_result['日付']
    df_result['日付'] = pd.to_datetime(df_result['日付'].apply(lambda x: f"{year}-{month}-{x}"), errors='coerce', format='%Y-%m-%d')
    # 日付から日本語の曜日名を作成し、Excelで見やすい表示用文字列を組み立てる。
    df_result['曜日'] = df_result['日付'].dt.day_name(locale='ja_JP')
    df_result['日付'] = df_result['日付'].dt.strftime('%m/%d')
    df_result['日付_曜日'] = df_result['日付']
    df_result['日付_曜日'] = df_result['日付_曜日'] + ' (' + df_result['曜日'] + ')'
    
    # 名前を週間表示用の名前に変換する
    if staff_info is not None and '表示名' in staff_info.columns:
        display_names = staff_info['表示名'].to_dict()
        df_result['Name'] = df_result['Name'].map(
            lambda name: display_names.get(name)
            if pd.notna(display_names.get(name)) and str(display_names.get(name)).strip()
            else name
        )
    
    # 当直担当または当直相方の行だけ、表示名の末尾に二重丸を付加する。
    df_result['Name'] = df_result.apply(
        lambda row: (
            f"{row['Name']} ◎"
            if pd.notna(row['Name'])
            and str(row['Name']).strip()
            and any(role in str(row.get('当直', '')) for role in ('当直担当', '当直相方'))
            else row['Name']
        ),
        axis=1,
    )
    
    #「外来」部門は当直者だけ週間予定表に名前を記載するので、専属業務＝＝外来　& 当直担当または当直相方でない場合は名前を空にする。
    df_result.loc[
        (df_result['専属業務'] == '外来') &
        (~df_result['当直'].str.contains('当直担当|当直相方', na=False)),
        'Name'
    ] = ''

    # 専属業務が休みの場合は兼務業務も休みに統一し、週間表では休みのみが残るようにする。
    df_result['専属業務'] = df_result['専属業務'].fillna('').astype(str).str.strip()
    df_result['兼務業務'] = df_result.apply(
        lambda row: '休み' if str(row['専属業務']).strip() in {'休み', '休'} else row['兼務業務'],
        axis=1,
    )
    
    # 週ごとに分割して保存する　週間予定表の作成
    df_result['週番号']=df_result['日付'].apply(lambda x: pd.to_datetime(f"{year}-{month}-{x.split('/')[1]}").isocalendar()[1])
    for week_num, week_df in df_result.groupby('週番号'):
        week_df.drop(columns=['週番号'], inplace=True)
        # シフト表のクリーニングと整形
        week_df = _cleanup_weekly_df(week_df = week_df,staff_info=staff_info,year=year,month=month)
        #書き出し用に整形する
        #　行：調剤室、監査AM、監査PM、化療AM、化療PM、1-2階、３階、４階、５階、入退院センター、RI、医療安全・感染管理、DI等
        # 列：日付（曜日）
        #　セル内：スタッフ名
        week_df = week_df.pivot_table(
            index='専属業務',
            columns='日付_曜日',
            values='Name',
            aggfunc=lambda x: '\n'.join(x)  # 同じ専属業務に複数のスタッフがいる場合は改行して表示,最後に編集したい
        )
        if '緩和回診(専任)' in week_df.index:
            week_df = _add_section_name(week_df, '緩和回診(専任)')
        if 'ポリファーマシーチーム' in week_df.index:
            week_df = _add_section_name(week_df, 'ポリファーマシーチーム')
        if '認知症せん妄ラウンド' in week_df.index:
            week_df = _add_section_name(week_df, '認知症せん妄ラウンド')
        if '心不全回診' in week_df.index:
            week_df = _add_section_name(week_df, '心不全回診')
        if 'NST' in week_df.index:
            week_df = _add_section_name(week_df, 'NST')
        if '実習' in week_df.index:
            week_df = _add_section_name(week_df, '実習')
        if 'マスター管理' in week_df.index:
            week_df = _add_section_name(week_df, 'マスター管理')
        # 医薬品安全使用WGの行が存在する場合、セルの内容の先頭に「医薬品安全使用WG:」を付加する
        if '医薬品安全使用WG' in week_df.index:
            week_df = _add_section_name(week_df, '医薬品安全使用WG')
        if '役職者会議' in week_df.index:
            week_df = _add_section_name(week_df, '役職者会議')
        if '学会' in week_df.index:
            week_df = _add_section_name(week_df, '学会')
        if '研修' in week_df.index:
            week_df = _add_section_name(week_df, '研修')
        if '緩和回診' in week_df.index:
            week_df = _add_section_name(week_df, '緩和回診')
        
        #その他」行を新規作成、『'緩和回診(専任)','ポリファーマシーチーム','認知症せん妄ラウンド','心不全回診','NST','実習','マスター管理','医薬品安全使用WG','役職者会議','学会','研修'}内のテキストは\nを挟んで全て並べて入れる
        #兼務業務のうち、「臨床薬剤課会議」は参加者多数のため表には表示しない、ohther_sectionsにも含めない
        other_sections = ['緩和回診','緩和回診(専任)','ポリファーマシーチーム','認知症せん妄ラウンド','心不全回診','NST回診','実習','マスター管理','医薬品安全使用WG','役職者会議','学会','研修','ICT回診','薬審']
        present_sections = [
            section for section in other_sections
            if section in week_df.index
        ]

        if present_sections:
            other_row = week_df.loc[present_sections].apply(
                lambda cells: '\n\n'.join(
                    str(value)
                    for value in cells
                    if pd.notna(value) and str(value).strip()
                ),
                axis=0,
            )
        else:
            other_row = pd.Series('', index=week_df.columns)

        week_df.loc['その他'] = other_row

        #行の順番を固定
        #指定した行だけ出力されるので、「休み」や「明け」は出力されない
        week_df = week_df.reindex(
        ['調剤室','監査_AM','監査_PM','化療','1-2階','3階','4階','5階','入退院センター','RI','医療安全・感染管理','AST','DI','課長業務','課長','部長','感染管理,AST','外来','その他',
        ],
        )
        week_file = weekly_dir / f"Shift_week_{year}_{month:02d}_week{week_num}.xlsx"
        week_df.to_excel(week_file, index=True)
        files.append(week_file)
    return files

def create_shift_schedule():
    """
    ========================================
    1. データ読み込み
    ========================================
    """    
    # 初期ディレクトリをスクリプトのあるディレクトリに設定
    iDir = os.path.abspath(os.path.dirname(__file__))
    
    print("================================================================================")
    print("シフト作成を開始します。対象年と対象月はこれから入力してください。入力は半角でお願いします。\n"
        "入力が終わったらEnterキーで次に進みます。\n"
        "\n"
        "Enterキーで進んだ後、一つ前に戻りたい場合・入力をし直したい場合・作成をキャンセルしたい場合は一旦終了が必要です。\n"
        "Control+Cでキャンセルできます。"
        "\n")
    print("これはテスト起動用のmain.pyのため、年度・月、条件ファイルの読み込みは固定パスで設定されます。")
    year = int(2026)#対象年を設定してください→2026で固定
    month = int(10)#対象月を設定してください→10月で固定
    offrequest_day = 9 #今月の指定休を入力してください→10月は9日で固定
    if month < 1 or month > 12:
        print("エラー: 月は1から12の範囲で指定してください。")
        return 1
    #日曜祝日の取得
    holidays = jpholiday.month_holidays(year=year,month=month)
    #staff_list_pass = input("スタッフリストのファイルパスを入力してください（例：staff_list.xlsx）: ")
    #月毎にスタッフ条件が変わるものは関数で変更(新人の条件など)
    

    #スタッフ条件のシートを読み込み
    staff_list_pass = "/Users/aizawaharuka/Documents/GitHub/shift_tool/読み込み用ファイル/スタッフ条件/スタッフ条件_2026_10.xlsx"#tkinter.filedialog.askopenfilename(title="スタッフ条件のファイルを選択してください",nitialdir=iDir,filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")])
    if not staff_list_pass:
        print("エラー: スタッフ条件のファイルが選択されませんでした。")
        return 1

    previous_month_shift = _load_previous_month_shift()#前月のシフト
    previous_month_oncall_counts = (
        dict(previous_month_shift.attrs.get('oncall_counts', {}))
        if previous_month_shift is not None else {}
    )
    previous_month_shift = _cleaning_previous_month_shift(previous_month_shift)
    previous_month_oncall_staff_ids = _extract_previous_month_oncall_staff_ids(
        previous_month_shift
    )
    if not previous_month_oncall_staff_ids:
        previous_month_oncall_staff_ids = _load_previous_month_oncall_staff_ids(
            year=year, month=month
        )
    previous_month_shifts = _read_previous_month_shifts_files(
        _load_previous_month_shifts_files()
    )
    #前月の当直回数集計
    previous_oncall_counts = _sum_previous_month_shifts(previous_month_shifts)# 前月の当直回数を集計
    previous_months_with_two_oncalls = (
        _count_previous_months_with_two_oncalls(previous_month_shifts)
    )# 過去に当直が月ちょうど2回だった回数を集計

    previous_year_end_shift = _load_previous_year_end_shift(year=year, month=month)#前年度の年末年始のシフト
    previous_year_december_30_staff = set()
    previous_december_31_staff = set()
    if month == 12:
        previous_year_december_30_staff = _load_previous_year_december_30_staff(year)
        previous_december_31_staff = _load_previous_december_31_staff(year)
    previous_january_1_staff = set()
    previous_january_2_staff = set()
    previous_january_3_staff = set()
    if month == 1:
        previous_january_staff_df = None
        if Path(f"result/Shift_cleaned_{year - 1}_01.csv").exists():
            previous_january_staff_df = _load_previous_january_staff_conditions(year)
        previous_january_1_staff = _load_previous_january_staff(
            year, 1, previous_january_staff_df
        )
        previous_january_2_staff = _load_previous_january_staff(
            year, 2, previous_january_staff_df
        )
        previous_january_3_staff = _load_previous_january_staff(
            year, 3, previous_january_staff_df
        )

    #フロア毎の必要人数リストを作成
    required_num_list = RequiredStaff(year=year, month=month, date=1, section=None)
    # Name列をキーにしてスタッフ条件と希望リストを突合する
    staff_list_df = pd.read_excel(staff_list_pass, sheet_name="member_list", skiprows=1)
    staff_list_df = normalize_name_index(
        staff_list_df,
        source_label=staff_list_pass,
        name_column="Name",
        allow_index_fallback=False,
    )

    hope_list_pass = "/Users/aizawaharuka/Documents/GitHub/shift_tool/読み込み用ファイル/希望表/10月 出欠確認.xlsx"#tkinter.filedialog.askopenfilename(title="希望リストのファイルを選択してください",initialdir=iDir,filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")])
    if not hope_list_pass:
        print("エラー: 希望リストのファイルが選択されませんでした。")
        return 1
    hope_list = pd.read_excel(hope_list_pass,skiprows=[1])
    #1列目は何もデータが入っていないので削除,1行目は削除しない
    hope_list = hope_list.iloc[:, 1:]
    #○月→"Name"に変更
    hope_list.rename(columns={hope_list.columns[0]: "Name"}, inplace=True)
    #31日分までの列に絞る,該当付きが28日までなら28日までの列,30日までなら30日までの列に絞る
    hope_list = hope_list.iloc[:, :min(32, hope_list.shape[1])]

    #スペーサー行など"Name"列が空の行は正規化前に削除する
    hope_list = hope_list[hope_list["Name"].notna()]

    hope_list = normalize_name_index(
        hope_list,
        source_label=hope_list_pass,
        name_column="Name",
        allow_index_fallback=True,
    )
    #NaNは"なし"に置換する
    hope_list = hope_list.replace(pd.NA, "なし")
    validate_name_alignment(staff_list_df, hope_list)
    
    
    ##休み希望・制約条件を組み込んだshift_requests_専属、shift_requests_兼務　,shift＿requests_当直を作成
    """
    ========================================
    2. 変数定義
    ========================================    
    """
    try:
        optimizer = ShiftOptimizer(year=year,month=month,holidays=holidays,
                                offrequest_day=offrequest_day,
                                staff_list_pass=staff_list_pass,
                                hope_list=hope_list,
                                previous_month_oncall_staff_ids=previous_month_oncall_staff_ids,
                                previous_oncall_counts=previous_oncall_counts,
                                previous_month_oncall_counts=previous_month_oncall_counts,
                                previous_months_with_two_oncalls=previous_months_with_two_oncalls,
                                previous_month_shift=previous_month_shift,
                                previous_year_end_shift=previous_year_end_shift,
                                previous_year_december_30_staff=previous_year_december_30_staff,
                                previous_december_31_staff=previous_december_31_staff,
                                previous_january_1_staff=previous_january_1_staff,
                                previous_january_2_staff=previous_january_2_staff,
                                previous_january_3_staff=previous_january_3_staff)
        print("シフト最適化モデルの初期化が完了しました。")
        optimizer._get_days_in_month()
        optimizer.create_variables()
        
    
        """
        ========================================
        3. 最適化モデル構築
        ========================================
        """
        #全ての制約を一括適用
        optimizer._init_constraints()#初期化
        optimizer.apply_all_constraints()

        
        
        
        solver = cp_model.CpSolver()
        solver.parameters.log_search_progress = True  # 探索ログを有効化
        solver.log_callback = lambda message:print(
            message,
            end="" if message.endswith("\n") else "\n",
            flush=True,
        )
        solver.parameters.max_time_in_seconds = 300 # タイムアウトを5分に設定
        solver.parameters.relative_gap_limit = 0.03 # 最適性ギャップの制限を3%に設定
        validation_message = optimizer.model.Validate()
        print(f"\n=====モデル検証======\n")
        print(f"Validation Message: {validation_message}")
        
        print("\n===== モデル統計 =====")
        print(optimizer.model.ModelStats())

        status = solver.Solve(optimizer.model)
        if status == cp_model.INFEASIBLE:
            # モデルが infeasible の場合、制約診断を出力する
            optimizer.model.write_constraint_diagnostics(
                optimizer.year,
                optimizer.month,
                solver=solver,
            )

        status_name = solver.StatusName(status)

        print(f"\n== ソルバー結果 ==")
        print(f"Solver Status: {status_name}")
        print(f"status code: {status}")
        print(f"wall_time: {solver.WallTime()}")
        print(f"response_status: {solver.ResponseStats()}")
        

        """
        ========================================
        6. 結果の出力
        ========================================
        休みに全て指定休を入れていき、最後に希望の休みの日に有給を入れていく
        病棟グループ別の並び替えから、年代順の並び方へ変更をする
        
        """
        
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            print("シフトの最適化が成功しました。")
            
            # DataFrameで結果を整理
            shift_result = []
            for staff in optimizer.staff.index:
                staff_name = staff
                for day in range(1, optimizer.days + 1):
                    work_status = optimizer.get_primary_work_status(
                        solver, staff, day
                    )
                    row = {
                        'Name': staff,
                        '日付': day,
                        '勤務状態': (
                            '未判定'
                            if work_status is None
                            else '出勤' if work_status else '非出勤'
                        ),
                        '当直': [],
                    }
                    #TODO:第二段階で必要かも
                    #for section in optimizer.primary_sections:
                    #    if solver.Value(optimizer.shifts[(staff, day, section)]) == 1:
                    #        row['専属業務'] = section
                    #        break
                    #TODO:第二段階で必要かも
                    #専属業務を番号から日本語名へ変換
                    #if isinstance(row['専属業務'], int):
                    #    row['専属業務'] = PRIMARY_SECTIONS[row['専属業務']]
                    #TODO:第二段階で必要かも
                    #for c_section in optimizer.concurrent_sections:
                    #    if solver.Value(optimizer.concurrent_shifts[(staff, day, c_section)]) == 1:
                    #        row['兼務業務'].append(c_section)
                    #TODO:第二段階で必要かも
                    #兼務業務を番号から日本語名へ変更
                    #if row['兼務業務']:
                    #    row['兼務業務'] = ', '.join([CONCURRENT_SECTIONS[c] for c in row['兼務業務']])
                    #else:
                    #    row['兼務業務'] = 'なし'

                    #当直の結果を出力、スタッフ・日付毎につきあり/なしかを記載
                    row['当直'] = []
                    if hasattr(optimizer,'night_shifts'):
                        for other_staff in optimizer.staff.index:
                            pair_var = optimizer.get_oncall_pair(staff, other_staff, day)
                            if pair_var is None or solver.Value(pair_var) != 1:
                                continue
                            if staff < other_staff:
                                row['当直'].append(f'当直担当（相方: {other_staff}）')
                            else:
                                row['当直'].append(f'当直相方（担当: {other_staff}）')
                    
                    row['当直'] = ', '.join(row['当直']) if row['当直'] else 'なし'
                    shift_result.append(row)
            
            df_result = pd.DataFrame(shift_result)
            print("\n===== シフト結果 =====")
            CalendarCreator().save_results(df_result, hope_list, optimizer, year, month)

            #専属業務の公平性を計算する スタッフ条件のFloor間にて計算する
            #TODO:第二段階で必要かも
            #_print_fairness_summary(df_result)
            
            #週ごとのシフト結果をまとめたxlsxファイルを作成#TODO:第二段階で必要かも
            #作成した結果はweeklyフォルダに格納する
            #weeklyフォルダはなければ作成する
            weekly_dir = Path("result/weekly")
            weekly_dir.mkdir(exist_ok=True)
            #週ごとのシフト結果をまとめたxlsxファイルを作成
            # weekly_files = mk_weekly_shift_schedule(df_result,year,month,weekly_dir,optimizer.staff)#TODO:第二段階で必要かも
            
            # 統計情報の表示
            print("\n===== 統計情報 =====")
            print(f"ステータス: {'最適解' if status == cp_model.OPTIMAL else '実行可能解'}")
            print(f"解決時間: {solver.WallTime()}秒")
        else:
            print("シフトの最適化に失敗しました。最適な解が見つかりませんでした。")
            return 1
    except FileNotFoundError as e:
        print(f"エラー: スタッフリストのファイルが見つかりません。パスを確認してください。詳細: {e}")
        return 1
    except Exception as e:
        print(f"予期しないエラーが発生しました。詳細: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    RunLog._setup_run_log()
    create_shift_schedule()