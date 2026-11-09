import jpholiday
import tkinter.filedialog
import os
from pathlib import Path
import pandas as pd
from get_previous_data import GetPreviousData
from required_staff import RequiredStaff
from staff_name_matching import normalize_name_index, normalize_staff_name, validate_name_alignment
from optimizer.mode1.shift_optimizer import ShiftOptimizer
from ortools.sat.python import cp_model
from create_calender import CalendarCreator

iDir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
class Mode1Optimizer:
        
    def mode1_initial_shift():
        print("初回の当直・出勤有無を決めるモードが選択されました。")
        print("シフト作成を開始します。対象年と対象月はこれから入力してください。入力は半角でお願いします。\n"
            "入力が終わったらEnterキーで次に進みます。\n"
            "\n"
            "Enterキーで進んだ後、一つ前に戻りたい場合・入力をし直したい場合・作成をキャンセルしたい場合は一旦終了が必要です。\n"
            "Control+Cでキャンセルできます。"
            "\n")
        year = int(input("対象年を入力してください（例：2026）: "))
        month = int(input("対象月を入力してください（例：1～12）: "))
        offrequest_day = int(input("今月の指定休日数を入力してください"))
        if month < 1 or month > 12:
            print("エラー: 月は1から12の範囲で指定してください。")
            return 1
        #日曜祝日の取得
        holidays = jpholiday.month_holidays(year=year,month=month)
        #staff_list_pass = input("スタッフリストのファイルパスを入力してください（例：staff_list.xlsx）: ")
        #月毎にスタッフ条件が変わるものは関数で変更(新人の条件など)
        

        #スタッフ条件のシートを読み込み
        staff_list_pass = tkinter.filedialog.askopenfilename(
            title="スタッフ条件のファイルを選択してください",
            initialdir=iDir,
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")]
            
        )
        if not staff_list_pass:
            print("エラー: スタッフ条件のファイルが選択されませんでした。")
            return 1

        previous_month_shift = GetPreviousData._load_previous_month_shift()#前月のシフト
        previous_month_oncall_counts = (
            dict(previous_month_shift.attrs.get('oncall_counts', {}))
            if previous_month_shift is not None else {}
        )
        previous_month_shift = GetPreviousData._cleaning_previous_month_shift(previous_month_shift)
        previous_month_oncall_staff_ids = GetPreviousData._extract_previous_month_oncall_staff_ids(
            previous_month_shift
        )
        if not previous_month_oncall_staff_ids:
            previous_month_oncall_staff_ids = GetPreviousData._load_previous_month_oncall_staff_ids(
                year=year, month=month
            )
        previous_month_shifts = GetPreviousData._read_previous_month_shifts_files(
            GetPreviousData._load_previous_month_shifts_files()
        )
        #前月の当直回数集計
        previous_oncall_counts = GetPreviousData._sum_previous_month_shifts(previous_month_shifts)# 前月の当直回数を集計
        previous_months_with_two_oncalls = (
            GetPreviousData._count_previous_months_with_two_oncalls(previous_month_shifts)
        )# 過去に当直が月ちょうど2回だった回数を集計
        if month==12 or month==1:
            previous_year_end_shift = GetPreviousData._load_previous_year_end_shift(year=year, month=month)
        else:
            previous_year_end_shift = None
            
        previous_year_december_30_staff = set()
        previous_december_31_staff = set()
        if month == 12:
            previous_year_december_30_staff = GetPreviousData._load_previous_year_december_30_staff(year)
            previous_december_31_staff = GetPreviousData._load_previous_december_31_staff(year)
        previous_january_1_staff = set()
        previous_january_2_staff = set()
        previous_january_3_staff = set()
        if month == 1:
            previous_january_staff_df = None
            if Path(f"result/Shift_cleaned_{year - 1}_01.csv").exists():
                previous_january_staff_df = GetPreviousData._load_previous_january_staff_conditions(year)
            previous_january_1_staff = GetPreviousData._load_previous_january_staff(
                year, 1, previous_january_staff_df
            )
            previous_january_2_staff = GetPreviousData._load_previous_january_staff(
                year, 2, previous_january_staff_df
            )
            previous_january_3_staff = GetPreviousData._load_previous_january_staff(
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

        hope_list_pass = tkinter.filedialog.askopenfilename(
            title="希望リストのファイルを選択してください",
            initialdir=iDir,
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")]
        )
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
                                    offrequest_day = offrequest_day,
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
            solver.parameters.max_time_in_seconds = 300 # タイムアウトを5分に設定
            solver.parameters.relative_gap_limit = 0.03 # 最適性ギャップの制限を3%に設定
            validation_message = optimizer.model.Validate()
            print(f"\n=====モデル検証======\n")
            print(f"Validation Message: {validation_message}")
            
            print("\n===== モデル統計 =====")
            print(optimizer.model.ModelStats())

            status = solver.Solve(optimizer.model)
            if status == cp_model.INFEASIBLE:
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
                    print(f"ソルバー解決後のスタッフ: {staff_name}")
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
                        #TODO:第二段階で必要かも#旧セクション毎にシフト変数を作成している場合、セクション毎の変数=1ならセクション名に変更する処理
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
