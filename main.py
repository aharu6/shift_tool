from optimizer.shift_optimizer import ShiftOptimizer
from ortools.sat.python import cp_model
from required_staff import RequiredStaff
from check_staff_list import Check_staff_list
import pandas as pd
from config.sections import PRIMARY_SECTIONS
from config.concurrent_sections import CONCURRENT_SECTIONS

from mk_staff_column import MkStafflist
from requests.mk_requests import MkRequests
def create_shift_schedule():
    """
    ========================================
    1. データ読み込み
    ========================================
    """    #TODO:本番環境ではinoutにするが、とりあえず固定値で動作確認
    #year = int(input("シフトを作成したい年を入力してください（例：2024）: "))
    year = 2026
    #month = int(input("シフトを作成したい月を入力してください（例：6）: "))
    month = 1
    
    
    #staff_list_pass = input("スタッフリストのファイルパスを入力してください（例：staff_list.xlsx）: ")
    #月毎にスタッフ条件が変わるものは関数で変更(新人の条件など)
    
    #スタッフ条件のシートを読み込み
    staff_list_pass = "条件.xlsx"
    #スタッフ条件の確認
    Check_staff_list()
    
    
    #フロア毎の必要人数リストを作成
    required_num_list = RequiredStaff(year=year, month=month, date=1, section=None)
    #休み希望・出勤希望シートの読み込み
    hope_list = pd.read_excel("休み希望_テスト.xlsx",index_col=0)
    
    #TODO:役職、会議等で決まる出勤希望リストを別で作成しておいてモデルに適用する形で読み込むか
    ##休み希望・制約条件を組み込んだshift_requests_専属、shift_requests_兼務　,shift＿requests_当直を作成
    shift_requests_primary = []
    shift_requests_concurrent = []
    shift_results_oncall = []
    
    
    #スタッフ人数分の空リストを作成 
    mkstaffColumn = MkStafflist(shift_requests_primary,shift_requests_concurrent,shift_results_oncall,staff_list_pass,year,month)   
    shift_requests_primary =mkstaffColumn.make_stafflist_primary()
    shift_requests_concurrent = mkstaffColumn.make_stafflist_concurrent()
    
    MkRequests(shift_requests_primary,shift_requests_concurrent,shift_results_oncall,hope_list,staff_list_pass)()
    #制約条件を組み込んだshift_requestsの作成
    
    """
    ========================================
    2. 変数定義
    ========================================    
    """
    try:
        optimizer = ShiftOptimizer(year=year,month=month,staff_list_pass=staff_list_pass,
                                hope_list=hope_list)
        print("シフト最適化モデルの初期化が完了しました。")
        optimizer._get_days_in_month()
        optimizer.create_variables()
    
        """
        ========================================
        3. 最適化モデル構築
        ========================================
        """
        #全ての制約を一括適用
        optimizer._init_constraints()
        optimizer.apply_all_constraints()
        optimizer.apply_day_off_requests()
        optimizer.add_section_requirements()
        optimizer.add_current_assignment()
        
        solver = cp_model.CpSolver()
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
                            if solver.Value(optimizer.night_shifts.get((staff,other_staff,day),0)) == 1:
                                row['当直'].append(f'当直担当（相方: {other_staff}）')
                            if solver.Value(optimizer.night_shifts.get((other_staff,staff,day),0)) == 1:
                                row['当直'].append(f'当直相方（担当: {other_staff}）')
                    
                    row['当直'] = ', '.join(row['当直']) if row['当直'] else 'なし'
                    shift_result.append(row)
            
            df_result = pd.DataFrame(shift_result)
            print("\n===== シフト結果 =====")
            print(df_result.head(20))  # 最初の20行を表示
            
            # CSVに保存
            df_result.to_csv(f'shift_{year}_{month:02d}.csv', index=False, encoding='utf-8-sig')
            print(f"\nシフト結果を 'shift_{year}_{month:02d}.csv' に保存しました。")
            
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
    create_shift_schedule()