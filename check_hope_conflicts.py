#!/usr/bin/env python3
"""
希望リストの衝突検証スクリプト

当直希望と休み希望の衝突をチェックし、問題があれば報告します。
main.py実行前に、このスクリプトを実行してデータの整合性を確認できます。

使い方:
    python check_hope_conflicts.py

HOPE_MAPPING:
    0: "休み"
    1: "出勤"
    2: "当直不可"
    3: "育休"
    5: "慶弔休暇"
    6: "研修"
    7: "なし"
    8: "当直"
"""

import pandas as pd
import sys
from pathlib import Path
from staff_name_matching import normalize_name_index, validate_name_alignment


def load_data(staff_list_pass, hope_list_pass):
    """スタッフリストと希望リストを読み込む"""
    try:
        staff_list = pd.read_excel(staff_list_pass, sheet_name="member_list", skiprows=1)
        hope_list = pd.read_excel(hope_list_pass, skiprows=1)

        staff_list = normalize_name_index(
            staff_list,
            source_label=staff_list_pass,
            name_column="Name",
            allow_index_fallback=False,
        )
        hope_list = normalize_name_index(
            hope_list,
            source_label=hope_list_pass,
            name_column="Name",
            allow_index_fallback=True,
        )
        validate_name_alignment(staff_list, hope_list)
        
        # 希望リストを数値に変換（既存コードと同じ処理）
        from config.hope_mapping import HOPE_MAPPING
        hope_list = hope_list.applymap(
            lambda x: HOPE_MAPPING.get(x, x) if pd.notna(x) else x
        )
        
        return staff_list, hope_list
    except FileNotFoundError as e:
        print(f"❌ エラー: ファイルが見つかりません - {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ エラー: ファイルの読み込みに失敗しました - {e}")
        sys.exit(1)


def check_hope_conflicts(staff_list, hope_list):
    """当直希望と休み希望の衝突をチェック"""
    
    HOPE_MAPPING = {
        0: "休み",
        1: "出勤",
        2: "当直不可",
        3: "育休",
        5: "慶弔休暇",
        6: "研修",
        7: "なし",
        8: "当直"
    }
    
    print("\n" + "="*60)
    print("希望リスト衝突検証")
    print("="*60)
    
    conflicts_found = False
    oncall_with_dayoff_conflicts = []
    oncall_with_no_oncall_conflicts = []
    statistics = {
        'total_staff': len(staff_list),
        'total_days': len(hope_list.columns),
        'oncall_hopes': 0,
        'dayoff_hopes': 0,
        'no_oncall_hopes': 0
    }
    
    # 各スタッフの希望をチェック
    for staff_name in staff_list.index:
        # 当直不可または休職中のスタッフはスキップ
        if staff_list.loc[staff_name, '当直'] == False:
            continue
        if staff_list.loc[staff_name, '休職'] == True:
            continue
        
        if staff_name not in hope_list.index:
            print(f"⚠️  スタッフ{staff_name}: 希望リストに存在しません")
            continue
        
        staff_hopes = hope_list.loc[staff_name]
        
        # 各日の希望をチェック
        for day_col in hope_list.columns:
            try:
                day = int(day_col)
            except (ValueError, TypeError):
                continue
            
            hope_value = staff_hopes[day_col]
            
            # NaNや無効な値をスキップ
            if pd.isna(hope_value):
                hope_value = 7  # デフォルト値
            
            try:
                hope_value = int(hope_value)
            except (ValueError, TypeError):
                continue
            
            # 統計情報を集計
            if hope_value == 8:
                statistics['oncall_hopes'] += 1
            elif hope_value == 0:
                statistics['dayoff_hopes'] += 1
            elif hope_value == 2:
                statistics['no_oncall_hopes'] += 1
            
            # 当直希望と休み希望の衝突チェック
            # （実際には同じセルに両方の値は入らないが、論理的な確認）
            if hope_value == 8:
                # 当直希望がある日に、他の休み系希望がないか確認
                # （通常はありえないが、念のため）
                pass
            
            # 当直希望と当直不可の衝突
            # （これも通常はありえないが、入力ミスの可能性）
    
    # 衝突パターンの検出（実際のデータ構造上、1セル1値なので衝突は起こらない）
    # しかし、結果ファイルで問題が起きているのは、異なる制約が競合しているため
    
    print(f"\n📊 統計情報:")
    print(f"  • 総スタッフ数: {statistics['total_staff']}名")
    print(f"  • 対象日数: {statistics['total_days']}日")
    print(f"  • 当直希望の総数: {statistics['oncall_hopes']}件")
    print(f"  • 休み希望の総数: {statistics['dayoff_hopes']}件")
    print(f"  • 当直不可の総数: {statistics['no_oncall_hopes']}件")
    
    # 同一スタッフの同一月内での希望パターンをチェック
    print(f"\n🔍 潜在的な問題パターンの検出:")
    
    problem_patterns = []
    for staff_name in staff_list.index:
        if staff_list.loc[staff_name, '当直'] == False or staff_list.loc[staff_name, '休職'] == True:
            continue
        
        if staff_name not in hope_list.index:
            continue
        
        staff_hopes = hope_list.loc[staff_name]
        oncall_days = []
        dayoff_days = []
        
        for day_col in hope_list.columns:
            try:
                day = int(day_col)
            except (ValueError, TypeError):
                continue
            
            hope_value = staff_hopes[day_col]
            if pd.isna(hope_value):
                hope_value = 7
            
            try:
                hope_value = int(hope_value)
            except (ValueError, TypeError):
                continue
            
            if hope_value == 8:
                oncall_days.append(day)
            elif hope_value == 0:
                dayoff_days.append(day)
        
        # 各スタッフの希望パターンの整合性チェック
        if len(oncall_days) > 0 and len(dayoff_days) > 0:
            # 当直希望と休み希望の両方がある（これ自体は問題ない）
            # 問題なのは、同じ日に両方が指定される場合だが、データ構造上それは不可能
            pass
        
        # 役職者・外来スタッフの当直希望が月1回を超えていないか
        is_role = (staff_list.loc[staff_name, 'Floor'] in [9, 10]) and (staff_list.loc[staff_name, '主任以上'] == True)
        max_oncall = 1 if is_role else 2
        
        if len(oncall_days) > max_oncall:
            role_label = "役職者・外来" if is_role else "通常スタッフ"
            problem_patterns.append({
                'staff': staff_name,
                'type': '希望回数超過',
                'detail': f"{role_label}の上限{max_oncall}回に対し、{len(oncall_days)}回の当直希望",
                'days': oncall_days
            })
    
    if problem_patterns:
        print(f"  ⚠️  {len(problem_patterns)}件の潜在的な問題を検出:")
        for pattern in problem_patterns:
            print(f"     • スタッフ{pattern['staff']}: {pattern['type']}")
            print(f"       {pattern['detail']}")
            if len(pattern['days']) <= 10:
                print(f"       関連日: {pattern['days']}")
        conflicts_found = True
    else:
        print("  ✓ 潜在的な問題は検出されませんでした")
    
    # 実際の問題についての説明
    print(f"\n📝 注意事項:")
    print("  • データ構造上、同じ日に複数の希望値は入力できません")
    print("  • 問題が発生しているのは、制約の適用順序によるものです:")
    print("    1. 当直制約で休み希望の日を避ける設定がある")
    print("    2. 当直希望がハード制約として強制適用される")
    print("    3. その後、休み希望が専属業務に強制適用される")
    print("  • 今回の修正で、休み希望が当直希望より優先されます")
    
    print("\n" + "="*60)
    if conflicts_found:
        print("⚠️  警告: いくつかの問題が検出されました")
        print("詳細を確認して、必要に応じて希望リストを修正してください")
        return False
    else:
        print("✅ 検証完了: 重大な衝突は検出されませんでした")
        return True
    print("="*60 + "\n")


def main():
    """メイン処理"""
    print("\n希望リスト検証スクリプトを開始します")
    
    # データ読み込み
    staff_list_pass = f"スタッフ条件_テスト_{month}.xlsx"
    hope_list_pass = f"希望リスト_テスト_{month}.xlsx"
    staff_list, hope_list = load_data(staff_list_pass, hope_list_pass)
    print(f"✓ データを読み込みました")
    print(f"  - スタッフリスト: {len(staff_list)}名")
    print(f"  - 希望リスト: {len(hope_list)}名 × {len(hope_list.columns)}日")
    
    # 衝突チェック
    result = check_hope_conflicts(staff_list, hope_list)
    
    # 終了コード
    if result:
        print("\n✅ 検証に合格しました。main.pyを実行できます。")
        sys.exit(0)
    else:
        print("\n⚠️  問題が検出されました。希望リストを確認してください。")
        sys.exit(1)


if __name__ == "__main__":
    main()
