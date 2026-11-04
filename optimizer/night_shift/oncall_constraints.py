from optimizer.base_constraint import BaseConstraint
from datetime import datetime
import pandas as pd
from ortools.sat.python import cp_model
from config.objective_weights import (
    WEIGHT_PREVIOUS_YEAR_DECEMBER_30_AVOIDANCE,
    WEIGHT_PREVIOUS_DECEMBER_31_AVOIDANCE,
    WEIGHT_PREVIOUS_JANUARY_1_AVOIDANCE,
    WEIGHT_PREVIOUS_JANUARY_2_AVOIDANCE,
    WEIGHT_PREVIOUS_JANUARY_3_AVOIDANCE,
    WEIGHT_ONCALL_PREV_MONTH_BALANCE,
    WEIGHT_ONCALL_TWO_PER_MONTH_HISTORY,
)
from config.oncall_rule_configs import SOFT_ONCALL_RULE_CONFIGS
class OncallConstraints(BaseConstraint):
    """
    当直に関する制約条件を定義するクラス
    - 2回を上限
    - 同日の希望が同フロアに集中する場合は競合として扱う
    - 同性ペアリングを考慮する
    - 同日希望者が3人以上の場合は不成立として扱う
    - 同日希望者が少数の相手候補に集中する場合は複数日の相互依存を考慮する
    - 当直希望が同日に集中する場合は公平性を考慮する
    - 当直希望が3人以上の場合は不成立として扱う
    - 当直希望が前月や前々月に偏っている場合は調整を考慮する
    - 当直希望が特定の曜日に偏っている場合は調整を考慮する
    - 当直希望が少数の相手候補に集中する場合は複数日の相互依存を考慮する
    - 当直希望が特定のスタッフに偏っている場合は調整を考慮する
    - 同フロアでの当直は避ける
    - 薬審の前日は担当者はなるべく当直を避ける
    - 緩和回診の前日はなるべく当直を避ける
    - 第二金曜日の病棟担当者カンファレンスの前日はなるべく避ける
    - primary_shiftを参照、休みの日は当直に割り当てない
    """
    def __init__(self, model,optimizer):
        super().__init__(model, optimizer)
        # 月累計当直回数を追跡する変数（公平性判断に使用）
        self.monthly_oncall_counts = {}
        self._had_oncall_today_vars = {}
        self._soft_oncall_rule_configs = SOFT_ONCALL_RULE_CONFIGS
        self.sync_penalties = self.add_oncall_paring_sync_constraints()
        
    def apply(self):
        # 制約の適用順序を変更：除外制約を先に適用してから、毎日の確保を行う
        self.add_oncall_constraints()#当直の基本制約（希望リストによる除外など）
        self._validate_oncall_requests()#事前検証：希望と制約の競合チェック
        self.apply_oncall_requests()#当直希望を叶える
        self.add_oncall_paring_constraints()#同性でペアリング
        self.add_oncall_spacing_constraints()#前回の当直から次回の当直までは最低7日間空ける    
        self.add_daily_oncall()#毎日の当直確保
        #TODO:非出勤日に当直を割り当てない、は出勤の公平性が決定してから実装する
        self.apply_primary_shift_constraints()#primary_shiftが非出勤の日は当直に割り当てない
        self.apply_weighted_objective()#重みづけした目的関数を設定(外来の当直希望、なるべく同じフロア避ける)
    
        self._print_oncall_statistics()  # 統計情報を出力
    
    def _print_oncall_statistics(self):
        """当直に関する統計情報を出力（デバッグ用）"""
        print("\n===== 当直最適化の統計情報 =====")
        
        # 当直可能なスタッフ数をカウント
        oncall_available = self.staff[self.staff['当直'] == True]
        oncall_available = oncall_available[oncall_available['休職'] == False]
        
        # 性別ごとにカウント（'M' = 男性, 'W' = 女性）
        male_count = len(oncall_available[oncall_available['Sex'] == 'M'])
        female_count = len(oncall_available[oncall_available['Sex'] == 'W'])
        
        # 役職者・外来のカウント
        role_floor_count = len(oncall_available[
            (oncall_available['Floor'].isin([9, 10])) & 
            (oncall_available['主任以上'] == True)
        ])
        regular_staff = len(oncall_available) - role_floor_count
        
        print(f"当直可能スタッフ総数: {len(oncall_available)}人")
        print(f"  - 男性(M): {male_count}人")
        print(f"  - 女性(W): {female_count}人")
        print(f"  - 役職者・外来（月1回まで）: {role_floor_count}人")
        print(f"  - 通常スタッフ（月1-2回）: {regular_staff}人")
        
        # 可能なペア数の概算
        male_pairs = male_count * (male_count - 1) // 2
        female_pairs = female_count * (female_count - 1) // 2
        total_pairs = male_pairs + female_pairs
        
        print(f"\n同性ペアの理論上の組み合わせ数:")
        print(f"  - 男性ペア: {male_pairs}通り")
        print(f"  - 女性ペア: {female_pairs}通り")
        print(f"  - 合計: {total_pairs}通り")
        
        # 必要な当直ペア数
        required_oncalls = self.days  # 毎日1-2人（最低31人分）
        print(f"\n月間必要当直数: 最低{required_oncalls}人分（毎日最低1人）")
        print(f"通常スタッフが月2回ずつ担当した場合: {regular_staff * 2}人分")
        
        if regular_staff * 2 < required_oncalls:
            print(f"⚠️ 警告: スタッフ数が不足している可能性があります")
            print(f"   不足: {required_oncalls - regular_staff * 2}人分")
        else:
            print(f"✓ スタッフ数は充足しています（余剰: {regular_staff * 2 - required_oncalls}人分）")
        
        print("=" * 40 + "\n")
        
    def add_daily_oncall(self):
        """
        毎日誰かが当直になるようにする
        """
        print("毎日の当直を確保します。")
        
        # デバッグ: 各日の利用可能なペア数をカウント
        daily_available_pairs = {}
        for day in range(1, self.days + 1):
            pair_count = 0
            all_pairs= 0
            static_possible_pairs = 0
            
            for i,staff1 in enumerate(self.staff.index):
                for staff2 in self.staff.index[i + 1:]:
                    pair_var = self.optimizer.get_oncall_pair(staff1,staff2,day,)
                    
                    if pair_var is None:
                        continue
                    
                    all_pairs += 1
                    reasons = []
                    
                    if not bool(self.staff.loc[staff1,'当直']):
                        reasons.append(f"{staff1}:当直不可")
                    if not bool(self.staff.loc[staff2,'当直']):
                        reasons.append(f"{staff2}:当直不可")
                    
                    if bool(self.staff.loc[staff1,'休職']):
                        reasons.append(f"{staff1}:休職")
                    if bool(self.staff.loc[staff2,'休職']):
                        reasons.append(f"{staff2}:休職")
                        
                    if self.staff.loc[staff1,'Sex'] !=self.staff.loc[staff2,'Sex']:
                        reasons.append('異性')
                        
                    if (
                        self.staff.loc[staff1,'同期変数']
                        ==self.staff.loc[staff2,'同期変数']
                    ):
                        reasons.append('同期')
                        
                    if (
                        bool(self.staff.loc[staff1,'主任以上']) and bool(self.staff.loc[staff2,'主任以上'])
                    ):
                        reasons.append('主任以上同士')
                        
                    hope1 = self._get_hope_value(staff1,day,default=7)#複数ある場合はリストで返ってくる
                    hope2 = self._get_hope_value(staff2,day,default=7)
                    
                    if self._hope_matches(hope1, {0,2,3,5,6}):
                        reasons.append(f"{staff1}:希望{hope1}")
                    if self._hope_matches(hope2, {0,2,3,5,6}):
                        reasons.append(f"{staff2}:希望{hope2}")
                    if not reasons:
                        static_possible_pairs += 1
                    
            for staff1 in self.staff.index:
                for staff2 in self.staff.index:
                    if staff1 < staff2:  # ペアは一度だけカウント
                        pair_var = self.optimizer.get_oncall_pair(staff1, staff2, day)
                        if pair_var is not None:
                            pair_count += 1
            daily_available_pairs[day] = pair_count
        
        # 利用可能ペア数が少ない日を警告
        print(f"\n各日の定義済みペア数:")
        problematic_days = []
        for day in range(1, min(10, self.days + 1)):  # 最初の10日を表示
            count = daily_available_pairs[day]
            status = "⚠️" if count < 10 else "✓"
            print(f"  {day}日: {count}ペア {status}")
            if count == 0:
                problematic_days.append(day)
        
        if problematic_days:
            print(f"\n⚠️ 警告: 次の日にペアが定義されていません: {problematic_days}")
            print("   これらの日は「毎日最低1人」制約を満たせません")
        print()
        
        for day in range(1,self.days +1):
            daily_oncalls = []
            daily_pair_vars = []
            for staff1 in self.staff.index:
                staff_oncall = self.model.NewBoolVar(f'staff_{staff1}_oncall_day_{day}')
                #スタッフがペアの1番目または2番目にいる場合、当直に入っている
                oncall_pairs = []
                for other_staff in self.staff.index:
                    if staff1 != other_staff:
                        pair_var = self.optimizer.get_oncall_pair(staff1, other_staff, day)
                        if pair_var is not None:
                            oncall_pairs.append(pair_var)
                            if not any(existing is pair_var for existing in daily_pair_vars):
                                daily_pair_vars.append(pair_var)

                daily_oncalls.append(staff_oncall)#各スタッフに作成した変数を日時集計用のdaily_oncallsリストに追加
                        
                #いずれかのペアに入っていればstaff_oncallは1
                self.model.Add(sum(oncall_pairs) >=1).OnlyEnforceIf(staff_oncall)
                self.model.Add(sum(oncall_pairs) ==0).OnlyEnforceIf(staff_oncall.Not())
                # 1人が同じ日に複数の当直ペアへ入ることを防ぐ
                self.model.Add(sum(oncall_pairs) <= 1)
                
                
                
            #最低1人,最高2人が当直になるようにする
            self.model.Add(sum(daily_oncalls) >=1)
            self.model.Add(sum(daily_oncalls) <=2)
            # 当直は1日1ペアまで。スタッフ数の上限だけでは、ペア単位の意図が明示されない。
            self.model.Add(sum(daily_pair_vars) == 1)
    
    #6.当直は月2回まで,当直不可のスタッフは除外する
    def add_oncall_constraints(self):
        """
        当直の基本制約
        - 当直不可のスタッフは除外
        - 休職中のスタッフは除外
        - 役職者、外来部門のスタッフは月1回まで
        - 翌日が当直明けの日はなるべく除外する,役職者限定(薬審の日が当直明けにならないようにする)
        - 薬審は偶数月の第一木曜日
        - 月2回まで（1番目でも2番目でも合計で2回まで）役職者、外来部門以外のスタッフは月2回まで、最低月1回
        - 当直不可の日は避ける
        - 休み希望の日は避ける、明けの日が当直にならないように休み希望の前日も避ける
        - 当直TRUE&休職FALSE&Floor!=外来のスタッフにおいて、最低1回/月は当直に割り当てる
        
        """
        print("当直の基本制約を適用します。")
        
        for staff in self.staff.index:
            if self.staff.loc[staff,'当直']==False:
                print(f"{staff}さんは当直不可のため、当直割り当てを行いません。")
                for day in range(1,self.days +1):                
                    for other_staff in self.staff.index:
                        if staff != other_staff:
                            pair_var = self.optimizer.get_oncall_pair(staff, other_staff, day)
                            if pair_var is not None:
                                self.model.Add(pair_var == 0)
            #休職中のスタッフは当直割り当てを行わない
            elif self.staff.loc[staff,'休職']==True:
                print(f"{staff}さんは休職中のため、当直割り当てを行いません。")
                for day in range(1,self.days +1):                
                    for other_staff in self.staff.index:
                        if staff != other_staff:
                            pair_var = self.optimizer.get_oncall_pair(staff, other_staff, day)
                            if pair_var is not None:
                                self.model.Add(pair_var == 0)
            else:
                total_oncalls = [] #当直回数のカウント用リスト
                total_oncalls_role = [] #役職者当直回数のカウント用リスト
                staff_not_oncall_days = []#当直不可日のチェック
                staff_holidays = []#休み希望のチェック
                staff_keichou_days = []#慶弔休暇のチェック
                staff_iku_days = []#育休のチェック
                staff_kenshu_days = []#研修のチェック
                staff_gakkai_days = []#学会のチェック
                staff_AM_days = []#午前出勤希望のチェック
                staff_PM_days = []#午後出勤希望のチェック
                
                #役職のチェック 、外来部門・役職者の当直は月１回まで
                #役職者の場合、翌日が薬審の日はなるべく当直を避ける
                
                for day in range(1,self.days +1):
                    #当直不可の日を避ける 
                    """
                    前日も当直に割り当てない
                    - 休み希望、慶弔休暇、育休、研修、学会、外来希望、出勤希望、午前出勤希望、午後出勤希望
                    - TODO:当直の次の次の日が出勤希望の場合は当直になるべく割り当てない ソフト制約
                    - 午後出勤希望の場合は当日当直⚪︎、前日当直×
                    """
                    print(f"スタッフ{staff}さんの希望は{self._get_hope_value(staff, day, default=7)}です。")
                    hope_value = self._get_hope_value(staff, day, default=7)
                    if self._hope_matches(hope_value, {2}):#当直不可の日を避ける
                        staff_not_oncall_days.append(day)
                    #_get_hope_value []内に2が含まれている場合（当×、出当×）は当直を避ける
                        
                    if self._hope_matches(hope_value, {0}):#休み希望の日を避ける
                        staff_holidays.append(day)
                        if day-1 >= 1:
                            staff_holidays.append(day-1)#休み希望の前日も避ける
                    
                    if self._hope_matches(hope_value, {5}):#慶弔休暇の日を避ける
                        staff_keichou_days.append(day)
                        if day-1 >= 1:
                            staff_keichou_days.append(day-1)#慶弔休暇の前日も避ける
                    
                    if self._hope_matches(hope_value, {3}):#育休の日を避ける
                        staff_iku_days.append(day)
                        if day-1 >= 1:
                            staff_iku_days.append(day-1)#育休の前日も避ける
                    
                    if self._hope_matches(hope_value, {6}):#研修の日を避ける
                        staff_kenshu_days.append(day)
                        if day-1 >= 1:  
                            staff_kenshu_days.append(day-1)#研修の前日も避ける
                    
                    if self._hope_matches(hope_value, {11}):#学会の日を避ける
                        print(f"day{day},スタッフ{staff}さんの希望は学会の日です。当直を避けます")
                        staff_gakkai_days.append(day)
                        if day-1 >= 1:
                            staff_gakkai_days.append(day-1)#学会の前日も避ける
                    
                    if self._hope_matches(hope_value, {1}):#出勤希望の前日は当直を避ける
                        #出勤希望の前日は当直に割り当てない
                        if day -1 >=1:
                            staff_holidays.append(day -1)#出勤希望の前日も避ける
                            
                    if self._hope_matches(hope_value, {9}):#午前出勤希望の前日は当直を避ける
                        if day -1 >=1:
                            staff_AM_days.append(day -1)#午前出勤希望の前日を避ける
                    if self._hope_matches(hope_value, {10}):#午後出勤希望の前日は当直を避ける
                        if day -1 >=1:
                            staff_PM_days.append(day -1)#午後出勤希望の前日を避ける
                            
                #午前出勤希望の前日の当直を避ける
                for am_day in staff_AM_days:
                    for other_staff in self.staff.index:
                        if staff != other_staff:
                            pair_var = self.optimizer.get_oncall_pair(staff, other_staff, am_day)
                            if pair_var is not None:
                                self.model.Add(pair_var == 0)
                #午後出勤希望の前日の当直を避ける
                for pm_day in staff_PM_days:
                    for other_staff in self.staff.index:
                        if staff != other_staff:
                            pair_var = self.optimizer.get_oncall_pair(staff, other_staff, pm_day)
                            if pair_var is not None:
                                self.model.Add(pair_var == 0)
                                print(f"スタッフ{staff}の{pm_day}日の午後出勤希望の前日({pm_day})を避けます。")
                #当直不可の日を避ける
                for not_oncall_day in staff_not_oncall_days:
                    for other_staff in self.staff.index:
                        if staff != other_staff:
                            pair_var = self.optimizer.get_oncall_pair(staff, other_staff, not_oncall_day)
                            if pair_var is not None:
                                self.model.Add(pair_var == 0)
                            
                #休み希望の日と前日の当直を避ける
                for holiday in staff_holidays:#休み希望と前日が入っている
                    for other_staff in self.staff.index:
                        if staff != other_staff:
                            pair_var = self.optimizer.get_oncall_pair(staff, other_staff, holiday)
                            if pair_var is not None:
                                self.model.Add(pair_var == 0)
                            
                
                #慶弔休暇の日と前日の当直を避ける
                for keichou_day in staff_keichou_days:
                    for other_staff in self.staff.index:
                        if staff != other_staff:
                            pair_var = self.optimizer.get_oncall_pair(staff, other_staff, keichou_day)
                            if pair_var is not None:
                                self.model.Add(pair_var == 0)
                            
                #育休の日の当直を避ける
                for iku_day in staff_iku_days:
                    for other_staff in self.staff.index:
                        if staff != other_staff:
                            pair_var = self.optimizer.get_oncall_pair(staff, other_staff, iku_day)
                            if pair_var is not None:
                                self.model.Add(pair_var == 0)
                            
                #研修の日と前日の当直を避ける
                for kenshu_day in staff_kenshu_days:
                    for other_staff in self.staff.index:
                        if staff != other_staff:
                            pair_var = self.optimizer.get_oncall_pair(staff, other_staff, kenshu_day)
                            if pair_var is not None:
                                self.model.Add(pair_var == 0)
                            
                #外来部門、または役職者の当直は月1回まで
                if (self.staff.loc[staff,'Floor'] in [9]) or (self.staff.loc[staff,'主任以上']==True):
                    for day in range(1,self.days +1):
                        for other_staff in self.staff.index:
                            if staff != other_staff:
                                pair_var = self.optimizer.get_oncall_pair(staff, other_staff, day)
                                if pair_var is not None:
                                    total_oncalls_role.append(pair_var)
                                    
                    if total_oncalls_role:  # リストが空でない場合のみ制約追加
                        self.model.Add(sum(total_oncalls_role)<=1)
                        
                        # 月累計当直回数の追跡変数を作成（役職者用）
                        monthly_count = self.model.NewIntVar(0, 1, f'monthly_oncall_count_{staff}')
                        self.model.Add(monthly_count == sum(total_oncalls_role))
                        self.monthly_oncall_counts[staff] = monthly_count  
                
                elif self.staff.loc[staff,'当直']==True and self.staff.loc[staff,'休職']==False and self.staff.loc[staff,'Floor'] not in [9]:
                    print(f"当直可能かつ、休職しておらず、Floor!=外来のスタッフ: {staff}")
                    print(f"月1回以上の当直を割り当てます。")
                    #当直可能&休職していない&Floor!=外来のスタッフ
                    #月1回以上は割り当てる
                    #月2回までの制約
                    for day in range(1,self.days +1):
                        for other_staff in self.staff.index:
                            if staff != other_staff:
                                pair_var = self.optimizer.get_oncall_pair(staff, other_staff, day)
                                if pair_var is not None:
                                    total_oncalls.append(pair_var)
                            
                    #月1回以上、2回までの制約を追加
                    if total_oncalls:  # リストが空でない場合のみ制約追加
                        self.model.Add(sum(total_oncalls)>=1)
                        self.model.Add(sum(total_oncalls)<=2)
                        
                        # 月累計当直回数の追跡変数を作成（公平性判断に使用）
                        monthly_count = self.model.NewIntVar(0, 2, f'monthly_oncall_count_{staff}')
                        self.model.Add(monthly_count == sum(total_oncalls))
                        self.monthly_oncall_counts[staff] = monthly_count
    
    # primary_shiftを参照、非出勤日は当直に割り当てない
    def apply_primary_shift_constraints(self):
        """
        primary_shift参照
        非出勤日は当直に割り当てない
        """
        for day in range(1, self.days + 1):
            for staff in self.staff.index:
                for other_staff in self.staff.index:
                    if staff != other_staff:
                        pair_var = self.optimizer.get_oncall_pair(staff, other_staff, day)
                        if pair_var is not None:
                            work_var = self.optimizer.get_primary_work_var(staff, day)
                            if work_var is None:
                                continue
                            self.model.Add(pair_var == 0).OnlyEnforceIf(work_var.Not())

    def yakushin_nextday(self):
        """
        - 役職者
        - 薬審の前日はなるべく当直を避ける
        - ソフト制約、ペナルティ変数で管理する
        """
        even_months = [2,4,6,8,10,12]
        penalties = []
        
        #翌日が薬審の日は当直を避ける(役職者限定)
        for staff in self.staff.index:
            if self.staff.loc[staff,'主任以上']==True:
                print(f"{staff}さんは役職者のため、薬審の日の当直をなるべく避けます。")
                if self.month in even_months:
                    print(f"{self.month}月は偶数月のため、薬審は第一木曜日に開催されます")
                    first_thursday = [day for day in range(1,self.days +1) if datetime(self.year,self.month,day).weekday()==3]
                    if first_thursday:
                        print(f"薬審の日は{first_thursday[0]}日です。")
                        first_thursday = first_thursday[0]
                        #休み希望をチェック
                        if self._hope_matches(
                            self._get_hope_value(staff, first_thursday, default=7),
                            {0},
                        ):
                            for other_staff in self.staff.index:
                                if staff != other_staff:
                                    pair_var = self.optimizer.get_oncall_pair(staff,other_staff,first_thursday-1)
                                    if pair_var is not None:
                                        self.model.Add(pair_var == 0)
                        else:
                            penalty_var = self.model.NewBoolVar(
                                f'oncall_before_pharmacy_penalty_{staff}_{first_thursday}'
                            )
                            violation_pairs = []
                            for other_staff in self.staff.index:
                                if staff != other_staff:
                                    pair_var = self.optimizer.get_oncall_pair(staff,other_staff,first_thursday-1)
                                    if pair_var is not None:
                                        violation_pairs.append(pair_var)
                            if violation_pairs:
                                violation_count = self.model.NewIntVar(
                                    0,
                                    len(violation_pairs),
                                    f'oncall_before_pharmacy_violation_count_{staff}_{first_thursday}'
                                )
                                self.model.Add(violation_count == sum(violation_pairs))
                                self.model.Add(violation_count >= 1).OnlyEnforceIf(penalty_var)
                                self.model.Add(violation_count == 0).OnlyEnforceIf(penalty_var.Not())
                                penalties.append(penalty_var)
        return penalties

    def _get_soft_oncall_event_days(self, rule):
        """ソフト制約ルールごとに対象イベント日を算出する。"""
        event_type = rule['event_type']

        if event_type == 'third_friday':
            fridays = [
                day for day in range(1, self.days + 1)
                if datetime(self.year, self.month, day).weekday() == 4
            ]
            if len(fridays) < 3:
                print(rule.get('missing_event_message', '対象日が存在しないためスキップします。'))
                return None, []
            third_friday = fridays[2]
            if rule.get('print_third_friday', False):
                print(f"第三金曜日は{third_friday}日です。")
            return third_friday, [third_friday]

        if event_type == 'monday_tuesday_thursday':
            mondays = [
                day for day in range(1, self.days + 1)
                if datetime(self.year, self.month, day).weekday() == 0
            ]
            tuesdays = [
                day for day in range(1, self.days + 1)
                if datetime(self.year, self.month, day).weekday() == 1
            ]
            thursdays = [
                day for day in range(1, self.days + 1)
                if datetime(self.year, self.month, day).weekday() == 3
            ]
            return None, mondays + tuesdays + thursdays

        if event_type == 'second_friday':
            fridays = [
                day for day in range(1, self.days + 1)
                if datetime(self.year, self.month, day).weekday() == 4
            ]
            if len(fridays) < 2:
                print(rule.get('missing_event_message', '対象日が存在しないためスキップします。'))
                return None, []
            second_friday = fridays[1]
            if rule.get('print_second_friday', False):
                print(f"第二金曜日は{second_friday}日です。")
            return second_friday, [second_friday]
        
        if event_type == 'fourth_friday':
            fridays = [
                day for day in range(1, self.days + 1)
                if datetime(self.year, self.month, day).weekday() == 4
            ]
            if len(fridays) < 4:
                print(rule.get('missing_event_message', '対象日が存在しないためスキップします。'))
                return None, []
            fourth_friday = fridays[3]
            if rule.get('print_fourth_friday', False):
                print(f"第四金曜日は{fourth_friday}日です。")
            return fourth_friday, [fourth_friday]
        
        if event_type == 'porifa':
            # ポリファーマシー候補の全火曜日と全金曜日を取得（祝日除く）
            event_days = []
            for day in range(1, self.days + 1):
                wd = datetime(self.year, self.month, day).weekday()
                if wd in [1, 4] and not self._is_holiday(day):
                    event_days.append(day)

            if not event_days:
                print(rule.get('missing_event_message', '対象日が存在しないためスキップします。'))
                return None, []
            return None, event_days
        
        if event_type == 'exective_meeting':
            # 役職者会議の前日を避ける制約
            #第1と第３の月曜日
            meeting_days = [day for day in range(1, self.days + 1) if datetime(self.year, self.month, day).weekday() == 0 and ((day - 1) // 7 + 1) in [1, 3]]
            if not meeting_days:
                print(rule.get('missing_event_message', '対象日が存在しないためスキップします。'))
                return None, []
            return None, meeting_days
        
        if event_type == 'dementia_round':
            # 認知症せん妄ラウンドの前日を避ける制約
            #火曜と金曜
            round_days = [day for day in range(1, self.days + 1) if datetime(self.year, self.month, day).weekday() in [1, 4]]
            if not round_days:
                print(rule.get('missing_event_message', '対象日が存在しないためスキップします。'))
                return None, []
            return None, round_days

        # pm_shiftはスタッフごとに希望日が異なるため_build_hope_shift_penalties内で個別処理する
        
        #研修、学会はスタッフごとに希望日が異なるため、_build_hope_shift_penalties内で個別処理する
        
        
        return None, []

    def _build_hope_shift_penalties(self, rule,type,penalties,hope_value):
        """午前と午後の出勤希望に基づく前々日当直ペナルティを生成する。"""
        for staff in self.staff.index:
            event_days = [
                day for day in range(1,self.days+1)
                if self._hope_matches(self._get_hope_value(staff, day, default=7), hope_value)
            ]    
            for event_day in event_days:
                target_day = event_day - rule['offset_days']
                if target_day <1:
                    continue
                
                violation_pairs = []
                for other_staff in self.staff.index:
                    if staff==other_staff:
                        continue
                    pair_var= self.optimizer.get_oncall_pair(staff,other_staff,target_day)
                    if pair_var is not None:
                        violation_pairs.append(pair_var)
                        
                if not violation_pairs:
                    continue
                
                penalty_var = self.model.NewBoolVar(
                    f'{rule['penalty_prefix']}_{staff}_{event_day}'
                )
                violation_count = self.model.NewIntVar(
                    0,len(violation_pairs),
                    f"{rule['penalty_prefix']}_{staff}_{event_day}"
                )
                self.model.Add(violation_count == sum(violation_pairs))
                self.model.Add(violation_count >=1).OnlyEnforceIf(penalty_var)
                self.model.Add(violation_count ==0).OnlyEnforceIf(penalty_var.Not())
                penalties.append(penalty_var)
                print(f"{type}の出勤希望があるため、前々日の当直をなるべく避けるペナルティを追加します{staff}_{event_day}")
    
    def _build_soft_oncall_penalties(self, rule_key):
        """設定テーブルに基づいてソフト制約ペナルティを生成する。"""
        rule = self._soft_oncall_rule_configs[rule_key]
        print(rule['start_message'])
        penalties = []

        anchor_day, event_days = self._get_soft_oncall_event_days(rule)
        

        if rule.get('check_negative_offset', False) and anchor_day is not None:
            if anchor_day - rule['offset_days'] < 1:
                print(rule['negative_offset_message'])
                return penalties
            
        if rule.get('event_type')=='am_shift':
            self._build_hope_shift_penalties(rule = rule,type='am_shift',penalties=penalties,hope_value={9})
            return penalties
        
        if rule.get('event_type')=='pm_shift':
            self._build_hope_shift_penalties(rule = rule,type='pm_shift',penalties=penalties,hope_value={10})
            return penalties        
        
        if rule.get('event_type')=='training':
            self._build_hope_shift_penalties(rule = rule,type='training',penalties=penalties,hope_value={6})
            return penalties
        if rule.get('event_type')=='conference':
            self._build_hope_shift_penalties(rule = rule,type='conference',penalties=penalties,hope_value={11})
            return penalties
        
        if not event_days:
                    return penalties
                
        for staff in self.staff.index:
            if not self._is_enabled_value(self.staff.loc[staff, rule['staff_attr']]):
                non_target_message = rule.get('non_target_message')
                if non_target_message:
                    print(f"{staff}さんは{non_target_message}")
                continue
            
            
            require_floor_any = rule.get('require_floor_any')
            if require_floor_any:
                floor_values = [
                    self.staff.loc[staff, 'Floor'],
                    self.staff.loc[staff, 'Floor2'],
                    self.staff.loc[staff, 'Floor3'],
                ]
                if not self._has_required_floor(floor_values, require_floor_any):
                    continue        

            holiday_check = rule.get('holiday_check')
            if holiday_check in ['third_friday', 'second_friday', 'fourth_friday'] and anchor_day is not None:
                if self._hope_matches(self._get_hope_value(staff, anchor_day, default=7), {0}):
                    continue

            for event_day in event_days:
                if (
                    holiday_check == 'event_days'
                    and self._hope_matches(
                        self._get_hope_value(staff, event_day, default=7),
                        {0},
                    )
                ):
                    holiday_skip_message = rule.get('holiday_skip_message')
                    if holiday_skip_message:
                        print(f"{staff}さんは{holiday_skip_message}")
                    continue

                hold_porifa_var = None
                if holiday_check == 'porifa':
                    if self._hope_matches(self._get_hope_value(staff, event_day, default=7), {0}):
                        continue
                    wd = datetime(self.year, self.month, event_day).weekday()
                    if wd == 1:
                        hold_porifa_var = self.optimizer.porifa_tuesday_vars.get(event_day)
                    elif wd == 4:
                        hold_porifa_var = self.optimizer.porifa_friday_vars.get(event_day)

                target_day = event_day - rule['offset_days']
                if target_day < 1:
                    continue

                violation_pairs = []
                for other_staff in self.staff.index:
                    if staff == other_staff:
                        continue
                    pair_var = self.optimizer.get_oncall_pair(
                        staff, other_staff, target_day
                    )
                    if pair_var is not None:
                        violation_pairs.append(pair_var)

                if not violation_pairs:
                    continue

                if holiday_check == 'porifa' and hold_porifa_var is not None:
                    # ポリファ開催日かつ当直違反がある場合のみペナルティ
                    penalty_var = self.model.NewBoolVar(
                        f"{rule['penalty_prefix']}_{staff}_{event_day}"
                    )
                    violation_count = self.model.NewIntVar(
                        0,
                        len(violation_pairs),
                        f"{rule['penalty_prefix']}_count_{staff}_{event_day}"
                    )
                    has_violation = self.model.NewBoolVar(
                        f"{rule['penalty_prefix']}_has_{staff}_{event_day}"
                    )
                    self.model.Add(violation_count == sum(violation_pairs))
                    self.model.Add(violation_count >= 1).OnlyEnforceIf(has_violation)
                    self.model.Add(violation_count == 0).OnlyEnforceIf(has_violation.Not())

                    self.model.Add(penalty_var == 1).OnlyEnforceIf([hold_porifa_var, has_violation])
                    self.model.Add(penalty_var == 0).OnlyEnforceIf(hold_porifa_var.Not())
                    self.model.Add(penalty_var == 0).OnlyEnforceIf(has_violation.Not())
                    penalties.append(penalty_var)
                else:
                    penalty_var = self.model.NewBoolVar(
                        f"{rule['penalty_prefix']}_{staff}_{event_day}"
                    )
                    violation_count = self.model.NewIntVar(
                        0,
                        len(violation_pairs),
                        f"{rule['penalty_prefix']}_count_{staff}_{event_day}"
                    )
                    self.model.Add(violation_count == sum(violation_pairs))
                    self.model.Add(violation_count >= 1).OnlyEnforceIf(penalty_var)
                    self.model.Add(violation_count == 0).OnlyEnforceIf(penalty_var.Not())
                    penalties.append(penalty_var)


        return penalties

    @staticmethod
    def _has_required_floor(floor_values, required_floors):
        """欠損値を真偽値評価せず、対象床を含むか判定する。"""
        for floor in floor_values:
            if pd.isna(floor):
                continue
            if floor in required_floors:
                return True
        return False
    
    
            
    #第三金曜日臨床薬剤課会議のため対象者が明けにならないように設定（ソフト制約）
    def friday_rinsho(self):
        """
        ソフト制約
        - 第三金曜日は臨床薬剤課会議のため、対象者（主任以上かつFloor 1-8）が当直明けにならないようにする
        - 当直明け = 前日（第三金曜日 - 1）に当直を割り当てない
        - meeting_constraints.fixed_medical_safety_working_group と同じ対象者条件で統一
        （Floor 9:外来・Floor 10:部長・Floor 6:化療 を除外）
        """
        return self._build_soft_oncall_penalties('friday_rinsho')

    #第三金曜日臨床薬剤課会議の前々日当直のため対象者が当直を避ける（ソフト制約）
    def friday_rinsho_prev(self):   
        """
        ソフト制約
        - 第三金曜日の前々日は臨床薬剤課会議のため、対象者（主任以上かつFloor 1-8）が当直を避ける
        - meeting_constraints.fixed_medical_safety_working_group と同じ対象者条件で統一
        （Floor 9:外来・Floor 10:部長・Floor 6:化療 を除外）
        """
        return self._build_soft_oncall_penalties('friday_rinsho_prev')
    
    def add_oncall_palliative_constraints(self):
        """
        ソフト制約
        - 緩和ケア回診担当者の前日の当直を避ける
        - 回診日は毎週月曜日と木曜日、火曜日
        """
        return self._build_soft_oncall_penalties('palliative')

    def add_oncall_palliative_prev_constraints(self):
        """
        ソフト制約
        - 緩和ケア回診担当者の前々日の当直を避ける
        - 回診日は毎週月曜日と木曜日
        """
        return self._build_soft_oncall_penalties('palliative_prev')
    
    def add_oncall_second_friday_constraints(self):
        """
        ソフト制約
        - 第二金曜日の病棟担当者カンファレンスのため、対象者（主任以上かつFloor 2または13）が当直明けにならないようにする
        - 当直明け = 前日（第二金曜日 - 1）に当直を割り当てない
        """
        return self._build_soft_oncall_penalties('second_friday_conference')
    
    def add_oncall_second_friday_prev_constraints(self):
        """
        ソフト制約
        - 第二金曜日の病棟担当者カンファレンスの前々日の当直を避ける
        - 対象者（主任以上かつFloor 2または13）が当直を避ける
        """
        return self._build_soft_oncall_penalties('second_friday_conference_prev')
    
    def add_oncall_safety_wg_constraints(self):
        """
        ソフト制約
        - 医療安全WGのため、対象者（医薬品安全使用WG==TRUE）が当直明けにならないようにする
        - 当直明け = 前日（医療安全WGの日 - 1）に当直を割り当てない
        """
        return self._build_soft_oncall_penalties('safety_wg')

    def add_oncall_safety_wg_prev_constraints(self):
        """
        ソフト制約
        - 医療安全WGの前々日の当直を避ける
        - 対象者（医薬品安全使用WG==TRUE）が当直を避ける
        """
        return self._build_soft_oncall_penalties('safety_wg_prev')
    
    def add_oncall_porifa_constraints(self):
        """
        ソフト制約
        - PORIFAのため、対象者（主任以上かつFloor 1-8）が当直明けにならないようにする
        - 当直明け = 前日（PORIFAの日 - 1）に当直を割り当てない
        """
        return self._build_soft_oncall_penalties('porifa')
    
    def add_oncall_porifa_prev_constraints(self):
        """
        ソフト制約
        - PORIFAの前々日の当直を避ける
        - 対象者（主任以上かつFloor 1-8）が当直を避ける
        """
        return self._build_soft_oncall_penalties('porifa_prev')
    
    def add_oncall_exective_meeting_constraints(self):
        """
        ソフト制約
        - 役職者会議のため、対象者（主任以上かつFloor 1-8）が当直明けにならないようにする
        - 当直明け = 前日（役職者会議の日 - 1）に当直を割り当てない
        """
        return self._build_soft_oncall_penalties('exective_meeting')
    
    def add_oncall_exective_meeting_prev_constraints(self):
        """
        ソフト制約
        - 役職者会議の前々日の当直を避ける
        - 対象者（主任以上かつFloor 1-8）が当直を避ける
        """
        return self._build_soft_oncall_penalties('exective_meeting_prev')
    
    def add_oncall_dementia_round_constraints(self):
        """
        ソフト制約
        - 認知症せん妄ラウンドのため、対象者（認知症せん妄ラウンド==TRUE)が当直明けにならないようにする
        - 当直明け = 前日（認知症せん妄ラウンドの日 - 1）に当直を割り当てない
        """
        return self._build_soft_oncall_penalties('dementia_round')
    
    def add_oncall_dementia_round_prev_constraints(self):
        """
        ソフト制約
        - 認知症せん妄ラウンドの前々日の当直を避ける
        - 対象者（認知症せん妄ラウンド==TRUE)が当直を避ける
        """
        return self._build_soft_oncall_penalties('dementia_round_prev')
    
    def add_oncall_am_shift_prev_constraints(self):
        """
        ソフト制約
        - 午前出勤希望者の前々日の当直を避ける
        - 対象者（午前出勤希望者==AM出：hopelist:9）が当直を避ける
        """
        return self._build_soft_oncall_penalties('am_shift_prev')
    
    def add_oncall_pm_shift_prev_constraints(self):
        """
        ソフト制約
        - 午後出勤希望者の前々日の当直を避ける
        - 対象者（午後出勤希望者==PM出：hopelist:10）が当直を避ける
        """
        return self._build_soft_oncall_penalties('pm_shift_prev')
    
    def add_oncall_training_prev_constraints(self):
        """
        ソフト制約
        - 研修の前々日の当直を避ける
        - 対象者（研修==TRUE)が当直を避ける
        """
        return self._build_soft_oncall_penalties('training_prev')

    def add_oncall_conference_prev_constraints(self):
        """
        ソフト制約
        - 学会の前々日の当直を避ける
        - 対象者（学会==TRUE)が当直を避ける
        """
        return self._build_soft_oncall_penalties('conference_prev')
    
    #7.当直は同性のスタッフで構成
    def add_oncall_paring_constraints(self):
        """
        当直のペアリング設定,ハード制約
        - 同性のスタッフで構成
        """
        print("当直のペアリング設定（同性）を適用します。") 
        for day in range(1,self.days +1):
            for staff1 in self.staff.index:
                for staff2 in self.staff.index:
                    if staff1 != staff2:
                        #性別が異なる場合、当直ペアを禁止
                        if self.staff.loc[staff1,'Sex'] != self.staff.loc[staff2,'Sex']:
                            pair_var = self.optimizer.get_oncall_pair(staff1, staff2, day)
                            if pair_var is not None:
                                self.model.Add(pair_var == 0)
    
    def oncall_paring_floor(self)    :
        """
        当直のペアリング設定,ハード制約
        - なるべく同じフロアのスタッフでの組み合わせは避ける
        - 外来の組み合わせを避けるのはほぼハード制約
        """
        print("当直のペアリング設定（同フロア避ける）を適用します。")
        floor_penalties = []
        for day in range(1,self.days +1):
            for i, staff1 in enumerate(self.staff.index):
                for staff2 in self.staff.index[i+1:]:
                    pair_var = self.optimizer.get_oncall_pair(staff1, staff2, day)
                    if pair_var is None:
                        continue

                    #同フロア同士でのペアリングは避ける（ハード制約）
                    if self.staff.loc[staff1,'Floor'] == self.staff.loc[staff2,'Floor']:
                        self.model.Add(pair_var == 0)
    
    def add_oncall_paring_role_constaints(self):
        """役職者どうしのペアリングは避ける"""
        print("当直のペアリング設定（役職者避ける）を適用します。")
        penalties = []
        for day in range(1,self.days +1):
            for staff1 in self.staff.index:
                for staff2 in self.staff.index:
                    if staff1 != staff2:
                        #主任ペアが成立した場合にペナルティを発生させる
                        if (self.staff.loc[staff1,'主任以上']==True) and (self.staff.loc[staff2,'主任以上']==True):
                            pair_var = self.optimizer.get_oncall_pair(staff1, staff2, day)
                            if pair_var is not None:
                                penalty_var = self.model.NewBoolVar(f'oncall_role_penalty_{staff1}_{staff2}_{day}')
                                self.model.Add(penalty_var == pair_var)
                                penalties.append(penalty_var)
        return penalties

    def add_oncall_paring_sync_constraints(self):
        """同期のペアリングは避ける"""
        print("当直のペアリング設定（同期避ける）を適用します。")
        penalties = []
        for day in range(1,self.days +1):
            for i, staff1 in enumerate(self.staff.index):
                for staff2 in self.staff.index[i+1:]:
                        if self.staff.loc[staff1,'同期変数'] != self.staff.loc[staff2,'同期変数']:
                            continue
                        
                        pair_var = self.optimizer.get_oncall_pair(staff1, staff2, day)
                        if pair_var is None:
                            continue
                        
                        #同期ペアが成立した場合にペナルティを発生させる
                        penalty_var = self.model.NewBoolVar(
                            f'oncall_sync_penalty_{staff1}_{staff2}_{day}')
                        self.model.Add(penalty_var == pair_var)
                        penalties.append(penalty_var)
                        
        return penalties
    
    #8.前回の当直から次回の当直までは最低7日間空ける
    def add_oncall_spacing_constraints(self):
        """
        当直の間隔に関する制約
        - スタッフにつき、前回から次回の当直までは最低７日間空ける
        - 前月シフト参照、今月１日から７日までは前月シフト参照
        - 前月の当直シフトがあればそこから7日以上は空ける
        - 1日なら前月最終日の7日前〜最終日までを参照
        - 7日なら前月最終日と今月の1〜6日までを考慮
        - 外来スタッフは希望通りなので、この当直間隔を適用しない
        - 非外来スタッフにおいて、当直希望を2回、または1回（主任以上のみ）場合、当直間隔制約を考慮しなくて良い
        """
        print("当直の間隔に関する制約を適用します")
        prev_oncall_dict = getattr(
            self.optimizer,
            'prev_month_oncall_staff_by_day',
            getattr(self.optimizer, 'prev_month_oncall_staff_ids', {}),
        )
        
        
        for staff in self.staff.index:
            #当直不可または休職中のスタッフはスキップ
            if self.staff.loc[staff,'当直']==False:
                continue
            if self.staff.loc[staff,'休職']==True:
                continue
            #外来スタッフは希望通りなので、当直間隔制約を適用しない
            #TODO:_get_eligigate　の希望取得方法に変更
            if self.staff.loc[staff,'Floor']=="外来":
                continue
                
            # 前月の当直履歴を考慮し、当月1〜7日の当直を制限する。
            #　前回当直から7日以上空けるので、取得情報は前月8日分とする
            if prev_oncall_dict:
                last_prev_day = max(prev_oncall_dict)

                for day in range(1, min(8, self.days + 1)):
                    previous_days = (
                        prev_oncall_dict.get(previous_day, [])
                        for previous_day in range(
                            last_prev_day - (8 - day), last_prev_day + 1
                        )#前8日分のシフト情報を取得
                    )
                    was_oncall = any(staff in staff_ids for staff_ids in previous_days)

                    if was_oncall:
                        for other_staff in self.staff.index:
                            if staff == other_staff:
                                continue
                            pair_var = self.optimizer.get_oncall_pair(
                                staff, other_staff, day
                            )
                            if pair_var is not None:
                                self.model.Add(pair_var == 0)
                                
            for day in range(1,self.days +1):
                #day日当直の場合、day+1からday+7までは当直にしない
                oncall_on_day = self.model.NewBoolVar(f'staff_{staff}_oncall_day_{day}_for_spacing')
                
                #day日に当直に入っているかを判定
                oncall_pairs = []
                for other_staff in self.staff.index:
                    if staff != other_staff:
                        pair_var = self.optimizer.get_oncall_pair(staff, other_staff, day)
                        if pair_var is not None:
                            oncall_pairs.append(pair_var)
                #いずれかのペアに入っていればoncall_on_dayは1
                if oncall_pairs:
                    self.model.Add(sum(oncall_pairs) >=1).OnlyEnforceIf(oncall_on_day)
                    self.model.Add(sum(oncall_pairs) ==0).OnlyEnforceIf(oncall_on_day.Not())
                    
                #day日に当直に入っている場合、次の7日間は当直にしない
                    for offset in range(1,min(8,self.days -day +1)): # 1日から7日までの範囲でループ
                        next_day = day +offset
                        
                        if next_day <= self.days:
                            next_oncall_pairs = []
                            for other_staff in self.staff.index:
                                if staff != other_staff:
                                    pair_var = self.optimizer.get_oncall_pair(staff, other_staff, next_day)
                                    if pair_var is not None:
                                        next_oncall_pairs.append(pair_var)
                            if next_oncall_pairs:
                                #day日に当直に入っている場合、next_day日は当直にしない
                                self.model.Add(sum(next_oncall_pairs) == 0).OnlyEnforceIf(oncall_on_day)
                            
    
    def _validate_oncall_requests(self):
        """
        事前検証：当直希望と制約の競合をチェック
        不成立の要件があれば処理を中止して、エラーメッセージを表示して停止
        """
        print("\n===== 当直希望の事前検証 =====")
        issues_found = False
        
        # 各スタッフの希望回数を集計
        staff_request_counts = {}
        staff_request_days = {}
        daily_requests = {}
        
        for staff in self.staff.index:
            if self.staff.loc[staff,'当直']==False or self.staff.loc[staff,'休職']==True:
                continue
            
            staff_requests = self.hope_list.loc[staff]
            request_count = sum(
                1 for day in range(1, self.days + 1)
                if self._hope_matches(self._get_hope_value(staff, day, default=7), {8})
            )
            
            if request_count > 0:
                staff_request_counts[staff] = request_count
                staff_request_days[staff] = []
                
                # 日別の希望者をリスト化
                for day in range(1, self.days + 1):
                    if self._hope_matches(self._get_hope_value(staff, day, default=7), {8}):
                        staff_request_days[staff].append(day)
                        if day not in daily_requests:
                            daily_requests[day] = []
                        daily_requests[day].append(staff)
        # 日別の希望者リストを作成完了
        active_staff = [
            staff
            for staff in self.staff.index
            if bool(self.staff.loc[staff, '当直'])
            and not bool(self.staff.loc[staff, '休職'])
        ]
        # 月間の当直枠の計算
        monthly_slot_capacity = sum(
            1
            if self.staff.loc[staff, 'Floor'] == 9
            or bool(self.staff.loc[staff, '主任以上'])
            else 2
            for staff in active_staff
        )
        # 必要当直枠の計算
        required_oncall_slots = self.days * 2
        print(
            "[当直希望候補ログ] "
            f"有効スタッフ数={len(active_staff)}, "
            f"月間必要枠={required_oncall_slots}, "
            f"月間上限合計={monthly_slot_capacity}"
        )
        # 月間の当直枠と必要枠の比較結果をログ出力
        if monthly_slot_capacity < required_oncall_slots:
            print(
                "[当直希望候補不足] 月間上限合計が必要枠を下回っています。"
                f"不足={required_oncall_slots - monthly_slot_capacity}枠"
            )
        for day, staff_list in sorted(daily_requests.items()):
            print(f"[当直希望日] day={day}, 希望者={staff_list}")
        
        # 1. 月回数上限との競合チェック
        print("\n1. 月回数上限との競合チェック:")
        for staff, count in staff_request_counts.items():
            #月の当直希望上限回数を判定
            is_monthly_limited = (
                self.staff.loc[staff, 'Floor'] == 9
                or bool(self.staff.loc[staff, '主任以上'])
            )
            max_count = 1 if is_monthly_limited else 2
            
            if count > max_count:
                issues_found = True
                limit_label = "外来・役職者" if is_monthly_limited else "通常スタッフ"
                raise ValueError(f"スタッフ{staff}の希望回数が上限を超えています: 希望{count}回 > 上限{max_count}回")
        
        if not any(count > (1 if (
                    self.staff.loc[s, 'Floor'] == 9
                    or bool(self.staff.loc[s, '主任以上'])
                ) else 2)
                for s, count in staff_request_counts.items()):
            print("  ✓ 問題なし")
        
        # 2. 同日の希望者数チェック
        print("\n2. 同日の希望者数チェック:")
        days_with_no_requests = []
        days_with_excess_requests = []
        # 日別の希望者数チェックの初期化
        for day in range(1, self.days + 1):
            request_count = len(daily_requests.get(day, []))
            if request_count == 0:
                days_with_no_requests.append(day)
            elif request_count > 2:
                days_with_excess_requests.append((day, daily_requests[day]))
                raise ValueError(f"{day}日の希望者が多すぎます: {request_count}人 > 上限2人")
        
        if days_with_no_requests:
            print(f"  ℹ️  希望者なし（自動割り当て対象）: {len(days_with_no_requests)}日")
            if len(days_with_no_requests) <= 5:
                print(f"     日付: {days_with_no_requests}")
        else:
            print("  ✓ 全日に希望者あり")
        
        # 2.3同日の当直希望が同フロアの場合には競合として扱う
        for day, staff_list in daily_requests.items():
            if len(staff_list) >= 2:
                floors = [self.staff.loc[staff, 'Floor'] for staff in staff_list]
                if len(set(floors)) != len(floors):
                    raise ValueError(
                        f"{day}日の当直希望者に同一フロアのスタッフがいます。希望を見直してください。: {staff_list}"
                    )

        # 2.3.1　TODO:々の日の希望が同じ少数の相手候補に集中するなど、複数日の相互依存まで判定したい

        # 2.4当直希望が同日に3人以上の場合は不成立として止める
        if days_with_excess_requests:
            issues_found = True
            print(f"  ⚠️ 希望過剰日（3人以上）: {len(days_with_excess_requests)}日")
            for day, staff_list in days_with_excess_requests[:3]:  # 最初の3日を表示
                print(f"     {day}日: {len(staff_list)}人 - {staff_list[:5]}")
            raise ValueError(f"当直希望が同日に3人以上のため不成立です。希望を見直してください。: {len(days_with_excess_requests)}日")
        else:
            print("  ✓ 希望過剰日なし")
        
        # 2.5 同性ペアリングチェック
        print("\n2.5. 同性ペアリングチェック:")
        gender_conflicts = []
        for day, staff_list in daily_requests.items():
            if len(staff_list) >= 2:
                genders = [self.staff.loc[s, 'Sex'] for s in staff_list]
                if len(set(genders)) > 1:
                    gender_conflicts.append((day, staff_list))
                    raise ValueError(f"{day}日の当直ペアが異性混在しています: {genders}")
        
        if gender_conflicts:
            issues_found = True
            print(f"  ⚠️ 異性混在日: {len(gender_conflicts)}日")
            for day, staff_list in gender_conflicts[:3]:
                genders = [f"{s}({self.staff.loc[s, 'Sex']})" for s in staff_list]
                print(f"     {day}日: {genders}")
        else:
            print("  ✓ 問題なし")

        # 2.6 同日希望者の同一フロア競合
        print("\n2.6. 同日希望者の同一フロア競合チェック:")
        for day, staff_list in daily_requests.items():
            if len(staff_list) >= 2:
                floors = [self.staff.loc[staff, 'Floor'] for staff in staff_list]
                if len(set(floors)) != len(floors):
                    raise ValueError(
                        f"{day}日の当直希望者に同一フロアのスタッフがいます: {staff_list}"
                    )

        # 同一スタッフの希望日同士も、当直間隔制約と両立するか確認
        for staff, request_days in staff_request_days.items():
            if self.staff.loc[staff, 'Floor'] == "外来":
                continue
            for previous_day, next_day in zip(request_days, request_days[1:]):
                if next_day - previous_day <= 7:
                    raise ValueError(
                        f"スタッフ{staff}の当直希望日が7日以内に重なり、"
                        f"当直間隔制約と両立しません: {previous_day}日、{next_day}日"
                    )

        # 前月の当直履歴により当月1〜7日の当直が禁止される競合を確認
        previous_oncall_by_day = getattr(
            self.optimizer, 'prev_month_oncall_staff_by_day', {}
        )
        if previous_oncall_by_day:
            last_previous_day = max(previous_oncall_by_day)
            for staff, request_days in staff_request_days.items():
                for day in request_days:
                    if day > 7:
                        continue
                    previous_days = range(
                        last_previous_day - (8 - day), last_previous_day + 1
                    )
                    if any(
                        staff in previous_oncall_by_day.get(previous_day, [])
                        for previous_day in previous_days
                    ):
                        raise ValueError(
                            f"スタッフ{staff}の{day}日当直希望が前月の当直履歴と"
                            "当直間隔制約に抵触します"
                        )

        # 希望者が1人の日に、ハード制約を満たせるペア相手がいるか確認
        for day, staff_list in daily_requests.items():
            if len(staff_list) != 1:
                continue

            requester = staff_list[0]#
            next_day = day + 1
            if next_day <= self.days and self._hope_matches(
                self._get_hope_value(requester, next_day, default=7),
                {0, 1, 3, 5, 6, 9, 10, 11},
            ):
                print(
                    f"[当直希望候補] day={day}, 希望者={requester}, 候補数=0, "
                    f"除外理由={{'本人の翌日希望': 1}}"
                )
                continue


            eligible_partners = []
            exclusion_counts = {}
            exclusion_examples = []
            for partner in self.staff.index:
                if partner == requester:
                    continue

                reasons = []
                if not bool(self.staff.loc[partner, '当直']):#当直FALSEの場合は除外
                    reasons.append('当直不可')
                if bool(self.staff.loc[partner, '休職']):#休職　TRUEの場合は除外
                    reasons.append('休職中')
                if self.staff.loc[requester, 'Sex'] != self.staff.loc[partner, 'Sex']:
                    reasons.append('異性')
                if self.staff.loc[requester, 'Floor'] == self.staff.loc[partner, 'Floor']:
                    reasons.append('同一フロア')

                partner_hope = self._get_hope_value(partner, day, default=7)
                if self._hope_matches(partner_hope, {0, 2, 3, 5, 6, 11}):
                    reasons.append('当日の希望で当直不可')

                next_day = day + 1
                if next_day <= self.days and self._hope_matches(
                    self._get_hope_value(partner, next_day, default=7),
                    {0, 1, 3,4, 5, 6,8, 9, 10,11,12,13,14,15},
                ):
                    reasons.append('翌日の希望で前日当直不可')

                partner_max_count = (
                    1
                    if self.staff.loc[partner, 'Floor'] == 9
                    or bool(self.staff.loc[partner, '主任以上'])
                    else 2
                )
                if staff_request_counts.get(partner, 0) >= partner_max_count:
                    reasons.append('当直希望で月上限到達')
                partner_has_spacing_rule = (
                    self.staff.loc[partner, 'Floor'] != "外来"
                )
                if partner_has_spacing_rule and any(
                    abs(request_day - day) <= 7
                    for request_day in staff_request_days.get(partner, [])
                ):
                    reasons.append('当直希望との7日間隔')

                has_recent_previous_oncall = False
                if (
                    partner_has_spacing_rule
                    and previous_oncall_by_day
                    and day <= 7
                ):
                    last_previous_day = max(previous_oncall_by_day)
                    previous_days = range(
                        last_previous_day - (8 - day), last_previous_day + 1
                    )
                    has_recent_previous_oncall = any(
                        partner in previous_oncall_by_day.get(previous_day, [])
                        for previous_day in previous_days
                    )
                if has_recent_previous_oncall:
                    reasons.append('前月当直履歴との間隔')

                if reasons:
                    for reason in set(reasons):
                        exclusion_counts[reason] = exclusion_counts.get(reason, 0) + 1
                    if len(exclusion_examples) < 10:
                        exclusion_examples.append(f"{partner}: {', '.join(reasons)}")
                    continue

                eligible_partners.append(partner)

            print(
                f"[当直希望候補] day={day}, 希望者={requester}, "
                f"候補数={len(eligible_partners)}, 候補={eligible_partners}, "
                f"除外理由別件数(重複あり)={exclusion_counts}, "
                f"除外例={exclusion_examples}"
            )

            if not eligible_partners:
                raise ValueError(
                    f"スタッフ{requester}の{day}日当直希望を満たせる相手候補がいません。"
                    f"除外理由={exclusion_counts}; 除外例={exclusion_examples}"
                )
        
        # 4. 役職者ペアリングチェック
        print("\n4. 役職者ペアリングチェック:")
        role_conflicts = []
        for day, staff_list in daily_requests.items():
            if len(staff_list) >= 2:
                roles = [self.staff.loc[s, '主任以上'] for s in staff_list]
                if sum(roles) >= 2:
                    role_conflicts.append((day, staff_list))
        
        if role_conflicts:
            print(f"  ⚠️ 主任以上同士のペア（ソフト制約）: {len(role_conflicts)}日")
            for day, staff_list in role_conflicts[:3]:
                roles = [f"{s}(役職)" if self.staff.loc[s, '主任以上'] else s for s in staff_list]
                print(f"     {day}日: {roles}")
        else:
            print("  ✓ 問題なし")
        
        # 当直希望翌日の希望が、当直の前日ブロック制約と衝突するか確認
        blocking_hope_labels = {
            0: "休み",
            1: "出勤",
            3: "育休",
            5: "慶弔休暇",
            6: "研修",
            9: "午前出勤",
            10: "午後出勤",
            11: "学会",
        }
        # 当直希望翌日のブロック対象希望ラベルをセット化
        blocked_next_day_hopes = set(blocking_hope_labels)
        for staff in self.staff.index:
            if self.staff.loc[staff,'当直']==False or self.staff.loc[staff,'休職']==True:
                continue
            for day in range(1,self.days+1):
                if self._hope_matches(self._get_hope_value(staff, day, default=7), {8}):  # 当直希望日
                    next_day = day + 1
                    if next_day <= self.days:
                        next_day_hope = self._get_hope_value(staff, next_day, default=7)
                        if self._hope_matches(next_day_hope, blocked_next_day_hopes):
                            # 当直希望翌日の希望がブロック対象に含まれている場合はエラーを発生させる
                            hope_value = next(
                                value for value in blocking_hope_labels
                                if self._hope_matches(next_day_hope, {value})
                            )
                            raise ValueError(
                                f"スタッフ{staff}の{day}日当直希望が翌日の"
                                f"{blocking_hope_labels[hope_value]}希望と衝突します"
                            )
        
        if days_with_excess_requests:
            # 当直希望が同日に3人以上ある場合の詳細を作成
            details = "; ".join(
                f"{day}日:{len(staff_list)}人({','.join(map(str,staff_list))})"
                for day,staff_list in days_with_excess_requests
        )
            raise ValueError(
                f"当直希望が同日に3人以上あるため処理を中止します: {details}"
            )
        # 前月末データ参照、前月末に当直があり、1日に出勤希望がある際は成立不可として止める
        # 当直明けの制約と競合するため
        conflicts = []
        for staff in self.prev_month_oncall_staff_ids:
            if staff not in self.staff.index:
                continue
            hope_value = self._get_hope_value(staff,1,default=7)
            if self._hope_matches(hope_value, {1, 9, 10}):
                conflicts.append(staff)
        if conflicts:
            raise ValueError(
                f"スタッフ{', '.join(map(str, conflicts))}は前月末に当直があり、1日に出勤希望があるため成立不可です\n"
                + "希望を見直してください。"
            )
        #通常日の配置不可、日曜・祝日の勤務不可、休暇希望、当直明けの理由t実際に集計される日を突き合わせる。
        #特に上限　self.dayoffrequest_day に対してハード制約で固定される非出勤が何日あるかを確認
        self._validate_joint_oncall_requests()
        self._validate_monthly_oncall_feasibility()
        print("\n" + "="*40)
        if issues_found:
            print("⚠️  警告：競合が検出されました。解が見つからない可能性があります。")
        else:
            print("✓ 事前検証完了：重大な競合は検出されませんでした。")
        return daily_requests  # 後続処理で使用するため返す

    def _get_hard_compatible_oncall_pairs(self, enforced_request_days=None):
        """日ごとに、局所的なハード条件を満たすスタッフペアを列挙する。"""
        # ハード条件を満たす当直ペアを日ごとに列挙する
        active_staff = [
            staff
            for staff in self.staff.index
            if self._is_enabled_value(self.staff.loc[staff, '当直'])
            and not self._is_enabled_value(self.staff.loc[staff, '休職'])
        ]
        # 日別の当直希望者リストを作成
        request_days_by_staff = {staff: [] for staff in active_staff}
        requests_by_day = {}
        enforced_request_days = (
            None
            if enforced_request_days is None
            else set(enforced_request_days)
        )
        for staff in active_staff:
            for day in range(1, self.days + 1):
                if (
                    self._hope_matches(self._get_hope_value(staff, day, default=7), {8})
                    and (
                        enforced_request_days is None
                        or day in enforced_request_days
                    )
                ):
                    # 当直希望がある場合は日別リストに追加
                    request_days_by_staff[staff].append(day)
                    requests_by_day.setdefault(day, []).append(staff)

        previous_oncall_by_day = getattr(
            self.optimizer, 'prev_month_oncall_staff_by_day', {}
        )
        pairs_by_day = {}
        for day in range(1, self.days + 1):
            pairs = []
            for first_index, staff1 in enumerate(active_staff):
                for staff2 in active_staff[first_index + 1:]:
                    if self.staff.loc[staff1, 'Sex'] != self.staff.loc[staff2, 'Sex']:
                        continue
                    if self.staff.loc[staff1, 'Floor'] == self.staff.loc[staff2, 'Floor']:
                        continue

                    pair_is_allowed = True
                    for staff in (staff1, staff2):
                        hope_today = self._get_hope_value(staff, day, default=7)
                        if self._hope_matches(hope_today, {0, 2, 3, 5, 6, 11}):
                            pair_is_allowed = False
                            break

                        next_day = day + 1
                        if next_day <= self.days and self._hope_matches(
                            self._get_hope_value(staff, next_day, default=7),
                            {0, 1, 3, 5, 6, 9, 10, 11},
                        ):
                            pair_is_allowed = False
                            break

                        max_monthly_oncalls = (
                            1
                            if self.staff.loc[staff, 'Floor'] == 9
                            or self._is_enabled_value(self.staff.loc[staff, '主任以上'])
                            else 2
                        )
                        staff_request_days = request_days_by_staff[staff]
                        if (
                            day not in staff_request_days
                            and len(staff_request_days) >= max_monthly_oncalls
                        ):
                            pair_is_allowed = False
                            break
                        has_spacing_rule = (
                            self.staff.loc[staff, 'Floor'] != "外来"
                        )
                        if has_spacing_rule and any(
                            request_day != day and abs(request_day - day) <= 7
                            for request_day in staff_request_days
                        ):
                            pair_is_allowed = False
                            break

                        if has_spacing_rule and previous_oncall_by_day and day <= 7:
                            last_previous_day = max(previous_oncall_by_day)
                            previous_days = range(
                                last_previous_day - (8 - day), last_previous_day + 1
                            )
                            if any(
                                staff in previous_oncall_by_day.get(previous_day, [])
                                for previous_day in previous_days
                            ):
                                pair_is_allowed = False
                                break

                    if pair_is_allowed:
                        pairs.append((staff1, staff2))
            pairs_by_day[day] = pairs

        return active_staff, requests_by_day, pairs_by_day

    def _build_joint_request_model(
        self,
        active_staff,
        requests_by_day,
        pairs_by_day,
        request_days=None,
        assign_every_day=False,
        require_regular_staff_once=False,
    ):
        """希望日または月全体について、当直ペアの割当条件を検査する。"""
        model = cp_model.CpModel()
        selected_by_staff = {staff: [] for staff in active_staff}
        requested_days = sorted(requests_by_day if request_days is None else request_days)
        assignment_days = (
            range(1, self.days + 1)
            if assign_every_day
            else requested_days
        )

        for day in assignment_days:
            requested_staff = (
                set(requests_by_day.get(day, []))
                if day in requested_days
                else set()
            )
            day_vars = []
            for pair_index, pair in enumerate(pairs_by_day[day]):
                if not requested_staff.issubset(pair):
                    continue
                pair_var = model.NewBoolVar(f'request_pair_{day}_{pair_index}')
                day_vars.append(pair_var)
                for staff in pair:
                    selected_by_staff[staff].append((day, pair_var))
            model.Add(sum(day_vars) == 1)

        for staff in active_staff:
            max_monthly_oncalls = (
                1
                if self.staff.loc[staff, 'Floor'] == 9
                or self._is_enabled_value(self.staff.loc[staff, '主任以上'])
                else 2
            )
            staff_assignments = selected_by_staff[staff]
            monthly_count = sum(var for _, var in staff_assignments)
            model.Add(monthly_count <= max_monthly_oncalls)
            is_monthly_limited = (
                self.staff.loc[staff, 'Floor'] == 9
                or self._is_enabled_value(self.staff.loc[staff, '主任以上'])
            )
            if require_regular_staff_once and not is_monthly_limited:
                model.Add(monthly_count >= 1)

            staff_assignments.sort(key=lambda item: item[0])
            if self.staff.loc[staff, 'Floor'] != "外来":
                for index, (day1, var1) in enumerate(staff_assignments):
                    for day2, var2 in staff_assignments[index + 1:]:
                        if day2 - day1 > 7:
                            break
                        model.Add(var1 + var2 <= 1)

        return model, selected_by_staff

    def _validate_joint_oncall_requests(self):
        """希望日ごとの候補を月回数・当直間隔も含めて同時に検証する。"""
        active_staff, requests_by_day, pairs_by_day = (
            self._get_hard_compatible_oncall_pairs()
        )
        print("\n===== 当直ハード制約後の候補診断 =====")
        for day in range(1, self.days + 1):
            print(
                f"[局所ハード条件後ペア数] day={day}, "
                f"count={len(pairs_by_day[day])}"
            )

        model, selected_by_staff = self._build_joint_request_model(
            active_staff,
            requests_by_day,
            pairs_by_day,
        )
        solver = cp_model.CpSolver()
        status = solver.Solve(model)
        print(
            "[当直希望同時割当] "
            f"status={solver.StatusName(status)}, "
            f"希望日={sorted(requests_by_day)}"
        )
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            selected_pairs = []
            for staff, assignments in selected_by_staff.items():
                for day, var in assignments:
                    if solver.Value(var):
                        selected_pairs.append((day, staff))
            selected_by_day = {}
            for day, staff in selected_pairs:
                selected_by_day.setdefault(day, []).append(staff)
            print(f"[当直希望同時割当例] {selected_by_day}")
            return

        if status != cp_model.INFEASIBLE:
            print(
                "[当直希望同時割当] 事前検証では可否を確定できませんでした。"
                "本モデルの最適化で判定します。"
            )
            return

        conflict_days = sorted(requests_by_day)
        for day in list(conflict_days):
            trial_days = [candidate_day for candidate_day in conflict_days if candidate_day != day]
            trial_model, _ = self._build_joint_request_model(
                active_staff,#アクティブスタッフ
                requests_by_day,#希望日ごとのリクエスト
                pairs_by_day,
                request_days=trial_days,
            )
            trial_solver = cp_model.CpSolver()
            trial_status = trial_solver.Solve(trial_model)
            if trial_status == cp_model.INFEASIBLE:
                conflict_days.remove(day)
        conflict_details = "; ".join(
            f"{day}日:{requests_by_day[day]}"
            for day in conflict_days
        )
        raise ValueError(
            "当直希望を同時に満たせません。"
            f"競合日候補={conflict_details or sorted(requests_by_day)}。"
            "希望者間で月回数上限または7日間隔が競合しています。"
        )

    def _validate_monthly_oncall_feasibility(self):
        """
        希望のない日も含め、月全体で当直を割り当てられるか検証する。
        """
        active_staff, _, base_pairs_by_day = (
            self._get_hard_compatible_oncall_pairs(enforced_request_days=set())
        )
        empty_candidate_days = [
            day
            for day, pairs in base_pairs_by_day.items()
            if not pairs
        ]
        print("\n===== 月全体の当直割当可能性チェック =====")
        for day, pairs in base_pairs_by_day.items():
            print(f"[当直候補ペア数] day={day}, count={len(pairs)}")

        base_model, _ = self._build_joint_request_model(
            active_staff,
            {},
            base_pairs_by_day,
            request_days=set(),
            assign_every_day=True,
            require_regular_staff_once=True,
        )
        base_solver = cp_model.CpSolver()
        base_solver.parameters.max_time_in_seconds = 10.0
        base_status = base_solver.Solve(base_model)
        print(f"[希望を除く月全体の当直割当] status={base_solver.StatusName(base_status)}")
        if base_status == cp_model.INFEASIBLE:
            if empty_candidate_days:
                reason = f"候補ペアがない日={empty_candidate_days}"
            else:
                reason = (
                    "毎日1ペア、通常スタッフ月1回以上、月間回数上限、"
                    "当直間隔を同時に満たせません"
                )
            raise ValueError(
                f"当直希望を除いても月全体に当直を割り当てられません: {reason}"
            )
        if base_status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            print(
                "[希望を除く月全体の当直割当] 事前検証では可否を確定できませんでした。"
                "本モデルの最適化で判定します。"
            )
            return

        _, requests_by_day, pairs_by_day = self._get_hard_compatible_oncall_pairs()
        request_model, _ = self._build_joint_request_model(
            active_staff,
            requests_by_day,
            pairs_by_day,
            assign_every_day=True,
            require_regular_staff_once=True,
        )
        request_solver = cp_model.CpSolver()
        request_solver.parameters.max_time_in_seconds = 10.0
        request_status = request_solver.Solve(request_model)
        print(
            "[当直希望を含む月全体の割当] "
            f"status={request_solver.StatusName(request_status)}"
        )
        if request_status == cp_model.INFEASIBLE:
            request_details = "; ".join(
                f"{day}日:{staff_list}"
                for day, staff_list in sorted(requests_by_day.items())
            )
            raise ValueError(
                "当直希望を含めると月全体の当直を割り当てられません。"
                f"希望日と希望者={request_details or 'なし'}"
            )
        if request_status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            print(
                "[当直希望を含む月全体の割当] 事前検証では可否を確定できませんでした。"
                "本モデルの最適化で判定します。"
            )
            return

        print("[当直希望を含む月全体の割当] 実行可能な割当が見つかりました。")
        
    def _add_hard_oncall_request_constraints(self):
        """
        当直希望のハード制約
        希望値8のスタッフを希望日の当直ペアに必ず含める。
        """
        request_count = 0
        for staff in self.staff.index:
            if '当直' in self.staff.columns and not bool(self.staff.loc[staff, '当直']):
                continue
            if '休職' in self.staff.columns and bool(self.staff.loc[staff, '休職']):
                continue

            for day in range(1, self.days + 1):
                if not self._hope_matches(self._get_hope_value(staff, day, default=7), {8}):
                    continue

                pair_vars = [
                    pair_var
                    for other_staff in self.staff.index
                    if staff != other_staff
                    if (pair_var := self.optimizer.get_oncall_pair(staff, other_staff, day)) is not None
                ]
                self.model.Add(sum(pair_vars) >= 1)
                request_count += 1
                print(f"  スタッフ{staff}の{day}日の当直希望をハード制約として適用します。")

        print(f"  当直希望ハード制約: {request_count}件")
        return request_count

    def apply_oncall_requests(self):
        """当直希望をハード制約として適用する。"""
        return self._add_hard_oncall_request_constraints()

    
    #なるべく叶える制約の重みづけを行う
    def apply_weighted_objective(self):
        """
        重みづけした目的関数を設定
        - 同フロアの当直ペア制約をハード制約として適用
        - 役職者同士の当直を避けるペナルティ
        - 同期同士の当直を避けるペナルティ
        - 当直回数の偏りを抑える公平性ペナルティ
        - 前月回数に応じた今月回数の目標ペナルティ
        - 月2回制約のペナルティ
        - 薬審の前日の当直ペナルティ
        - 第三金曜日臨床薬剤課会議の前日・前々日当直ペナルティ
        - 緩和回診参加者の前日・前々日当直ペナルティ
        - 第二金曜日病棟担当者カンファレンスの前日・前々日当直ペナルティ
        - 医療安全WGの前日・前々日当直ペナルティ
        - ポリファの前日・前々日当直ペナルティ
        - 研修希望の前々日当直ペナルティ
        - 学会の前々日当直ペナルティ
        """
        #同フロアの当直ペア制約を適用　ハード制約
        self.oncall_paring_floor()
        #役職者同士の当直を避けるペナルティを取得
        executive_penalties = self.add_oncall_paring_role_constaints()
        # 同期同士の当直を避けるペナルティを取得
        sync_penalties = self.add_oncall_paring_sync_constraints()
        # 当直回数の偏り（max-min）を抑える公平性ペナルティ
        fairness_penalties = self.add_oncall_fairness_penalties()
        # 前月回数に応じた今月回数の目標は、実行可能性を保つためソフト制約にする
        prev_month_balance_penalties = self.add_oncall_prev_month_balance_penalties()
        two_per_month_history_penalties = (
            self.add_oncall_two_per_month_history_penalties()
        )
        #薬審の前日の当直ペナルティを取得
        yakushin_nextday = self.yakushin_nextday()
        #第三金曜日臨床薬剤課会議の前日当直ペナルティを取得
        friday_rinsho_penalties = self.friday_rinsho()
        #第三金曜日臨床薬剤課会議の前々日当直ペナルティ
        friday_rinsho_prev_penalties = self.friday_rinsho_prev()
        #緩和回診参加者の前日当直ペナルティを取得
        kanwa_penalties = self.add_oncall_palliative_constraints()
        #緩和回診参加者の前々日当直ペナルティを取得
        kanwa_prev_penalties = self.add_oncall_palliative_prev_constraints()
        #第二金曜日病棟担当者カンファレンスの前日当直ペナルティを取得
        second_friday_penalties = self.add_oncall_second_friday_constraints()
        #第二金曜日病棟担当者カンファレンスの前々日当直ペナルティを取得
        second_friday_prev_penalties = self.add_oncall_second_friday_prev_constraints()
        #医療安全WGの前日当直ペナルティを取得
        safety_wg_penalties = self.add_oncall_safety_wg_constraints()
        #医療安全WGの前々日当直ペナルティを取得
        safety_wg_prev_penalties = self.add_oncall_safety_wg_prev_constraints()
        #ポリファの前日当直ペナルティを取得
        porifa_penalties = self.add_oncall_porifa_constraints()
        #ポリファの前々日当直ペナルティを取得
        porifa_prev_penalties = self.add_oncall_porifa_prev_constraints()
        #役職者会議の前日当直ペナルティを取得
        exective_meeting_penalties = self.add_oncall_exective_meeting_constraints()
        #役職者会議の前々日当直ペナルティを取得
        exective_meeting_prev_penalties = self.add_oncall_exective_meeting_prev_constraints()
        #認知症せん妄ラウンドの前日当直ペナルティを取得
        dementia_round_penalties = self.add_oncall_dementia_round_constraints()
        #認知症せん妄ラウンドの前々日当直ペナルティを取得
        dementia_round_prev_penalties = self.add_oncall_dementia_round_prev_constraints()   
        #午前出勤希望者の前々日当直ペナルティを取得
        am_shift_prev_penalties = self.add_oncall_am_shift_prev_constraints()
        #午後出勤希望者の前々日当直ペナルティを取得
        pm_shift_prev_penalties = self.add_oncall_pm_shift_prev_constraints()
        #研修の前々日当直ペナルティを取得
        training_prev_penalties = self.add_oncall_training_prev_constraints()
        #学会の前々日当直ペナルティを取得
        conference_prev_penalties = self.add_oncall_conference_prev_constraints()
        
        if self.month in [12, 1]:
            #12月または1月シフト作成時にのみ有効
            #前年12/30 の当直ペナルティを取得
            #前年12/30に出勤した人から今年の当直者を選ぶことを避けるペナルティ変数
            previous_year_december_30_penalties = [
                oncall_var
                for (staff1, staff2, day), oncall_var in self.night_shifts.items()
                if day == 30
                and self.month == 12
                and (
                    staff1 in self.previous_year_december_30_staff
                    or staff2 in self.previous_year_december_30_staff
                )
            ]
            #前年12/31に出勤
            previous_december_31_penalties = [
                oncall_var
                for (staff1, staff2, day), oncall_var in self.night_shifts.items()
                if day == 31
                and self.month == 12
                and (
                    staff1 in self.previous_december_31_staff
                    or staff2 in self.previous_december_31_staff
                )
            ]
            
            #前年1/1の当直ペナルティを取得
            #前年1/1に出勤した人から今年の当直者を選ぶことを避けるペナルティ変数
            previous_january_1_penalties = [
                oncall_var
                for (staff1, staff2, day), oncall_var in self.night_shifts.items()
                if day == 1
                and self.month == 1
                and (
                    staff1 in self.previous_january_1_staff
                    or staff2 in self.previous_january_1_staff
                )
            ]
            
            #前年1/2の当直ペナルティを取得
            previous_january_2_penalties = [
                oncall_var
                for (staff1, staff2, day), oncall_var in self.night_shifts.items()
                if day == 2
                and self.month == 1
                and (
                    staff1 in self.previous_january_2_staff
                    or staff2 in self.previous_january_2_staff
                )
            ]
            #前年1/3の当直ペナルティを取得
            #1月シフト作成の時にのみ有効
            previous_january_3_penalties = [
                oncall_var
                for (staff1, staff2, day), oncall_var in self.night_shifts.items()
                if day == 3
                and self.month == 1
                and (
                    staff1 in self.previous_january_3_staff
                    or staff2 in self.previous_january_3_staff
                )
            ]
        
        #重みづけ
        WEIGHT_EXECUTIVE_PAIR = self._soft_oncall_rule_configs['executive_pair']['weight']  # 役職者同士の当直ペアリングを避ける重み
        WEIGHT_SYNC = self._soft_oncall_rule_configs['sync']['weight']  # 同期ペアリングを避ける重み
        WEIGHT_SECOND_FRIDAY = self._soft_oncall_rule_configs['second_friday_conference']['weight']#
        WEIGHT_SECOND_FRIDAY_PREV = self._soft_oncall_rule_configs['second_friday_conference_prev']['weight']
        WEIGHT_FAIRNESS = 20  # 当直回数の偏りを抑える公平性ペナルティの重み
        WEIGHT_YAKUSHIN_NEXTDAY = 8  # 薬審の前日の当直ペナルティ
        WEIGHT_RINSHO_FRIDAY = self._soft_oncall_rule_configs['friday_rinsho']['weight']
        WEIGHT_RINSHO_FRIDAY_PREV = self._soft_oncall_rule_configs['friday_rinsho_prev']['weight']
        WEIGHT_KANWA = self._soft_oncall_rule_configs['palliative']['weight']
        WEIGHT_KANWA_PREV = self._soft_oncall_rule_configs['palliative_prev']['weight']
        WEIGHT_SAFETY_WG = self._soft_oncall_rule_configs['safety_wg']['weight']
        WEIGHT_SAFETY_WG_PREV = self._soft_oncall_rule_configs['safety_wg_prev']['weight']
        WEIGHT_PORIFA = self._soft_oncall_rule_configs['porifa']['weight']
        WEIGHT_PORIFA_PREV = self._soft_oncall_rule_configs['porifa_prev']['weight']
        WEIGHT_EXECTIVE_MEETING = self._soft_oncall_rule_configs['exective_meeting']['weight']
        WEIGHT_EXECTIVE_MEETING_PREV = self._soft_oncall_rule_configs['exective_meeting_prev']['weight']
        WEIGHT_DEMENTIA_ROUND = self._soft_oncall_rule_configs['dementia_round']['weight']
        WEIGHT_DEMENTIA_ROUND_PREV = self._soft_oncall_rule_configs['dementia_round_prev']['weight']
        WEIGHT_AMSHIFT_PREV = self._soft_oncall_rule_configs['am_shift_prev']['weight']
        WEIGHT_PMSHIFT_PREV = self._soft_oncall_rule_configs['pm_shift_prev']['weight']
        WEIGHT_TRAINING_PREV = self._soft_oncall_rule_configs['training_prev']['weight']
        WEIGHT_CONFERENCE_PREV = self._soft_oncall_rule_configs['conference_prev']['weight']

        #結合した目的関数
        total_penalty = (
            WEIGHT_EXECUTIVE_PAIR * sum(executive_penalties) +
            WEIGHT_FAIRNESS * sum(fairness_penalties) +
            WEIGHT_ONCALL_PREV_MONTH_BALANCE * sum(prev_month_balance_penalties) +
            WEIGHT_ONCALL_TWO_PER_MONTH_HISTORY * sum(two_per_month_history_penalties) +
            WEIGHT_SYNC * sum(sync_penalties) +
            WEIGHT_YAKUSHIN_NEXTDAY * sum(yakushin_nextday) +
            WEIGHT_RINSHO_FRIDAY * sum(friday_rinsho_penalties) +
            WEIGHT_RINSHO_FRIDAY_PREV * sum(friday_rinsho_prev_penalties)+
            WEIGHT_KANWA * sum(kanwa_penalties)+
            WEIGHT_KANWA_PREV * sum(kanwa_prev_penalties)+
            WEIGHT_SECOND_FRIDAY * sum(second_friday_penalties) +
            WEIGHT_SECOND_FRIDAY_PREV * sum(second_friday_prev_penalties) +
            WEIGHT_SAFETY_WG * sum(safety_wg_penalties) +
            WEIGHT_SAFETY_WG_PREV * sum(safety_wg_prev_penalties) +
            WEIGHT_PORIFA * sum(porifa_penalties) +
            WEIGHT_PORIFA_PREV * sum(porifa_prev_penalties) +
            WEIGHT_EXECTIVE_MEETING * sum(exective_meeting_penalties) +
            WEIGHT_EXECTIVE_MEETING_PREV * sum(exective_meeting_prev_penalties) +
            WEIGHT_DEMENTIA_ROUND * sum(dementia_round_penalties) +
            WEIGHT_DEMENTIA_ROUND_PREV * sum(dementia_round_prev_penalties)+
            WEIGHT_PORIFA_PREV * sum(porifa_prev_penalties)+
            WEIGHT_EXECTIVE_MEETING * sum(exective_meeting_penalties) +
            WEIGHT_EXECTIVE_MEETING_PREV * sum(exective_meeting_prev_penalties) +
            WEIGHT_EXECTIVE_MEETING * sum(exective_meeting_penalties) +
            WEIGHT_EXECTIVE_MEETING_PREV * sum(exective_meeting_prev_penalties) +
            WEIGHT_DEMENTIA_ROUND * sum(dementia_round_penalties) +
            WEIGHT_DEMENTIA_ROUND_PREV * sum(dementia_round_prev_penalties) +
            WEIGHT_AMSHIFT_PREV * sum(am_shift_prev_penalties) +
            WEIGHT_PMSHIFT_PREV * sum(pm_shift_prev_penalties) +
            WEIGHT_TRAINING_PREV * sum(training_prev_penalties) +
            WEIGHT_CONFERENCE_PREV * sum(conference_prev_penalties)
        )
        if self.month in[12,1]:
            total_penalty = (total_penalty+
                            WEIGHT_PREVIOUS_YEAR_DECEMBER_30_AVOIDANCE* sum(previous_year_december_30_penalties)+
                            WEIGHT_PREVIOUS_DECEMBER_31_AVOIDANCE* sum(previous_december_31_penalties)+
                            WEIGHT_PREVIOUS_JANUARY_1_AVOIDANCE* sum(previous_january_1_penalties)+
                            WEIGHT_PREVIOUS_JANUARY_2_AVOIDANCE* sum(previous_january_2_penalties)+
                            WEIGHT_PREVIOUS_JANUARY_3_AVOIDANCE* sum(previous_january_3_penalties)
                            )

        print(f"  目的関数構成:")
        print(f"    - 役職者同士の当直ペアリング回避ペナルティ: {len(executive_penalties)}個 (重み={WEIGHT_EXECUTIVE_PAIR})")
        print(f"    - 公平性ペナルティ: {len(fairness_penalties)}個 (重み={WEIGHT_FAIRNESS})")
        print(f"    - 前月回数バランスペナルティ: {len(prev_month_balance_penalties)}個 (重み={WEIGHT_ONCALL_PREV_MONTH_BALANCE})")
        print(f"    - 月2回当直履歴ペナルティ: {len(two_per_month_history_penalties)}個 (重み={WEIGHT_ONCALL_TWO_PER_MONTH_HISTORY})")
        print(f"    - 薯審の前日当直回避ペナルティ: {len(yakushin_nextday)}個 (重み={WEIGHT_YAKUSHIN_NEXTDAY})")
        print(f"    - 第三金曜会議前日当直回避ペナルティ: {len(friday_rinsho_penalties)}個 (重み={WEIGHT_RINSHO_FRIDAY})")
        print(f"    - 第三金曜会議前々日当直回避ペナルティ: {len(friday_rinsho_prev_penalties)}個 (重み={WEIGHT_RINSHO_FRIDAY_PREV})")
        print(f"    - 緩和回診前日当直回避ペナルティ: {len(kanwa_penalties)}個 (重み={WEIGHT_KANWA})")
        print(f"    - 緩和回診前々日当直回避ペナルティ: {len(kanwa_prev_penalties)}個 (重み={WEIGHT_KANWA_PREV})")
        print(f"    - 第二金曜会議前日当直回避ペナルティ: {len(second_friday_penalties)}個 (重み={WEIGHT_SECOND_FRIDAY})")
        print(f"    - 第二金曜会議前々日当直回避ペナルティ: {len(second_friday_prev_penalties)}個 (重み={WEIGHT_SECOND_FRIDAY_PREV})")
        print(f"    - 医療安全WG前日当直回避ペナルティ: {len(safety_wg_penalties)}個 (重み={WEIGHT_SAFETY_WG})")
        print(f"    - 医療安全WG前々日当直回避ペナルティ: {len(safety_wg_prev_penalties)}個 (重み={WEIGHT_SAFETY_WG_PREV})")
        print(f"    - PORIFA前日当直回避ペナルティ: {len(porifa_penalties)}個 (重み={WEIGHT_PORIFA})")
        print(f"    - PORIFA前々日当直回避ペナルティ: {len(porifa_prev_penalties)}個 (重み={WEIGHT_PORIFA_PREV})")
        print(f"    - 役職者会議の前日当直回避ペナルティ: {len(exective_meeting_penalties)}個 (重み={WEIGHT_EXECTIVE_MEETING})")
        print(f"    - 役職者会議の前々日当直回避ペナルティ: {len(exective_meeting_prev_penalties)}個 (重み={WEIGHT_EXECTIVE_MEETING_PREV})")
        print(f"    - 認知症せん妄ラウンド前日当直回避ペナルティ: {len(dementia_round_penalties)}個 (重み={WEIGHT_DEMENTIA_ROUND})")
        print(f"    - 認知症せん妄ラウンド前々日当直回避ペナルティ: {len(dementia_round_prev_penalties)}個 (重み={WEIGHT_DEMENTIA_ROUND_PREV})")
        print(f"  合計ペナルティ: {total_penalty}")
        self.optimizer.register_objective_term("oncall_constraints", total_penalty)

    def add_oncall_prev_month_balance_penalties(self):
        """
        前月当直回数に応じた今月回数の目標からの差を返す
        - 前月1回のスタッフは今月2回を目標とする
        - 前月2回以上のスタッフは今月1回を目標とする
        - 主任以上・外来・当直FALSEは対象外
        """
        gairai_section_id = 16
        penalties = []
        previous_month_counts = getattr(self.optimizer, 'previous_month_oncall_counts', {})
        for staff, monthly_count in self.monthly_oncall_counts.items():
            if bool(self.staff.loc[staff, '主任以上']):
                continue
            if gairai_section_id in self.get_eligible_sections.get(staff, []):
                continue
            if not bool(self.staff.loc[staff, '当直']):
                continue

            previous_count = previous_month_counts.get(staff, 0)
            print(f"スタッフ: {staff}, 前月当直回数: {previous_count}, 今月当直回数: {monthly_count}")
            if previous_count == 1:
                target_count = 2
            elif previous_count >= 2:
                target_count = 1
            else:
                continue

            penalty = self.model.NewIntVar(
                0,
                2,
                f'previous_month_balance_penalty_{staff}',
            )
            self.model.Add(penalty >= monthly_count - target_count)
            self.model.Add(penalty >= target_count - monthly_count)
            penalties.append(penalty)

        return penalties

    def add_oncall_two_per_month_history_penalties(self):
        """前月2回以上のスタッフ間で、過去に月2回だった人を避ける。"""
        gairai_section_id = 16#外来の専属業務ID
        penalties = []
        previous_month_counts = getattr(
            self.optimizer, 'previous_month_oncall_counts', {}
        )#過去数ヶ月の月1回当直履歴を取得
        two_per_month_history = getattr(
            self.optimizer, 'previous_months_with_two_oncalls', {}
        )# 過去数か月の月2回当直履歴を取得

        for staff, monthly_count in self.monthly_oncall_counts.items():
            if bool(self.staff.loc[staff, '主任以上']):#主任以上を除外
                continue
            if gairai_section_id in self.get_eligible_sections.get(staff, []):#読み込んだスタッフ条件（作成したい今月）に基づいて、外来所属スタッフを除外
                continue
            if not bool(self.staff.loc[staff, '当直']):#当直不可のスタッフを除外
                continue
            if previous_month_counts.get(staff, 0) < 2:#前月の当直回数が2回未満の場合はスキップ
                continue

            history_count = int(two_per_month_history.get(staff, 0))
            if history_count <= 0:# 過去に月2回の履歴がない場合はスキップ
                continue
            
            #月2回当直が割り当てられたかを表すブール変数
            assigned_twice = self.model.NewBoolVar(
                f'oncall_assigned_twice_{staff}'
            )
            self.model.Add(monthly_count == 2).OnlyEnforceIf(assigned_twice)
            self.model.Add(monthly_count != 2).OnlyEnforceIf(assigned_twice.Not())
            penalties.append(history_count * assigned_twice)# 過去に月2回の履歴がある場合のペナルティを追加

        return penalties

    def add_oncall_fairness_penalties(self):
        """
        主任以上・外来・当直FALSEを除くスタッフの履歴込み
        外来判定は_get_eligible_sectionに由来する
        当直回数の max-min を最小化する。
        """
        gairai_section_id = 16#外来の専属業務ID
        penalties = []
        eligible_staff = [
            staff
            for staff in self.monthly_oncall_counts
            if not bool(self.staff.loc[staff, '主任以上']) 
            and gairai_section_id not in self.get_eligible_sections.get(staff,[])
            and bool(self.staff.loc[staff, '当直'])  # 当直FALSEを除く
        ]
        print(f"主任以上を除く当直回数公平性計算対象のスタッフ: {eligible_staff}")

        if len(eligible_staff) <= 1:
            print("当直公平性ペナルティ: 対象者不足のためスキップ")
            return penalties

        previous_counts = {
            staff: int(self.optimizer.previous_oncall_counts.get(staff, 0))
            for staff in eligible_staff
        }
        print(f"前月までの当直回数: {previous_counts}")
        total_oncall_count_vars = []
        for staff in eligible_staff:
            previous_count = previous_counts[staff]
            total_count = self.model.NewIntVar(
                previous_count,
                previous_count + 2,
                f'oncall_total_count_{staff}',
            )
            self.model.Add(
                total_count == previous_count + self.monthly_oncall_counts[staff]
            )
            total_oncall_count_vars.append(total_count)

        max_possible_count = max(previous_counts.values()) + 2
        min_possible_count = min(previous_counts.values())
        max_oncall_count = self.model.NewIntVar(
            min_possible_count, max_possible_count, 'oncall_max_total_count'
        )
        min_oncall_count = self.model.NewIntVar(
            min_possible_count, max_possible_count, 'oncall_min_total_count'
        )
        spread_oncall_count = self.model.NewIntVar(
            0, max_possible_count - min_possible_count, 'oncall_total_spread'
        )

        self.model.AddMaxEquality(max_oncall_count, total_oncall_count_vars)
        self.model.AddMinEquality(min_oncall_count, total_oncall_count_vars)
        self.model.Add(spread_oncall_count == max_oncall_count - min_oncall_count)
        penalties.append(spread_oncall_count)

        return penalties
        
    #他の仕事による当直制約の追加