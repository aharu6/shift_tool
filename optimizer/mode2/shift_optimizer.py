#mode2専用
from optimizer.method.baseshiftoptimizer import BaseShiftOptimizer
from ortools.sat.python import cp_model
import pandas as pd
import datetime
from optimizer.mode2.constraint_dignostics import TrackedCpModel
from optimizer.mode2.primary_shift.weekly_placement_optimizer import WeeklyPlacementOptimizer
from optimizer.mode2.concurrent_shift import MeetingConstraints
from optimizer.mode2.concurrent_shift.concurrent_constraints import ConcurrentConstraints
from optimizer.method.staff_name_matching import normalize_name_index
from optimizer.method.staff_name_matching import validate_name_alignment
from config.hope_mapping import HOPE_MAPPING
from config.sections import PRIMARY_SECTIONS
from config.concurrent_sections import CONCURRENT_SECTIONS

class ShiftOptimizer(BaseShiftOptimizer):
    
    def __init__(
        self,year,month,holidays,staff_list_df,hope_list,
        mode1_attendance_list,
    ):
        """
        mode2シフト最適化
        
        
        """
        self.model = TrackedCpModel()
        self.year = year 
        self.month = month
        self.days = BaseShiftOptimizer._get_days_in_month(self)
        self.holidays = holidays
        self.staff = staff_list_df.copy()
        self.hope_list =hope_list.copy()
        self.mode1_attendance_list = mode1_attendance_list
        
        for column in ('当直','休職','主任以上','ポリファーマシーチーム'):
            if column in self.staff.columns:
                self.staff[column] =ShiftOptimizer._normalize_boolean_column(self.staff[column])
        #Floorカラムを数値IDに変換
        if 'Floor' in self.staff.columns:
            self.staff['Floor'] = ShiftOptimizer._normalize_floor_column(self.staff['Floor'])
        #Floor2カラムを数値IDに変換
        if 'Floor2' in self.staff.columns:
            self.staff['Floor2'] = ShiftOptimizer._normalize_floor_column(self.staff['Floor2'])
        #Floor3カラムを数値IDに変換
        if 'Floor3' in self.staff.columns:
            self.staff['Floor3'] = ShiftOptimizer._normalize_floor_column(self.staff['Floor3'])
        
        
        #希望リストを数値IDに変換
        for column in self.hope_list.columns:
            self.hope_list[column] = self.hope_list[column].apply(
                lambda x:HOPE_MAPPING.get(x,x) if pd.notna(x) else x
            )
        self.primary_sections = PRIMARY_SECTIONS.keys()
        self.concurrent_sections = CONCURRENT_SECTIONS.keys()
        self.shifts = {}
        self.night_shifts = {}
        self.concurrent_shifts = {}
        self.objective_terms = []
        #ポリファ開催日は出勤しているスタッフが揃っている日から選択する
        self.porifa_friday,self.porifa_tuesday = self._select_porifa_days()
        
    
    def create_variables(self):
        """
        mode2用のシフト変数を作成する
        staffname_day_sectionの組み合わせでシフト変数を作成する
        """
        #シフト変数(専属業務)
        for staff in self.staff.index:
            for day in range(1,self.days+1):
                for section in self.primary_sections:
                    if section in {0,17}:
                        continue
                    var_name = f'section_shift_{staff}_{day}_{section}'
                    self.shifts[(staff,day,section)] = self.model.NewBoolVar(var_name)
                    
        #兼務業務の変数を追加
        for staff in self.staff.index:
            for day in range(1,self.days+1):
                for section in self.concurrent_sections:
                    var_name = f'concurrent_{staff}_{day}_{section}'
                    self.concurrent_shifts[(staff,day,section)] = self.model.NewBoolVar(var_name)
                    
                    
    def get_attendance_status(self,staff,day):
        """
        mode1で確定した出勤表から、指定日の出勤状態を返す
        ◎と空欄は出勤、その他は非出勤とみなす
        """
        if staff not in self.mode1_attendance_list.index:
            raise KeyError(f"スタッフ {staff} の出勤情報が存在しません")
        
        day_column = next(
            
            (
                column
                for column in self.mode1_attendance_list.columns
                if str(column).strip() == str(day)
            ),
            None,
        )
        if day_column is None:
            raise KeyError(f"スタッフ {staff} の出勤情報に日 {day} の列が存在しません")
        
        value = self.mode1_attendance_list.loc[staff,day_column]
        return pd.isna(value) or self._normalize_attendance_mark(value) in {"", "◎"}
    
    def get_concurrent_assignment_var(self,staff,day,section):
        """指定スタッフ・日付・兼務業務IDの割当変数を返す"""
        return self.concurrent_shifts[(staff,day,section)]
    
    def get_concurrent_work_var(self, staff, day):
        """スタッフの兼務業務シフト変数を取得する。"""
        return self.concurrent_shifts.get((staff, day))
    
    
    def get_concurrent_work_status(self,solver,staff,day):
        """兼務業務のシフトの解から、その日の出勤状態を返す"""
        concurrent_var = self.get_concurrent_work_var(staff, day)
        if concurrent_var is None:
            return None
        return bool(solver.Value(concurrent_var))
    
    
    def _init_constraints(self):
        """制約オブジェクトの初期化"""
        self.work_constraitns = WeeklyPlacementOptimizer(self.model,self)
        self.meeting_constraints = MeetingConstraints(self.model,self)
        self.concurrent_constraints = ConcurrentConstraints(self.model,self)
        
    def apply_all_constraints(self):
        """全ての制約を適用する"""
        self.work_constraitns.apply()
        self.meeting_constraints.apply()
        self.concurrent_constraints.apply()
        self.finalize_objective()
        
    def solve_with_fallback(self,max_time_seconds=60.0):
        """
        段階的ソルバー：解が見つからない場合、制約を段階的に緩和して再試行する

        Args:
            max_time_seconds (float, optional): _description_. Defaults to 60.0.
        """
        print("\n" + "="*60)
        print("段階的ソルバーを開始します")
        print("="*60)
        
        # 試行1: 厳密モード（全制約をハードとして実行）
        print("\n【試行1】厳密モード - 全制約をハード制約として実行")
        solver = cp_model.CpSolver()
        solver.parameters.log_search_progress = True
        solver.parameters.max_time_in_seconds = max_time_seconds

        status = solver.Solve(self.model)

        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            print("✓ 成功：厳密モードで制約を満たす解が見つかりました")
            return status,solver,[]
        
        status_name = solver.StatusName(status)
        if status == cp_model.INFEASIBLE:
            print("✗ 失敗：厳密モードでは制約を満たす解が存在しません (INFEASIBLE)")
            self.model.write_constraint_diagnostics(
                self.year,
                self.month,
                solver=solver,
            )
            failure_reason = "infeasible"
        elif status == cp_model.UNKNOWN:
            print(
                "? 未確定:制限時間内に解の有無を判定できませんでした"
                f" (UNKNOWN,status={status_name})"
            )
            failure_reason = "unknown"
        else:
            print(
                "✗ 失敗：厳密モードでは解が見つかりませんでした"
                f"(status={status_name})"
            )
            failure_reason = status_name.lower()
            
        # 試行2以降の段階的緩和をここに実装することができます
        #mode1のShiftOptimizer solve_with_faillbackを参照
        return status, solver, [failure_reason]
        
        

    def _select_porifa_days(self):
        """ポリファーマシーチームの開催日を選択する
        - 金曜日と火曜日の開催日を選択する
        - 月内の金曜日と火曜日の日付を返す
        - 金曜日を開催した翌週に火曜日を開催
        - 月内に火曜日が金曜日の翌週にない場合は、最も近い火曜日を選択する
        - 祝日は候補外
        - 月1回開催
        - ポリファーマシー所属メンバー全員が出勤の日に開催
        """
        
        team_column = "ポリファーマシーチーム"
        if team_column not in self.staff.columns:
            raise KeyError(f"{team_column} がスタッフ情報に存在しません")
        # ポリファーマシーチームのメンバーを取得
        members = self.staff.index[self.staff[team_column].fillna(False)]
        if len(members) == 0:
            raise ValueError(f"ポリファーマシー所属メンバーが登録されていません")
        #日付列のマッピングを作成
        day_columns = {
            str(column).strip():column
            for column in self.mode1_attendance_list.columns
        }
        #祝日
        holiday_dates = set()
        for holiday in self.holidays or []:
            holiday_date = holiday[0] if isinstance(holiday,tuple) else holiday
            if isinstance(holiday_date,datetime.datetime):
                holiday_date = holiday_date.date()
                
            if isinstance(holiday_date,datetime.date):
                holiday_dates.add(holiday_date)
                
        candidates = []
        for friday in range(1,self.days +1):
            friday_date = datetime.datetime(self.year,self.month,friday)
            tuesday = friday +4
            # 金曜日と火曜日の日付を作成
            if friday_date.weekday() !=4 or tuesday > self.days:
                #当日が金曜日でない、または火曜日が月内に存在しない場合はスキップ
                continue
            
            tuesday_date = datetime.datetime(self.year,self.month,tuesday)
            if friday_date.date() in holiday_dates or tuesday_date.date()in holiday_dates:
                # 金曜日または火曜日が祝日の場合はスキップ
                continue
            
            can_attend_both_days = True
            for staff in members:
                for day in (friday,tuesday):
                    column =day_columns.get(str(day))
                    if column is None:
                        raise KeyError(f"出勤表に{day}日が存在しません")
                    value = self.mode1_attendance_list.loc[staff,column]
                    if not (pd.isna(value) or str(value).strip() in {"","◎"}):
                        # 出勤できない日がある場合は両日出勤不可とする
                        can_attend_both_days = False
                        break
                if not can_attend_both_days:
                    break
                
            if can_attend_both_days:
                week = (friday - 1) // 7 + 1
                candidates.append((0 if week <=2 else 1,friday))
                
        if not candidates:
            raise ValueError("ポリファーマシー所属メンバー全員が出勤できる候補日が存在しません")
        
        _, friday = min(candidates)
        return friday,friday + 4

    def register_objective_term(self,term_name,term_expr):
        """
        目的関数の項を登録する
        term_name: 項の名前
        term_expr: 項の式
        """
        self.objective_terms.append((term_name, term_expr))
        
    def finalize_objective(self):
        """
        登録済みの目的関数項を合算し、合計値を最小化する目的関数として設定する。
        目的関数項が登録されていない場合は、何も設定しない。
        """
        if self.objective_terms:
            self.model.Minimize(
                sum(term for _, term in self.objective_terms)
            )