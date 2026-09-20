import pandas as pd
from pathlib import Path
def _get_previous_year_month(year: int, month: int):
    if month == 1:
        return year - 1, 12
    return year, month - 1

"""テストしたいcsv読み込みの関数"""
def _load_previous_month_oncall_staff_ids(year: int, month: int):
    year = int(input("年を入力してください: "))#本番環境では不要
    month = int(input("月を入力してください: "))#本番環境では不要
    
    prev_year, prev_month = _get_previous_year_month(year, month)
    oncall_csv = Path(f"../../result/oncall_shift_wide_{prev_year}_{prev_month:02d}.csv")#本番環境では対象のパスに直す
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
        print(f"前月当直ファイルに日付列が見つかりません: {oncall_csv}")
        return []

    staff_names_dict = {}#日付：staff_name
    
    # 前月　最終日の７日前〜最終日
    for offset in range(7,-1,-1):
        target_day = max(int(str(c).strip()) for c in day_columns) - offset
        target_day = str(target_day)
        print(f"ターゲット日: {target_day}")#デバッグ用
        if target_day in day_columns:
            last_seven_days_column = target_day
            print(f"前月末7日間の対象列: {last_seven_days_column}")#デバッグ用
            if 'Name' not in oncall_df.columns:
                print(f"前月当直ファイルにスタッフ列がないため、月初連携をスキップします: {oncall_csv}")
                return []

            for _, row in oncall_df[['Name', last_seven_days_column]].iterrows():
                cell = row[last_seven_days_column]
                print(f"処理中のセル: {cell}")#デバッグ用
                if pd.isna(cell):
                    continue
                cell_text = str(cell)
                print(f"セルのテキスト: {cell_text}")#デバッグ用
                
                if  ('当直担当' in cell_text) or('当直相方' in cell_text):
                    staff_names_dict.setdefault(last_seven_days_column, []).append(row['Name'])
                    print(f"当直者を追加: {row['Name']}")#デバッグ用
            print(f"前月末7日間の当直者を読み込みました: {prev_year}/{prev_month:02d} 対象={staff_names_dict}")
    if not staff_names_dict:
        print(f"前月末7日間の当直者が見つかりませんでした: {oncall_csv}")
    return staff_names_dict
    


def __main__():
    staff_ids = _load_previous_month_oncall_staff_ids(0, 0)
    print(f"前月の当直スタッフID: {staff_ids}")

if __name__ == "__main__":
    __main__()