import jpholiday
import os
from pathlib import Path
import tkinter.filedialog
import pandas as pd
from get_previous_data import GetPreviousData
from optimizer.method.staff_name_matching import normalize_name_index, normalize_staff_name, validate_name_alignment
from optimizer.mode2.shift_optimizer import ShiftOptimizer
from ortools.sat.python import cp_model
from create_calender import CalendarCreator
from optimizer.method.baseshiftoptimizer import BaseShiftOptimizer
from config.sections import PRIMARY_SECTIONS
from config.concurrent_sections import CONCURRENT_SECTIONS

iDir = os.path.abspath(os.path.join(os.path.dirname(__file__),'..','..'))

class Mode2Optimizer:
    def mode2_adjust_shift():
        """
        出勤有無調整後の週間配置を決めるモードの処理を行う関数
        """
        # ここに mode2 の処理を実装する
        print("出勤有無調整後の週間配置を決めるモードが選択されました。\n")
        print("このモードでは、既に決まっている出勤有無を考慮して、週間のシフト配置を調整します。\n")
        print("最初にすでに決まっている出勤日や当直情報の収集を行います。\n")
        """
        ==============================================================
        1. 入力受付
        ==============================================================
        """
        year = int(input("対象年を入力してください（例：2026):"))
        month = int(input("対象月を入力してください(例:10):"))
        
        if month < 1 or month >12:
            raise ValueError("エラー:月は1から12の範囲で入力してください")
        
        #日曜祝日の取得
        holidays = jpholiday.month_holidays(year = year,month = month)
        
        
        #スタッフ条件のシートを読み込み
        staff_list_pass = tkinter.filedialog.askopenfilename(
            title="スタッフ条件のファイルを選択してください",
            initialdir=iDir
        )
        if not staff_list_pass:
            print("エラー: スタッフ条件のファイルが選択されませんでした")
            return
            
        #前月シフト表の読み込みはいらない
        #previous_month_shift = GetPreviousData._load_previous_month_shift()#前月のシフト
        #previous_month_oncall_counts = (
        #    dict(previous_month_shift.attrs.get('oncall_counts', {}))
        #    if previous_month_shift is not None else {}
        #)
        #previous_month_shift = GetPreviousData._cleaning_previous_month_shift(previous_month_shift)
        #previous_month_oncall_staff_ids = GetPreviousData._extract_previous_month_oncall_staff_ids(
        #    previous_month_shift
        #)
        #if not previous_month_oncall_staff_ids:
        #    previous_month_oncall_staff_ids = GetPreviousData._load_previous_month_oncall_staff_ids(
        #        year=year, month=month
        #    )
        #previous_month_shifts = GetPreviousData._read_previous_month_shifts_files(
        #    GetPreviousData._load_previous_month_shifts_files()
        #)
        #前月の当直回数集計
        #previous_oncall_counts = GetPreviousData._sum_previous_month_shifts(previous_month_shifts)# 前月の当直回数を集計
        #previous_months_with_two_oncalls = (
        #    GetPreviousData._count_previous_months_with_two_oncalls(previous_month_shifts)
        #)# 過去に当直が月ちょうど2回だった回数を集計
        #if month==12 or month==1:
        #    previous_year_end_shift = GetPreviousData._load_previous_year_end_shift(year=year, month=month)
        #else:
        #    previous_year_end_shift = None
            
        #previous_year_december_30_staff = set()
        #previous_december_31_staff = set()
        #if month == 12:
        #    previous_year_december_30_staff = GetPreviousData._load_previous_year_december_30_staff(year)
        #    previous_december_31_staff = GetPreviousData._load_previous_december_31_staff(year)
        #previous_january_1_staff = set()
        #previous_january_2_staff = set()
        #previous_january_3_staff = set()
        #if month == 1:
        #    previous_january_staff_df = None
        #    if Path(f"result/Shift_cleaned_{year - 1}_01.csv").exists():
        #        previous_january_staff_df = GetPreviousData._load_previous_january_staff_conditions(year)
        #    previous_january_1_staff = GetPreviousData._load_previous_january_staff(
        #        year, 1, previous_january_staff_df
        #    )
        #    previous_january_2_staff = GetPreviousData._load_previous_january_staff(
        #        year, 2, previous_january_staff_df
        #    )
        #    previous_january_3_staff = GetPreviousData._load_previous_january_staff(
        #        year, 3, previous_january_staff_df
        #    )

        #Name列をキーにしてスタッフ条件と希望リストを突合する
        staff_list_df = pd.read_excel(staff_list_pass,sheet_name="member_list",skiprows=1)
        staff_list_df = normalize_name_index(
            staff_list_df,
            source_label=staff_list_pass,
            name_column = "Name",
            allow_index_fallback=False,
        )
        
        hope_list_pass = tkinter.filedialog.askopenfilename(
            title="希望リストのファイルを選択してください",
            initialdir=iDir,
            filetypes=[("Excel files", "*.xlsx *.xls"),("All files","*.*")]
        )
        if not hope_list_pass:
            print("エラー: 希望リストのファイルが選択されませんでした")
            return
            
        hope_list = pd.read_excel(hope_list_pass,skiprows=[1])
        #1列目は何もデータが入っていないので削除、1行目は削除しない
        hope_list = hope_list.iloc[:, 1:]
        #○月→"Name"に変更
        hope_list.rename(columns={hope_list.columns[0]:"Name"},inplace = True)
        #31日分までの列に絞る、該当月が28日までなら28日までの列、30日までなら30日までの列に絞る
        hope_list = hope_list.iloc[:,:min(32,hope_list.shape[1])]
        
        #スペーサー行など"Name"列が空の行は正規化前に削除する
        hope_list = hope_list[hope_list["Name"].notna()]
        
        hope_list = normalize_name_index(
            hope_list,
            source_label=hope_list_pass,
            name_column = "Name",
            allow_index_fallback=False,
        )
        #NaNは"なし"に置換する
        hope_list = hope_list.replace(pd.NA, "なし")
        validate_name_alignment(staff_list_df,hope_list)
        
        #mode1で作成したスタッフの出勤・非出勤のリスト
        mode1_attendance_list = tkinter.filedialog.askopenfilename(
            title="mode1で作成したスタッフの出勤・非出勤リストを選択してください",
            initialdir=iDir,
            filetypes=[("Excel files", "*.xlsx *.xls"),("All files","*.*")]
        )
        if not mode1_attendance_list:
            print("エラー: mode1で作成したスタッフの出勤・非出勤リストが選択されませんでした")
            return
        attendance_path = mode1_attendance_list
        mode1_attendance_list = pd.read_excel(attendance_path, skiprows=[1])
        if "Name" not in mode1_attendance_list.columns:
            raise ValueError(f"{attendance_path} に Name 列がありません")
        #31日分までの列に絞る、該当月が28日までなら28日までの列、30日までなら30日までの列に絞る
        mode1_attendance_list = mode1_attendance_list.iloc[:,:min(32,mode1_attendance_list.shape[1])]
        #スペーサー行など"Name"列が空の行は正規化前に削除する
        mode1_attendance_list = mode1_attendance_list[mode1_attendance_list["Name"].notna()]

        mode1_attendance_list = normalize_name_index(
            mode1_attendance_list,
            source_label=attendance_path,
            name_column = "Name",
            allow_index_fallback=False,
        )
        #NaNは　”なし"に置換する
        mode1_attendance_list = mode1_attendance_list.fillna("")
        validate_name_alignment(staff_list_df, mode1_attendance_list)
        
        
        """
        ==============================================================
        2. 変数定義
        ==============================================================
        """
        try:
            optimizer = ShiftOptimizer(
                year=year,
                month=month,
                staff_list_df=staff_list_df,
                hope_list=hope_list,
                mode1_attendance_list=mode1_attendance_list,
                holidays=holidays,
                
            )
            print("シフト最適化モデルの初期化が完了しました")
            optimizer.create_variables()
            optimizer._init_constraints()
            optimizer.apply_all_constraints()
            
            status,solver,failure_reasons = optimizer.solve_with_fallback()
            if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                print(
                    "エラー: 解が見つかりませんでした"
                    f"({solver.StatusName(status)}:{failure_reasons})"
                )
                return
            
        except Exception as e:
            print(f"エラー: シフト最適化モデルの初期化に失敗しました: {e}")
            raise
        
        
        shift_result = []
        day_columns = {
            str(column).strip():column
            for column in optimizer.mode1_attendance_list.columns
        }
        
        for staff in optimizer.staff.index:
            for day in range(1, optimizer.days +1):
                primary_assignments = [
                    section 
                    for section in optimizer.primary_sections
                    if (staff, day, section) in optimizer.shifts
                    and solver.Value(optimizer.shifts[(staff, day,section)])
                ]
                if len(primary_assignments) >1:
                    raise ValueError(
                        f"専属業務が複数割り当てられています:{staff},{day}"
                    )
                    
                day_column = day_columns.get(str(day))
                if day_column is None:
                    raise KeyError(f"出勤表に{day}列がありません")
                
                attendance_value = optimizer.mode1_attendance_list.loc[
                    staff,
                    day_column
                ]
                concurrent_assignments = [
                    CONCURRENT_SECTIONS[section]
                    for section in optimizer.concurrent_sections
                    if solver.Value(
                        optimizer.concurrent_shifts[(staff, day, section)]
                    )
                ]
                
                shift_result.append({
                    "Name":staff,
                    "日付":day,
                    "専属業務":(
                        PRIMARY_SECTIONS[primary_assignments[0]]
                        if primary_assignments
                        else "休み"
                    ),
                    "兼務業務": ",".join(concurrent_assignments),
                    "当直":(
                        "当直担当"
                        if  optimizer._normalize_attendance_mark(attendance_value) == "◎" #
                        else "なし"
                    ),
                })
    
        weekly_dir = Path("result/weekly")
        weekly_dir.mkdir(parents=True, exist_ok=True)#なければディレクトリを作成する
        CalendarCreator.mk_weekly_shift_schedule(
            pd.DataFrame(shift_result),
            year,
            month,
            weekly_dir,
            staff_info = optimizer.staff
    )
    