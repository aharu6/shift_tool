import random
from optimizer.shift_optimizer import ShiftOptimizer
from ortools.sat.python import cp_model
from required_staff import RequiredStaff
from check_staff_list import Check_staff_list
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


class _TeeStream:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)
        return len(data)

    def flush(self):
        for stream in self.streams:
            stream.flush()


def _setup_run_log() -> Path:
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"shift_run_{timestamp}.txt"

    log_file = open(log_path, "w", encoding="utf-8")
    sys.stdout = _TeeStream(sys.stdout, log_file)
    sys.stderr = _TeeStream(sys.stderr, log_file)

    print(f"実行ログを '{log_path}' に出力します。")
    return log_path


def _get_previous_year_month(year: int, month: int):
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _find_previous_month_file(file_prefix: str, year: int, month: int):
    """正規名を優先し、旧来のゼロ埋めなしファイル名も読み込む。"""
    prev_year, prev_month = _get_previous_year_month(year, month)
    candidates = [
        Path(f"result/{file_prefix}_{prev_year}_{prev_month:02d}.csv"),
        Path(f"result/{file_prefix}_{prev_year}_{prev_month}.csv"),
    ]
    return next((path for path in candidates if path.exists()), candidates[0])

def _is_int_lile(c):
    s = str(c).strip()
    return s.lstrip('-').isdigit() and s != ''

def _load_previous_month_shift(year: int, month: int):
    prev_year, prev_month = _get_previous_year_month(year, month)
    shift_csv = _find_previous_month_file("Shift_wide", year, month)
    print(f"前月シフトファイルのパス: {shift_csv}")#デバッグ用
    if not shift_csv.exists():
        print(f"前月シフトファイルが見つかりません: {shift_csv}")
        return None
    try:
        shift_df = pd.read_csv(shift_csv, encoding='utf-8-sig')
    except Exception as exc:
        print(f"前月シフトファイルの読み込みに失敗しました: {exc}")
        return None
    day_columns = [c for c in shift_df.columns if str(c).strip().isdigit()]
    if not day_columns:
        print(f"前月シフトファイルに日付列が見つかりません: {shift_csv}")
        return None
    
    print(f'読み込んだシフトの確認{shift_df.head()}')
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
    #sections.pyを使用してフロアを数字に変換 
    
    for offset_day in range(-1,-8,-1):#過去8日間を対象
        print(f"現在のターゲット日: {offset_day}")
        if str(offset_day) in day_columns:
            last_eight_days  = str(offset_day)
            if 'Name' not in shift_df.columns:
                print(f"前月シフトファイルにスタッフ列がないため、月初連携をスキップします: {shift_csv}")
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
    return shift_df[['Name'] + [str(offset_day) for offset_day in range(-1,-8,-1) if str(offset_day) in shift_df.columns]]

def _load_previous_month_oncall_staff_ids(year: int, month: int):    
    prev_year, prev_month = _get_previous_year_month(year, month)
    oncall_csv = _find_previous_month_file("oncall_shift_wide", year, month)
    if not oncall_csv.exists():
        print(f"前月当直ファイルが見つかりません: {oncall_csv}")
        return []
    
    try:
        oncall_df = pd.read_csv(oncall_csv, encoding='utf-8-sig')
    except Exception as exc:
        print(f"前月当直ファイルの読み込みに失敗しました: {exc}")
        return []
    
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
                    print(f"当直者を追加: {row['Name']}")#デバッグ用
            print(f"前月末7日間の当直者を読み込みました: {prev_year}/{prev_month:02d} 対象={staff_names_dict}")
    if not staff_names_dict:
        print(f"前月末7日間の当直者が見つかりませんでした: {oncall_csv}")
    return staff_names_dict

def _load_previous_year_end_shift(year, month):
    """前年度の年末年始のシフト読み込み
    形式：csvファイル,excelファイル
    startcol等が異なればエラーを返して停止させる
    """
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
    shift_csv = Path(f"result/Shift_cleaned_{year - 1}_12.csv")
    if not shift_csv.exists():
        print(f"前年12月シフトファイルが見つかりません: {shift_csv}")
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
        print(f"前年スタッフ条件ファイルの読み込みに失敗しました: {exc}")
        raise ValueError(f"{exc}:前年スタッフ条件ファイルの読み込みに失敗しました。\n"
                        "ファイルが存在しないか、ファイル名が間違っている可能性があります。")
    
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
        #スタッフ条件.xlsxを参照して、「外来」部門スタッフの"出”は再びNaNに変換する
        #外来部門スタッフは12/30の「出」を無視する
        if staff_name in outpatient_staff:
            print(f"外来部門スタッフの勤務情報を無視します: {staff_name}")
            shift_value = float('nan')
        print(f"スタッフ: {staff_name}, シフト値: {shift_value}")
        shift_text = "" if pd.isna(shift_value) else str(shift_value).strip()#外来部門の情報は無視する
        if shift_text and not any(marker in shift_text for marker in ("休","休み" ,"指", "有", "夏", "慶","慶弔","育","育休")):
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
    staff_old_list_df =Path(f"スタッフ条件_テスト_{year-1}_12.xlsx")
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
        if shift_text and not any(marker in shift_text for marker in ("休","休み" ,"指", "有", "夏", "慶","慶弔","育","育休")):
            worked_staff.add(staff_name)
            
    return worked_staff

def _load_previous_january_1_staff(year:int):
    """前年1月1日で出勤していたスタッフを取得"""
    shift_csv = Path(f"result/Shift_cleaned_{year-1}_01.csv")
    if not shift_csv.exists():
        print(f"前年1月1日のシフトファイルがみつかりません:{shift_csv}")
        return set()
    
    try:
        shift_df = pd.read_csv(shift_csv,encoding="utf-8-sig")
    except Exception as e:
        print(f"前年1月シフトファイルの読み込みに失敗しました:{e}")
        return set()
    
    """昨年のスタッフ条件.xlsxを参照する"""
    staff_old_list_df = Path(f"スタッフ条件_テスト_{year-1}_01.xlsx")
    try:
        staff_old_list_df = pd.read_excel(staff_old_list_df,sheet_name="member_list",skiprows=1)
    except Exception as e:
        print(f"前年のスタッフ条件ファイルの読み込みに失敗しました:{e}")
        raise ValueError(f"{e}前年スタッフ条件ファイルの読み込みに失敗しました\n"
                        "ファイルが存在しないか、ファイル名が間違っている可能性があります")
        
    staff_column = next(
        (column for column in ("Name","スタッフ") if column in shift_df.columns),
        None,
    )
    day_column = next(
        (column for column in shift_df.columns if str(column).strip() == "1"),
        None,
    )
    if staff_column is None or day_column is None:
        print(f"前年1月1日のシフト列が見つかりません")
        raise ValueError(f"前年1月1日のシフト列が見つかりません\n"
                        "読み込む前年シフト表の列名が正しいか確認してください。")
    
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
        if shift_text and not any(marker in shift_text for marker in ("休","休み" ,"指", "有", "夏", "慶","慶弔","育","育休")):
            worked_staff.add(staff_name)
    
    return worked_staff
        
        
    
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


def _pivot_staff_day_wide(
    df: pd.DataFrame,
    value_column: str,
    fill_value: str,
) -> pd.DataFrame:
    """スタッフの入力順を維持したまま日付横持ちに変換する。"""
    return df.pivot_table(
        index='Name',
        columns='日付',
        values=value_column,
        aggfunc='first',
        fill_value=fill_value,
        sort=False,
    )


def _cleanup_weekly_df(week_df: pd.DataFrame, staff_info=None,year:int=None,month:int=None,) -> pd.DataFrame:
    """週ごとのシフト結果を整形する。
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
    #専属業務列に[休み、明け]を含むデータは除外する
    #監査があるスタッフを専属業務名に反映する
    audit_am_rows = week_df[week_df['兼務業務'].str.contains('監査_AM',na=False)].copy()
    audit_am_rows['専属業務'] = '監査_AM'
    week_df = pd.concat([week_df, audit_am_rows], ignore_index=True)
    audit_pm_rows = week_df[week_df['兼務業務'].str.contains('監査_PM',na=False)].copy()
    audit_pm_rows['専属業務'] = '監査_PM'
    week_df = pd.concat([week_df, audit_pm_rows], ignore_index=True)
    
    ###兼務業務名の反映
    #RI兼務業務があるスタッフは専属業務　RI行を追加作成、書き換えではなく、RI行を追加する
    ri_rows = week_df[week_df['兼務業務'].str.contains('RI',na=False)].copy()
    ri_rows['専属業務'] = 'RI'
    week_df = pd.concat([week_df, ri_rows], ignore_index=True)
    #心不全回診
    heart_team_rows = week_df[week_df['兼務業務'].str.contains('心不全回診',na=False)].copy()
    heart_team_rows['専属業務'] = '心不全回診'
    week_df = pd.concat([week_df, heart_team_rows], ignore_index=True)
    #役職者会議
    exective_meeting_rows = week_df[week_df['兼務業務'].str.contains('役職者会議',na=False)].copy()
    exective_meeting_rows['専属業務'] = '役職者会議'
    week_df = pd.concat([week_df, exective_meeting_rows], ignore_index=True)    
    #医薬品安全使用WG
    safety_wg_rows = week_df[week_df['兼務業務'].str.contains('医薬品安全使用WG',na=False)].copy()
    safety_wg_rows['専属業務'] = '医薬品安全使用WG'
    week_df = pd.concat([week_df, safety_wg_rows], ignore_index=True)
    #土曜日の化学療法室
    chemo_rows = week_df[week_df['兼務業務'].str.contains('化療',na=False)].copy()
    chemo_rows['専属業務'] = '化療'
    week_df = pd.concat([week_df, chemo_rows], ignore_index=True)
    #認知症せん妄ラウンド
    dementia_round_rows = week_df[week_df['兼務業務'].str.contains('認知症せん妄ラウンド',na=False)].copy()
    dementia_round_rows['専属業務'] = '認知症せん妄ラウンド'
    week_df = pd.concat([week_df, dementia_round_rows], ignore_index=True)
    return week_df

def mk_weekly_shift_schedule(df_result: pd.DataFrame, year: int, month: int, weekly_dir: Path,staff_info=None):
    """週ごとのシフト結果をまとめたxlsxファイルを作成する。

    ``df_result`` の日付を表示用の ``MM/DD (曜日)`` 形式に整え、
    後続処理で週単位に集計・保存できる形に変換する。元のDataFrameを
    直接更新するため、この関数の呼び出し後は日付列が文字列になる点に注意する。
    """
    files = []
    
    # 週ごとに分割して保存する前に、日付を日時型へ変換する。
    # 不正な値はエラーにせずNaTにすることで、他の日付の処理を継続する。
    #df_result['日付']には%dの情報しかないので、　yearとmonthを指定して、日付を作成する。
    df_result['日付'] = pd.to_datetime(df_result['日付'].apply(lambda x: f"{year}-{month}-{x}"), errors='coerce', format='%Y-%m-%d')
    # 日付から日本語の曜日名を作成し、Excelで見やすい表示用文字列を組み立てる。
    df_result['曜日'] = df_result['日付'].dt.day_name(locale='ja_JP')
    df_result['日付'] = df_result['日付'].dt.strftime('%m/%d')
    df_result['日付_曜日'] = df_result['日付']
    df_result['日付_曜日'] = df_result['日付_曜日'] + ' (' + df_result['曜日'] + ')'
    # 曜日は日付_曜日列へ取り込んだため、一時列を削除する。
    df_result.drop(columns=['曜日'], inplace=True)

    # 週ごとに分割して保存する
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
        #行の順番を固定
        #指定した行だけ出力されるので、「休み」や「明け」は出力されない
        week_df = week_df.reindex(
        ['調剤室','監査_AM','監査_PM','化療','1-2階','3階','4階','5階','入退院センター','RI','医療安全・感染管理','AST','DI','課長業務','課長','部長','外来',
        '緩和回診(専任)','ポリファーマシーチーム','認知症せん妄ラウンド','心不全回診','NST','実習','マスター管理','医薬品安全使用WG','役職者会議'],
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
    year = int(input("対象年を入力してください（例：2026）: "))
    month = int(input("対象月を入力してください（例：1～12）: "))
    if month < 1 or month > 12:
        print("エラー: 月は1から12の範囲で指定してください。")
        return 1
    #日曜祝日の取得
    holidays = jpholiday.month_holidays(year=year,month=month)
    #staff_list_pass = input("スタッフリストのファイルパスを入力してください（例：staff_list.xlsx）: ")
    #月毎にスタッフ条件が変わるものは関数で変更(新人の条件など)
    
    #スタッフ条件のシートを読み込み
    staff_list_pass = f"スタッフ条件_テスト_{year}_{month}.xlsx"
    #スタッフ条件の確認
    Check_staff_list()

    previous_month_oncall_staff_ids = _load_previous_month_oncall_staff_ids(year=year, month=month)#前月の当直シフト
    previous_month_shift = _load_previous_month_shift(year=year, month=month)#前月のシフト
    previous_year_end_shift = _load_previous_year_end_shift(year=year, month=month)#前年度の年末年始のシフト
    previous_year_december_30_staff = _load_previous_year_december_30_staff(year)
    previous_december_31_staff = _load_previous_december_31_staff(year)
    previous_january_1_staff = _load_previous_january_1_staff(year)

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

    hope_list_pass = f"希望リスト_テスト_{year}_{month}.xlsx"
    hope_list = pd.read_excel(hope_list_pass, skiprows=1)
    hope_list = normalize_name_index(
        hope_list,
        source_label=hope_list_pass,
        name_column="Name",
        allow_index_fallback=True,
    )
    validate_name_alignment(staff_list_df, hope_list)
    
    
    ##休み希望・制約条件を組み込んだshift_requests_専属、shift_requests_兼務　,shift＿requests_当直を作成
    """
    ========================================
    2. 変数定義
    ========================================    
    """
    try:
        optimizer = ShiftOptimizer(year=year,month=month,holidays=holidays,
                                staff_list_pass=staff_list_pass,
                                hope_list=hope_list,
                                previous_month_oncall_staff_ids=previous_month_oncall_staff_ids,
                                previous_month_shift=previous_month_shift,
                                previous_year_end_shift=previous_year_end_shift,
                                previous_year_december_30_staff=previous_year_december_30_staff,
                                previous_december_31_staff=previous_december_31_staff,
                                previous_january_1_staff=previous_january_1_staff)
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
        solver.parameters.max_time_in_seconds = 300 # タイムアウトを5分に設定
        solver.parameters.relative_gap_limit = 0.03 # 最適性ギャップの制限を3%に設定
        validation_message = optimizer.model.Validate()
        print(f"\n=====モデル検証======\n")
        print(f"Validation Message: {validation_message}")
        
        print("\n===== モデル統計 =====")
        print(optimizer.model.ModelStats())

        status = solver.Solve(optimizer.model)
        
        status_name = solver.StatusName(status)
        print(f"\n== ソルバー結果 ==")
        print(f"Solver Status: {status_name}")
        print(f"status code: {status}")
        print(f"wall_time: {solver.WallTime()}")
        print(f"response_status: {solver.ResponseStats()}")
        
        
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            print("シフトの最適化が成功しました。")
            
            # DataFrameで結果を整理
            shift_result = []
            for staff in optimizer.staff.index:
                for day in range(1, optimizer.days + 1):
                    row = {'Name': staff, '日付': day, '専属業務': '休み', '兼務業務': [], '当直': []}
                    for section in optimizer.primary_sections:
                        if solver.Value(optimizer.shifts[(staff, day, section)]) == 1:
                            row['専属業務'] = section
                            break
                    #専属業務を番号から日本語名へ変換
                    if isinstance(row['専属業務'], int):
                        row['専属業務'] = PRIMARY_SECTIONS[row['専属業務']]
                
                    
                    for c_section in optimizer.concurrent_sections:
                        if solver.Value(optimizer.concurrent_shifts[(staff, day, c_section)]) == 1:
                            row['兼務業務'].append(c_section)
                    #兼務業務を番号から日本語名へ変更
                    if row['兼務業務']:
                        row['兼務業務'] = ', '.join([CONCURRENT_SECTIONS[c] for c in row['兼務業務']])
                    else:
                        row['兼務業務'] = 'なし'
                                            
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
            #デバッグ用
            print(df_result)  
            
            # CSVに保存
            df_result.to_csv(f'result/Shift_{year}_{month:02d}.csv', index=False, encoding='utf-8-sig')
            print(f"\nシフト結果を 'Shift_{year}_{month:02d}.csv' に保存しました。")
            
            #日付を横長に展開したcsvファイルを保存
            df_result_long = _pivot_staff_day_wide(
                df_result,
                value_column='専属業務',
                fill_value='休み',
            )
            df_result_long.to_csv(f'result/Shift_wide_{year}_{month:02d}.csv', index=True, encoding='utf-8-sig')
            
            #業務名を書き出し用にクリーニングしたテーブルを保存
            #休みは「休」明けは「⚪︎」当直日は「◎」それ以外の出勤日は全て空白とする
            #当直担当」または「当直相方」の場合に当直と判定されるようにする
            df_result_cleaned = df_result.copy()
            df_result_cleaned['専属業務'] = df_result_cleaned.apply(
                lambda row: '◎' 
                if '当直' in row['当直'] else row['専属業務'],
                axis=1
                )
            print(f"当直を二重丸として反映したデータフレーム{df_result_cleaned.head()}")  # デバッグ用
            df_result_cleaned['専属業務'] = df_result_cleaned.apply(
                lambda row: '⚪︎' if '明け' in row['専属業務'] else row['専属業務'],
                axis=1
                )
            print(f"明けを反映したデータフレーム{df_result_cleaned.head()}")  # デバッグ用
            df_result_cleaned['専属業務'] = df_result_cleaned.apply(
                lambda row: '休' if row['専属業務']=='休み' else row['専属業務'],
                axis=1
                )
            print(f"休みを反映したデータフレーム{df_result_cleaned.head()}")  # デバッグ用
            
            #スタッフ条件を参照し、「外来」floorのスタッフは、専属業務が「外来」以外の場合は空白にする
            #スタッフ条件を参照し、FLoor情報列を追加する
            df_result_cleaned = df_result_cleaned.merge(
                optimizer.staff[['Floor']],
                how='left',
                left_on='Name',
                right_index=True
            )
            df_result_cleaned = df_result_cleaned.merge(
                optimizer.staff[['Floor2']],
                how='left',
                left_on='Name',
                right_index=True
            )
            df_result_cleaned = df_result_cleaned.merge(
                optimizer.staff[['Floor3']],
                how='left',
                left_on='Name',
                right_index=True
            )
            #FLoor1-3のいずれかに外来を含むかの判定列を追加 floorid = 9
            df_result_cleaned['外来有無']=df_result_cleaned.apply(
                lambda row: 9 in [f for f in [row['Floor'], row['Floor2'], row['Floor3']] if pd.notna(f)],
                axis=1
            )
            print(f"スタッフ条件を参照し、外来有無を反映したデータフレーム{df_result_cleaned.head()}")  # デバッグ用
            #外来有無列にTRUEがある場合、専属業務のうち、◎と⚪︎のみ残して残りは全て空白として出力
            #外来有無列FALSEの場合は、専属業務の内容をそのまま出力する
            print(f"外来有無列にTRUEを含むデータは{df_result_cleaned[df_result_cleaned['外来有無']==True].head()}")  # デバッグ用
            
            df_result_cleaned['専属業務'] =df_result_cleaned.apply(
                lambda row: (
                    row['専属業務'] 
                    if not row['外来有無'] or row['専属業務'] in ['◎','⚪︎'] 
                    else ''
                ),
                axis=1
            )
            print(f"外来有無列にTRUEを含むデータの専属業務を反映したデータフレーム{df_result_cleaned[df_result_cleaned['外来有無']==True].head()}")  # デバッグ用
            
            df_result_cleaned['専属業務'] = df_result_cleaned.apply(
                lambda row: '' if (row['外来有無']==False and row['専属業務'] not in ['◎','⚪︎','休']) else row['専属業務'],
                axis=1
            )
            df_result_cleaned = _pivot_staff_day_wide(
                df_result_cleaned,
                value_column='専属業務',
                fill_value='休',
            )   
            df_result_cleaned.to_csv(f'result/Shift_cleaned_{year}_{month:02d}.csv', index=True, encoding='utf-8-sig')
            
            #当直結果の縦長データ表示、csv保存
            oncall_result = df_result[['Name', '日付', '当直']]
            oncall_result.to_csv(f'result/oncall_shift_long_{year}_{month:02d}.csv', index=False, encoding='utf-8-sig')
            #デバッグ用
            print(oncall_result)  
            #当直結果の横長データ表示、csv保存
            on_call_result = df_result[['Name', '日付', '当直']]
            on_call_result = _pivot_staff_day_wide(
                on_call_result,
                value_column='当直',
                fill_value='なし',
            )
            #一番右の列に当直回数を追加
            on_call_result['当直回数'] = on_call_result.apply(lambda row: sum(1 for val in row if '当直担当' in val or '当直相方' in val), axis=1)
            #デバッグ用
            print(on_call_result)
            on_call_result.to_csv(f'result/oncall_shift_wide_{year}_{month:02d}.csv', index=True, encoding='utf-8-sig')

            _print_fairness_summary(df_result)
            
            #週ごとのシフト結果をまとめたxlsxファイルを作成
            #作成した結果はweeklyフォルダに格納する
            #weeklyフォルダはなければ作成する
            weekly_dir = Path("result/weekly")
            weekly_dir.mkdir(exist_ok=True)
            #週ごとのシフト結果をまとめたxlsxファイルを作成
            weekly_files = mk_weekly_shift_schedule(df_result,year,month,weekly_dir,optimizer.staff)
            
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
    
    """
    ========================================
    4. 制約条件の設定
    ========================================
    """
    
    
    """
    ========================================
    5. 平等性の最適化
    ========================================
    """
    

    """
    ========================================
    6. 結果の出力
    ========================================
    名前をアルファベットから日本語名へ変換
    休みに全て指定休を入れていき、最後に希望の休みの日に有給を入れていく
    病棟グループ別の並び替えから、年代順の並び方へ変更をする
    
    """

if __name__ == "__main__":
    _setup_run_log()
    create_shift_schedule()