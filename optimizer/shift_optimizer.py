from ortools.sat.python import cp_model
import pandas as pd
from datetime import datetime,timedelta
from config.sections import PRIMARY_SECTIONS
from config.concurrent_sections import CONCURRENT_SECTIONS
from config.floor_mapping import FLOOR_MAPPING
from config.hope_mapping import HOPE_MAPPING
from optimizer.primary_shift.work_constraints import WorkConstraints  
from optimizer.primary_shift.work_requests import WorkRequests
from optimizer.concurrent_shift.meeting_constraints import MeetingConstraints
from optimizer.night_shift.oncall_constraints import OncallConstraints
from optimizer.concurrent_shift.concurrent_constraints import ConcurrentConstraints
from staff_name_matching import normalize_name_index, validate_name_alignment


class ShiftOptimizer:
    @staticmethod
    def _normalize_boolean_column(values):
        """ブール列を正規化する。

        Args:
            values (pd.Series): ブール列

        Returns:
            pd.Series: 正規化されたブール列
        
        """
        # 文字列として解釈される「偽」の値のセット
        false_values = {
            '', '0', 'false', 'f', 'no', 'n', 'off',
            'なし', '無', '不可', '当直不可', '×',
        }

        def normalize(value):
            if pd.isna(value):
                return False
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return value != 0
            return str(value).strip().lower() not in false_values

        return values.map(normalize)

    def __init__(self,year,month,holidays,staff_list_pass,hope_list,previous_month_oncall_staff_ids=None):
        """
        シフト最適化
        専任業務を定義

        Args:
            year (_type_): 作成する年
            month (_type_): 作成する月
            staff_list_pass (_type_): スタッフ条件
            hope_list (_type_): 希望の休みリスト        
        """
        self.model = cp_model.CpModel()
        self.year = year
        self.month = month
        self.holidays = holidays
        self.days = self._get_days_in_month()
        self.staff = pd.read_excel(staff_list_pass, sheet_name="member_list", skiprows=1)
        self.staff = normalize_name_index(
            self.staff,
            source_label=staff_list_pass,
            name_column="Name",
            allow_index_fallback=False,
        )
        for column in ('当直', '休職', '主任以上'):
            if column in self.staff.columns:
                self.staff[column] = self._normalize_boolean_column(self.staff[column])
        #floorカラムを数値IDに変換
        if 'Floor' in self.staff.columns:
            self.staff['Floor'] = self.staff['Floor'].map(FLOOR_MAPPING)
        #floor2カラムを数値IDに変換
        if 'Floor2' in self.staff.columns:
            self.staff['Floor2'] = self.staff['Floor2'].map(FLOOR_MAPPING)
        #floor3カラムを数値IDに変換
        if 'Floor3' in self.staff.columns:
            self.staff['Floor3'] = self.staff['Floor3'].map(FLOOR_MAPPING)
            
        self.hope_list = normalize_name_index(
            hope_list,
            source_label="希望リスト",
            name_column="Name",
            allow_index_fallback=True,
        )
        validate_name_alignment(self.staff, self.hope_list)
        self.prev_month_oncall_staff_ids = previous_month_oncall_staff_ids #前月当直者辞書{日付:staff_name_list}
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
        self.concurrent_shifts = {}  # 兼務業務用の変数辞書を追加
        self.night_shifts = {}  # 当直業務用の変数辞書を追加
        self.objective_terms = []  # 目的関数は最後に1回だけ設定する

    def register_objective_term(self, term_name, term_expr):
        """目的関数の項を登録する。"""
        self.objective_terms.append((term_name, term_expr))

    def finalize_objective(self):
        """登録済みの目的項を合算して目的関数を確定する。"""
        if not self.objective_terms:
            print("目的項が未登録のため、0目的で最適化します。")
            self.model.Minimize(0)
            return

        total_penalty = sum(term for _, term in self.objective_terms)
        print(f"目的関数を確定します。登録済み項数: {len(self.objective_terms)}")
        self.model.Minimize(total_penalty)
        
    
    def create_variables(self):
        # シフト変数(専属業務)
        for staff in self.staff.index:
            for day in range(1, self.days + 1):
                for section in self.primary_sections:
                    var_name = f'shift_{staff}_{day}_{section}'
                    self.shifts[(staff, day, section)] = self.model.NewBoolVar(var_name)
        
        # 兼務業務の変数を追加
        for staff in self.staff.index:
            for day in range(1, self.days + 1):
                for section in self.concurrent_sections:
                    var_name = f'concurrent_{staff}_{day}_{section}'
                    self.concurrent_shifts[(staff, day, section)] = self.model.NewBoolVar(var_name)
                    
        
        # 当直変数
        for day in range(1,self.days +1):
            for i, staff1 in enumerate(self.staff.index):
                for staff2 in self.staff.index[i+1:]:
                    var_name = f'oncall_{staff1}_{staff2}_{day}'
                    self.night_shifts[(staff1,staff2,day)] = self.model.NewBoolVar(var_name)
    
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
        # 常に小さいインデックスを先に（変数定義時の順序と一致させる）
        s1, s2 = (staff1, staff2) if staff1 < staff2 else (staff2, staff1)
        return self.night_shifts.get((s1, s2, day), None)
        
        
    def _get_days_in_month(self):
        if self.month ==12:
            next_month =datetime(self.year +1,1,1)
        else:
            next_month =datetime(self.year,self.month +1,1)
        last_day = (next_month - timedelta(days=1)).day
        return last_day
    
    
    def _init_constraints(self):
        """制約オブジェクトの初期化"""
        self.work_constraints = WorkConstraints(self.model,self)
        self.work_requests = WorkRequests(self.model,self)
        self.oncall_constraints = OncallConstraints(self.model,self)
        self.meeting_constraints = MeetingConstraints(self.model,self)
        self.concurrent_constraints = ConcurrentConstraints(self.model,self)
        
    def apply_all_constraints(self):
        """全ての制約を適用"""
        self.oncall_constraints.apply()
        self.work_requests.apply()
        self.work_constraints.apply()
        self.concurrent_constraints.apply()
        self.finalize_objective()   

    
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
        
        print(f"✗ 失敗：厳密モードでは解が見つかりませんでした (status={solver.StatusName(status)})")
        
        # 試行2: 月回数制限をソフト制約化（上限を超えることを許容）
        # 注意：この実装では既存の制約構造を変更せず、警告メッセージのみを出力
        print("\n【試行2】回数緩和モード - 月回数上限の緩和を検討")
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
        
        return status, solver, ["strict_mode_failed"]
