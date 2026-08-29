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


def _load_previous_month_oncall_staff_ids(year: int, month: int):
    prev_year, prev_month = _get_previous_year_month(year, month)
    oncall_csv = Path(f"result/oncall_shift_{prev_year}_{prev_month:02d}.csv")
    if not oncall_csv.exists():
        print(f"前月当直ファイルが見つからないため、月初の当直明け連携をスキップします: {oncall_csv}")
        return []

    try:
        oncall_df = pd.read_csv(oncall_csv, encoding='utf-8-sig')
    except Exception as exc:
        print(f"前月当直ファイルの読み込みに失敗したため、月初連携をスキップします: {exc}")
        return []

    if oncall_df.empty:
        return []

    # 右端の集計列を除いた最終日列を使用して、前月末の当直担当者を抽出する
    day_columns = [c for c in oncall_df.columns if str(c).strip().isdigit()]
    if not day_columns:
        print(f"前月当直ファイルに日付列が見つかりませんでした: {oncall_csv}")
        return []

    last_day_column = max(day_columns, key=lambda x: int(str(x).strip()))
    if 'スタッフ' not in oncall_df.columns:
        print(f"前月当直ファイルにスタッフ列がないため、月初連携をスキップします: {oncall_csv}")
        return []

    staff_names = []
    for _, row in oncall_df[['スタッフ', last_day_column]].iterrows():
        cell = row[last_day_column]
        if pd.isna(cell):
            continue
        cell_text = str(cell)
        if ('当直担当' in cell_text) or ('当直相方' in cell_text):
            staff_names.append(row['スタッフ'])

    unique_staff_names = sorted(set(normalize_name_list(staff_names)))
    print(
        f"前月末当直者を読み込みました: {prev_year}/{prev_month:02d} 最終日列={last_day_column} "
        f"対象={unique_staff_names}"
    )
    return unique_staff_names


def _print_fairness_summary(df_result: pd.DataFrame):
    """専属業務・当直の偏りサマリを表示する。"""
    print("\n===== 公平性サマリ =====")

    primary_df = df_result[df_result['専属業務'].isin(['休み', '明け']) == False]
    if primary_df.empty:
        print("専属業務: 対象データなし")
    else:
        primary_counts = primary_df.groupby(['専属業務', 'スタッフ']).size().unstack(fill_value=0)
        for section_name, row in primary_counts.iterrows():
            max_count = int(row.max())
            min_count = int(row.min())
            diff = max_count - min_count
            print(f"専属業務[{section_name}] max={max_count} min={min_count} diff={diff}")

    oncall_series = df_result.groupby('スタッフ')['当直'].apply(
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
        index='スタッフ',
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
    week_df.loc[week_df['兼務業務'].str.contains('監査_AM',na=False),'専属業務']='監査_AM'
    week_df.loc[week_df['兼務業務'].str.contains('監査_PM',na=False),'専属業務']='監査_PM'
    print(f"監査があるスタッフを専属業務名に反映した週ごとのシフト結果を表示します{week_df}")
    
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
            values='スタッフ',
            aggfunc=lambda x: '\n'.join(x)  # 同じ専属業務に複数のスタッフがいる場合は改行して表示,最後に編集したい
        )
        #行の順番を固定
        #指定した行だけ出力されるので、「休み」や「明け」は出力されない
        week_df = week_df.reindex(
        ['調剤室','監査_AM','監査_PM','化療','1-2階','3階','4階','5階','入退院センター','RI','課長業務','医療安全・感染管理','AST','DI','課長業務','課長','部長','実習','外来',
        '緩和回診(専任)','ポリファーマシーチーム','せん妄ラウンド','心不全回診','NST','実習','マスター管理','医薬品安全使用WG',],
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

    previous_month_oncall_staff_ids = _load_previous_month_oncall_staff_ids(year=year, month=month)

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
                                previous_month_oncall_staff_ids=previous_month_oncall_staff_ids)
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
        status = solver.Solve(optimizer.model)
        
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            print("シフトの最適化が成功しました。")
            
            # DataFrameで結果を整理
            shift_result = []
            for staff in optimizer.staff.index:
                for day in range(1, optimizer.days + 1):
                    row = {'スタッフ': staff, '日付': day, '専属業務': '休み', '兼務業務': [], '当直': []}
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
            df_result_long.to_csv(f'result/Shift_long_{year}_{month:02d}.csv', index=True, encoding='utf-8-sig')
            #デバッグ用
            print(df_result_long)  
            
            #当直結果の縦長データ表示、csv保存
            oncall_result = df_result[['スタッフ', '日付', '当直']]
            oncall_result.to_csv(f'result/oncall_shift_long_{year}_{month:02d}.csv', index=False, encoding='utf-8-sig')
            #デバッグ用
            print(oncall_result)  
            #当直結果の横長データ表示、csv保存
            on_call_result = df_result[['スタッフ', '日付', '当直']]
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