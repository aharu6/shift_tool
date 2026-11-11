from ortools.sat.python import cp_model
import pandas as pd
from collections.abc import Mapping
from datetime import datetime,timedelta
from config.sections import PRIMARY_SECTIONS
from config.concurrent_sections import CONCURRENT_SECTIONS
from config.hope_mapping import HOPE_MAPPING
from optimizer.mode1.primary_shift.work_constraints import WorkConstraints  
from optimizer.mode2.concurrent_shift.meeting_constraints import MeetingConstraints
from optimizer.mode1.night_shift.oncall_constraints import OncallConstraints
from optimizer.mode2.concurrent_shift.concurrent_constraints import ConcurrentConstraints
from optimizer.method.staff_name_matching import normalize_name_index, validate_name_alignment
from optimizer.mode1.constraint_diagnostics import TrackedCpModel
from optimizer.method.baseshiftoptimizer import BaseShiftOptimizer

class ShiftOptimizer(BaseShiftOptimizer):
    def __init__(self,year,month,holidays,staff_list_pass,hope_list,offrequest_day,
                previous_month_oncall_staff_ids=None,previous_month_shift=None,previous_year_end_shift=None,
                previous_year_december_30_staff=None,previous_december_31_staff=None,
                previous_january_1_staff=None,
                previous_january_2_staff=None,
                previous_january_3_staff=None,
                previous_oncall_counts=None,
                previous_month_oncall_counts=None,
                previous_months_with_two_oncalls=None):
        """
        シフト最適化
        専任業務を定義

        Args:
            year (_type_): 作成する年
            month (_type_): 作成する月
            staff_list_pass (_type_): スタッフ条件
            hope_list (_type_): 希望の休みリスト        
        """
        self.model = TrackedCpModel()
        self.year = year
        self.month = month
        self.holidays = holidays#祝日
        self.offrequest_day = offrequest_day# 月間の指定休
        self.days = BaseShiftOptimizer._get_days_in_month(self)
        self.staff = pd.read_excel(staff_list_pass, sheet_name="member_list", skiprows=1)
        self.staff = normalize_name_index(
            self.staff,
            source_label=staff_list_pass,
            name_column="Name",
            allow_index_fallback=False,
        )
        for column in ('当直', '休職', '主任以上'):
            if column in self.staff.columns:
                self.staff[column] = ShiftOptimizer._normalize_boolean_column(self.staff[column])
        #floorカラムを数値IDに変換
        if 'Floor' in self.staff.columns:
            self.staff['Floor'] = ShiftOptimizer._normalize_floor_column(self.staff['Floor'])
        #floor2カラムを数値IDに変換
        if 'Floor2' in self.staff.columns:
            self.staff['Floor2'] = ShiftOptimizer._normalize_floor_column(self.staff['Floor2'])
        #floor3カラムを数値IDに変換
        if 'Floor3' in self.staff.columns:
            self.staff['Floor3'] = ShiftOptimizer._normalize_floor_column(self.staff['Floor3'])
            
        self.hope_list = normalize_name_index(
            hope_list,
            source_label="希望リスト",
            name_column="Name",
            allow_index_fallback=True,
        )
        if "Name" in self.hope_list.columns:
            self.hope_list = self.hope_list.drop(columns=["Name"])
        validate_name_alignment(self.staff, self.hope_list)
        self.prev_month_shift = previous_month_shift
        self.previous_oncall_counts = dict(previous_oncall_counts or {})
        self.previous_month_oncall_counts = dict(previous_month_oncall_counts or {})
        self.previous_months_with_two_oncalls = dict(
            previous_months_with_two_oncalls or {}
        )
        self.prev_month_oncall_staff_by_day = (
            dict(previous_month_oncall_staff_ids)
            if isinstance(previous_month_oncall_staff_ids, Mapping)
            else {}
        )
        last_prev_day = (
            max(self.prev_month_oncall_staff_by_day)
            if self.prev_month_oncall_staff_by_day
            else None
        )
        self.prev_month_oncall_staff_ids = set(
            self.prev_month_oncall_staff_by_day.get(last_prev_day, [])
            if last_prev_day is not None
            else (previous_month_oncall_staff_ids or [])
        )
        self.prev_year_end_shift = previous_year_end_shift #前年度の年末年始のシフト
        self.previous_year_december_30_staff = set(previous_year_december_30_staff or [])#12/30の勤務者
        self.previous_december_31_staff = set(previous_december_31_staff or [])#12/31の勤務者
        self.previous_january_1_staff = set(previous_january_1_staff or [])#1/1の勤務者
        self.previous_january_2_staff = set(previous_january_2_staff or [])#1/2の勤務者
        self.previous_january_3_staff = set(previous_january_3_staff or [])#1/3の勤務者
        # 当直明け制約はデフォルトで厳密モードとし、翌日以外の明けを禁止する
        self.strict_oncall_nextday = True
        #希望リストを数値IDに変換
        for column in self.hope_list.columns:
            self.hope_list[column] = self.hope_list[column].apply(
                lambda x: HOPE_MAPPING.get(x,x) if pd.notna(x) else x
            )
        self.primary_sections = PRIMARY_SECTIONS.keys()
        self.concurrent_sections = CONCURRENT_SECTIONS.keys()        
        self.shifts = {}
        self.am_shifts = {}
        self.pm_shifts = {} # 午後業務用の変数辞書を追加
        self.night_shifts = {}  # 当直業務用の変数辞書を追加
        self.porifa_tuesday_vars = {}  # ポリファ火曜開催決定変数 {day: BoolVar}
        self.porifa_friday_vars = {}  # ポリファ金曜開催決定変数 {day: BoolVar}
        self.objective_terms = []  # 目的関数は最後に1回だけ設定する

    def register_objective_term(self, term_name, term_expr):
        """目的関数の項を登録する。"""
        self.objective_terms.append((term_name, term_expr))

    def create_variables(self):
        """
        mode1用のシフト変数を作成する
        oncall_shift,primary_shift,concurrent_shiftの変数を新規作成
        """
        # シフト変数(専属業務)
        for staff in self.staff.index:
            for day in range(1, self.days + 1):
                var_name = f'shift_{staff}_{day}'
                self.shifts[(staff, day)] = self.model.NewBoolVar(var_name)
        
        
        for day in range(1, self.days + 1):
            for index, staff1 in enumerate(self.staff.index):
                for staff2 in self.staff.index[index + 1:]:
                    var_name = f'oncall_{staff1}_{staff2}_{day}'
                    self.night_shifts[(staff1, staff2, day)] = (
                        self.model.NewBoolVar(var_name)
                    )
                    
        for day in range(1, self.days + 1):
            wd = datetime(self.year, self.month, day).weekday()
            if wd == 1:  # 火曜日
                self.porifa_tuesday_vars[day] = self.model.NewBoolVar(f'hold_porifa_tuesday_{day}')
            elif wd == 4:  # 金曜日
                self.porifa_friday_vars[day] = self.model.NewBoolVar(f'hold_porifa_friday_{day}')
    
    
    def get_primary_work_var(self, staff, day):
        """スタッフの日別出勤状態を表す変数を取得する。"""
        return self.shifts.get((staff, day))

    def get_primary_work_status(self, solver, staff, day):
        """専属シフトの解から、その日の出勤状態を返す。"""
        work_var = self.get_primary_work_var(staff, day)
        if work_var is None:
            return None
        return bool(solver.Value(work_var))
    
    
    
    def get_oncall_pair(self, staff1, staff2, day):
        """
        staff1とstaff2の当直ペア変数を取得（順序を正規化）
        
        Args:
            staff1: スタッフ1のインデックス
            staff2: スタッフ2のインデックス
            day: 日付
            
        Returns:
            当直ペア変数（存在する場合）、存在しない場合はNone
        """
        if staff1 == staff2:
            return None
        # staff1とstaff2が同じ場合はNoneを返す
        return self.night_shifts.get(
            (staff1, staff2, day),
            self.night_shifts.get((staff2, staff1, day)),
        )
        
        
    def get_had_oncall_yesterday_var(self, staff, day):
        """前日が当直だったかを示す変数を取得"""
        
        return self.work_constraints._get_had_oncall_yesterday_var(staff, day)
    
    def _init_constraints(self):
        """制約オブジェクトの初期化"""
        self.work_constraints = WorkConstraints(self.model, self)
        self.oncall_constraints = OncallConstraints(self.model,self)
        
    def apply_all_constraints(self):
        """全ての制約を適用"""
        for hold in (*self.porifa_tuesday_vars.values(), *self.porifa_friday_vars.values()):
            self.model.Add(hold == 0)
        self.oncall_constraints.apply()
        self.work_constraints.apply()
        self.work_constraints.log_oncall_work_candidate_overlap()
        self.model.Minimize(sum(term for _, term in self.objective_terms))

    
    def solve_with_fallback(self, max_time_seconds=60.0):
        """
        段階的ソルバー：解が見つからない場合、制約を段階的に緩和して再試行
        
        Args:
            max_time_seconds: 各試行のタイムアウト時間（秒）
        
        Returns:
            (status, solver, relaxed_constraints): 
                - status: 解のステータス
                - solver: CP-SATソルバー
                - relaxed_constraints: 緩和した制約のリスト
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
            print("✓ 成功：厳密モードで解が見つかりました")
            return status, solver, []
        
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
                "? 未確定：制限時間内に解の有無を判定できませんでした "
                f"(UNKNOWN, status={status_name})"
            )
            failure_reason = "unknown"
        else:
            print(
                "✗ 失敗：厳密モードでは解が見つかりませんでした "
                f"(status={status_name})"
            )
            failure_reason = status_name.lower()
        
        # 試行2: 月回数制限をソフト制約化（上限を超えることを許容）
        # 注意：この実装では既存の制約構造を変更せず、警告メッセージのみを出力
        print(f"\n【試行2】回数緩和モード - 月回数上限の緩和を検討 ({failure_reason})")
        print("  ℹ️  現在の実装では、制約の動的な緩和は未対応です")
        print("  ℹ️  解が見つからない場合は、以下を確認してください：")
        print("     1. 希望リストの入力ミス（同日に異性の希望、役職者2人など）")
        print("     2. 月回数上限を超える希望数")
        print("     3. 特定日に当直可能なスタッフが不足")
        
        # 今後の実装案：
        # - oncall_constraints.pyに「ソフト制約モード」フラグを追加
        # - 月回数制限を違反した場合のペナルティ変数を作成
        # - 目的関数に高ペナルティで追加
        
        print("\n" + "="*60)
        print("段階的ソルバー終了 - 解が見つかりませんでした")
        print("="*60)
        
        return status, solver, ["strict_mode_failed", failure_reason]
