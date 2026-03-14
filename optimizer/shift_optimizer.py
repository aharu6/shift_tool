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

class ShiftOptimizer:
    def __init__(self,year,month,holidays,staff_list_pass,hope_list):
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
        self.staff = pd.read_excel(staff_list_pass,sheet_name="member_list",index_col=0,skiprows=1)
        #floorカラムを数値IDに変換
        if 'Floor' in self.staff.columns:
            self.staff['Floor'] = self.staff['Floor'].map(FLOOR_MAPPING)
        #floor2カラムを数値IDに変換
        if 'Floor2' in self.staff.columns:
            self.staff['Floor2'] = self.staff['Floor2'].map(FLOOR_MAPPING)
        #floor3カラムを数値IDに変換
        if 'Floor3' in self.staff.columns:
            self.staff['Floor3'] = self.staff['Floor3'].map(FLOOR_MAPPING)
            
        self.hope_list = hope_list
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
                    
        
        #午前シフト変数
        for staff in self.staff.index:
            pass
        
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
        
    def apply_all_constraints(self):
        """全ての制約を適用"""
        self.oncall_constraints.apply()
        self.work_requests.apply()
        self.work_constraints.apply()
        #self.meeting_constraints.apply()
    
    
    #9.連続勤務は最大6日まで
    
    #10.ソフト制約　日曜祝日出勤は可能な限り一人月1回までとする
    

    #12.兼務業務の割り当て
    def add_current_assignment(self):
        """
        兼務業務の割り当て制約を追加
        - 兼務業務は専属業務をもつスタッフ飲みに割り当てる
        - スタッフの業務可能な条件.xlsxの条件に基づいて割り当てる
        - 各兼務業務の必要人数を確保する
        """        
        
        #兼務業務毎の必要人数
        concurrent_required_num = {
            '心不全回診':1,
            'NST回診':1,
            'ICT回診':1,        
            '緩和回診(兼任)':1,
        }#会議は該当する役職者であればなるべく全員参加
        
        for day in range(1,self.days +1):
            for c_section in self.concurrent_sections:
                ecligible_staff = []
                for staff in self.staff.index:
                    if c_section in self.staff.columns and self.staff.loc[staff,c_section] == True:
                        ecligible_staff.append(staff)
                
                if ecligible_staff:
                    required_count = concurrent_required_num.get(c_section,0)
                    if c_section == 'RI':
                        self.model.Add(
                            sum(self.concurrent_shifts[(staff,day,c_section)]
                                for staff in ecligible_staff) <= 1
                        )
                    else:
                        self.model.Add(
                            sum(self.concurrent_shifts[(staff,day,c_section)]
                                for staff in ecligible_staff)==required_count
                        )
                    
                    for staff in self.staff.index:
                        if staff not in ecligible_staff:
                            self.model.Add(
                                self.concurrent_shifts[(staff,day,c_section)]==0
                            )
                            
        #1人あたりの兼務業務数を制限 当直を含める場合のみ１日２つまで
        for staff in self.staff.index:
            for day in range(1,self.days +1):
                self.model.Add(
                    sum(self.concurrent_shifts[(staff,day,c_section)]
                        for c_section in self.concurrent_sections)<=2
                )
    
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
