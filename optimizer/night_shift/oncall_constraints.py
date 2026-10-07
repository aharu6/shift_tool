from optimizer.base_constraint import BaseConstraint
from datetime import datetime
import pandas as pd
from config.objective_weights import (
    WEIGHT_PREVIOUS_YEAR_DECEMBER_30_AVOIDANCE,
    WEIGHT_PREVIOUS_DECEMBER_31_AVOIDANCE,
    WEIGHT_PREVIOUS_JANUARY_1_AVOIDANCE,
    WEIGHT_PREVIOUS_JANUARY_2_AVOIDANCE,
    WEIGHT_PREVIOUS_JANUARY_3_AVOIDANCE,
    WEIGHT_ONCALL_PREV_MONTH_BALANCE,
)
class OncallConstraints(BaseConstraint):
    """当直に関する制約条件を定義するクラス"""
    def __init__(self, model,optimizer):
        super().__init__(model, optimizer)
        # 月累計当直回数を追跡する変数（公平性判断に使用）
        self.monthly_oncall_counts = {}
        self._soft_oncall_rule_configs = {
            'executive_pair':{
                'weight':10,
            },
            'sync':{
                'weight':5,
            },
            'safety_wg':{
                'start_message':'医薬品安全使用WGのため、対象者が当直明けにならないように設定します',
                'missing_event_message':'第四金曜日が存在しないためスキップします',
                'event_type':'fourth_friday',
                'offset_days':1,
                'print_fourth_friday':True,
                'check_negative_offset':True,
                'negative_offset_message':'第四金曜日が1日のため前日が存在しません。スキップします。',
                'staff_attr':'医薬品安全使用WG',
                'require_floor_any':None,
                'holiday_check':'fourth_friday',
                'active_staff_message':'医薬品安全使用WGのため、第四金曜日前日の当直をなるべく避けます。',
                'penalty_prefix':'oncall_before_safety_wg_penalty',
                'weight':8,
                
                },
            'safety_wg_prev':{
                'start_message':'医薬品安全使用WGの前々日当直のため、対象者が当直を避けるように設定します',
                'missing_event_message':'第四金曜日が存在しないためスキップします',
                'event_type':'fourth_friday',
                'offset_days':2,
                'print_fourth_friday':False,
                'check_negative_offset':True,
                'negative_offset_message':'第四金曜日の前々日が存在しないためスキップします。',
                'staff_attr':'医薬品安全使用WG',
                'require_floor_any':None,
                'holiday_check':'fourth_friday',
                'active_staff_message':'医薬品安全使用WGのため、第四金曜日前々日の当直をなるべく避けます。',
                'penalty_prefix':'oncall_before_safety_wg_prev_penalty',
                'weight':1,
                },
            'second_friday_conference':{
                'start_message':'第二金曜日の病棟担当者カンファレンスのため、対象者が当直明けにならないように設定します',
                'missing_event_message':'第二金曜日が存在しないためスキップします',
                'event_type':'second_friday',
                'offset_days':1,
                'print_second_friday':True,
                'check_negative_offset':True,
                'negative_offset_message':'第二金曜日が1日のため前日が存在しません。スキップします。',
                'staff_attr':'主任以上',
                'require_floor_any':[2,13],# floor DI、課長
                'holiday_check':'second_friday',
                'active_staff_message':'病棟担当者カンファレンスのため、第二金曜日前日の当直をなるべく避けます。',
                'penalty_prefix':'oncall_before_second_friday_penalty',
                'weight':8,
            },
            'second_friday_conference_prev':{
                'start_message':'第二金曜日の病棟担当者カンファレンスの前々日当直のため、対象者が当直を避けるように設定します',
                'missing_event_message':'第二金曜日が存在しないためスキップします',
                'event_type':'second_friday',
                'offset_days':2,
                'print_second_friday':False,
                'check_negative_offset':True,
                'negative_offset_message':'第二金曜日の前々日が存在しないためスキップします。',
                'staff_attr':'主任以上',
                'non_target_message':'主任以上ではないため、第二金曜日前々日の当直回避制約の対象外です。',
                'require_floor_any':[2,13],# floor DI、課長
                'holiday_check':'second_friday',
                'active_staff_message':'病棟担当者カンファレンスのため、第二金曜日前々日の当直をなるべく避けます。',
                'penalty_prefix':'oncall_before_second_friday_prev_penalty',
                'weight':1,
            },
            'friday_rinsho': {
                'start_message': '第三金曜日の臨床薬剤課会議のため、対象者が当直明けにならないように設定します。',
                'missing_event_message': '第三金曜日が存在しないためスキップします。',
                'event_type': 'third_friday',
                'offset_days': 1,
                'print_third_friday': True,
                'check_negative_offset': True,
                'negative_offset_message': '第三金曜日が1日のため前日が存在しません。スキップします。',
                'staff_attr': '主任以上',
                'require_floor_any': [1, 2, 3, 4, 5],#floor 1-5F
                'holiday_check': 'third_friday',
                'active_staff_message': '臨床薬剤課会議のため、第三金曜日前日の当直をなるべく避けます。',
                'penalty_prefix': 'oncall_before_rinsho_friday_penalty',
                'weight': 8,
            },
            'friday_rinsho_prev': {
                'start_message': '第三金曜日臨床薬剤課会議の前々日当直のため、対象者が当直を避けるように設定します。',
                'missing_event_message': '第三金曜日が存在しないためスキップします。',
                'event_type': 'third_friday',
                'offset_days': 2,
                'print_third_friday': False,
                'check_negative_offset': True,
                'negative_offset_message': '第三金曜日の前々日が存在しないためスキップします。',
                'staff_attr': '主任以上',
                'non_target_message': '主任以上ではないため、第三金曜日前々日の当直回避制約の対象外です。',
                'require_floor_any': [1, 2, 3, 4, 5],
                'holiday_check': 'third_friday',
                'active_staff_message': '臨床薬剤課会議のため、第三金曜日前々日の当直をなるべく避けます。',
                'penalty_prefix': 'oncall_before_rinsho_friday_prev_penalty',
                'weight': 1,
            },
            'palliative': {
                'start_message': '緩和ケア回診担当者前日の当直を避ける制約を適用します。',
                'event_type': 'monday_tuesday_thursday',
                'offset_days': 1,
                'staff_attr': '緩和回診',
                'holiday_check': 'event_days',
                'holiday_skip_message': '緩和ケア回診担当者ですが、回診日に休み希望があるためスキップします。',
                'active_staff_message': '緩和ケア回診担当者のため、前日の当直をなるべく避けます。',
                'penalty_prefix': 'oncall_palliative_penalty',
                'weight': 10,
            },
            'palliative_prev': {
                'start_message': '緩和ケア回診担当者前々日の当直を避ける制約を適用します。',
                'event_type': 'monday_tuesday_thursday',
                'offset_days': 2,
                'staff_attr': '緩和回診',
                'holiday_check': 'event_days',
                'holiday_skip_message': '緩和ケア回診担当者ですが、回診日に休み希望があるためスキップします。',
                'active_staff_message': '緩和ケア回診担当者のため、前々日の当直をなるべく避けます。',
                'penalty_prefix': 'oncall_palliative_prev_penalty',
                'weight': 3,
            },
            'porifa':{
                'start_message':'ポリファーマシー担当者開催日前日の当直を避ける制約を追記します(制約を追記するのは選択された火曜と金曜のみとします)',
                'event_type':'porifa',
                'offset_days':1,
                'staff_attr':'ポリファーマシーチーム',
                'holiday_check':'porifa',
                'active_staff_message':'ポリファーマシー担当者のため、開催日前日の当直をなるべく避けます。',
                'penalty_prefix':'oncall_porifa_penalty',
                'weight':10,
            },
            'porifa_prev':{
                'start_message':'ポリファーマシー担当者開催日前々日の当直を避ける制約を追記します(制約を追記するのは選択された火曜と金曜のみとします)',
                'event_type':'porifa',
                'offset_days':2,
                'staff_attr':'ポリファーマシーチーム',
                'holiday_check':'porifa',
                'active_staff_message':'ポリファーマシー担当者のため、開催日前々日の当直をなるべく避けます。',
                'penalty_prefix':'oncall_porifa_prev_penalty',
                'weight':3,
            },
            'exective_meeting':{
                'start_message':'役職者会議の前日の当直を避ける制約を追記します',
                'event_type':'exective_meeting',
                'offset_days':1,
                'staff_attr':'主任以上',
                'holiday_check':'exective_meeting',
                'active_staff_message':'役職者会議のため、前日の当直をなるべく避けます。',
                'penalty_prefix':'oncall_exective_meeting_penalty',
                'weight':3,
            },
            'exective_meeting_prev':{
                'start_message':'役職者会議の前々日の当直を避ける制約を追記します',
                'event_type':'exective_meeting',
                'offset_days':2,
                'staff_attr':'主任以上',
                'holiday_check':'exective_meeting',
                'active_staff_message':'役職者会議のため、前々日の当直をなるべく避けます。',
                'penalty_prefix':'oncall_exective_meeting_prev_penalty',
                'weight':1,
            },
            'dementia_round':{
                'start_message':'認知症せん妄ラウンドの前日の当直を避ける制約を追記します',
                'event_type':'dementia_round',
                'offset_days':1,
                'staff_attr':'認知症せん妄ラウンド',
                'holiday_check':'dementia_round',
                'active_staff_message':'認知症せん妄ラウンドのため、前日の当直をなるべく避けます。',
                'penalty_prefix':'oncall_dementia_round_penalty',
                'weight':3,
            },
            'dementia_round_prev':{
                'start_message':'認知症せん妄ラウンドの前々日の当直を避ける制約を追記します',
                'event_type':'dementia_round',
                'offset_days':2,
                'staff_attr':'認知症せん妄ラウンド',
                'holiday_check':'dementia_round',
                'active_staff_message':'認知症せん妄ラウンドのため、前々日の当直をなるべく避けます。',
                'penalty_prefix':'oncall_dementia_round_prev_penalty',
                'weight':1,
            },
            'pm_shift_prev':{
                'start_message':'午後出勤希望の前々日の当直を避ける制約を追記します。前日の当直を避ける制約はハード制約にて別に定義されています。',
                'event_type':'pm_shift',
                'offset_days':2,
                'staff_attr':None,
                'staff_hope':10,#PM出：10（hope_list)
                'holiday_check':'pm_shift',
                'active_staff_message':'午後出勤希望のため、前々日の当直をなるべく避けます。',
                'penalty_prefix':'oncall_pm_shift_prev_penalty',
                'weight':1,
            },
            'am_shift_prev':{
                'start_message':'午前出勤希望の前々日の当直を避ける制約を追記します。前日の当直を避ける制約はハード制約にて別に定義されています。',
                'event_type':'am_shift',
                'offset_days':2,
                'staff_attr':None,
                'staff_hope':9,#AM出：9（hope_list)
                'holiday_check':'am_shift',
                'active_staff_message':'午前出勤希望のため、前々日の当直をなるべく避けます。',
                'penalty_prefix':'oncall_am_shift_prev_penalty',
                'weight':1,
            }
        }
        self.sync_penalties = self.add_oncall_paring_sync_constraints()
        
    def apply(self):
        # 制約の適用順序を変更：除外制約を先に適用してから、毎日の確保を行う
        self.add_oncall_constraints()#当直の基本制約（希望リストによる除外など）
        self._validate_oncall_requests()#事前検証：希望と制約の競合チェック
        self.apply_oncall_requests()#当直希望を叶える
        self.add_oncall_paring_constraints()#同性でペアリング
        self.add_oncall_spacing_constraints()#前回の当直から次回の当直までは最低7日間空ける    
        self.add_daily_oncall()#毎日の当直確保
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
                            print(f"スタッフ{staff}の{day}日の午前出勤希望の前日({day-1})を避けます。")
                    if self._hope_matches(hope_value, {10}):#午後出勤希望の前日は当直を避ける
                        if day -1 >=1:
                            staff_PM_days.append(day -1)#午後出勤希望の前日を避ける
                            print(f"スタッフ{staff}の{day}日の午後出勤希望の前日({day-1})を避けます。")
                            
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
                            
                #外来部門、役職者の当直は月1回まで
                if (self.staff.loc[staff,'Floor'] in [9,10]) and (self.staff.loc[staff,'主任以上']==True):
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
                
                else:
                    #月2回までの制約
                    for day in range(1,self.days +1):
                        for other_staff in self.staff.index:
                            if staff != other_staff:
                                pair_var = self.optimizer.get_oncall_pair(staff, other_staff, day)
                                if pair_var is not None:
                                    total_oncalls.append(pair_var)
                            
                    #月1回以上、2回までの制約を追加
                    if total_oncalls:  # リストが空でない場合のみ制約追加
                        # 一時的に月1回以上の制約をコメントアウト（解が見つかるか確認）
                        # self.model.Add(sum(total_oncalls)>=1)
                        self.model.Add(sum(total_oncalls)<=2)
                        print(f"  スタッフ{staff}: 当直ペア変数{len(total_oncalls)}個を設定（月0-2回）")
                        
                        # 月累計当直回数の追跡変数を作成（公平性判断に使用）
                        monthly_count = self.model.NewIntVar(0, 2, f'monthly_oncall_count_{staff}')
                        self.model.Add(monthly_count == sum(total_oncalls))
                        self.monthly_oncall_counts[staff] = monthly_count

    
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

        # pm_shiftはスタッフごとに希望日が異なるため_build_soft_oncall_penalties内で個別処理する
        return None, []
    
    def _build_pm_am_shift_penalties(self, rule,type,penalties,hope_value):
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
            self._build_pm_am_shift_penalties(rule = rule,type='am_shift',penalties=penalties,hope_value={9})
            return penalties
        
        if rule.get('event_type')=='pm_shift':
            self._build_pm_am_shift_penalties(rule = rule,type='pm_shift',penalties=penalties,hope_value={10})
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
            elif holiday_check == 'event_days':
                if any(
                    self._hope_matches(self._get_hope_value(staff, event_day, default=7), {0})
                    for event_day in event_days
                ):
                    holiday_skip_message = rule.get('holiday_skip_message')
                    if holiday_skip_message:
                        print(f"{staff}さんは{holiday_skip_message}")
                    continue

            print(f"{staff}さんは{rule['active_staff_message']}")
            for event_day in event_days:
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
        当直のペアリング設定,ソフト制約
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

                    #同フロア同士でのペアリングは避ける（ソフト制約）
                    penalty_var = self.model.NewBoolVar(f'oncall_floor_penalty_{staff1}_{staff2}_{day}')
                    floor_penalties.append(penalty_var)

                    # 違反フラグを当直ペア結果に一致させる
                    self.model.Add(penalty_var == pair_var)
        return floor_penalties
    
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
        """事前検証：当直希望と制約の競合をチェック"""
        print("\n===== 当直希望の事前検証 =====")
        issues_found = False
        
        # 各スタッフの希望回数を集計
        staff_request_counts = {}
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
                
                # 日別の希望者をリスト化
                for day in range(1, self.days + 1):
                    if self._hope_matches(self._get_hope_value(staff, day, default=7), {8}):
                        if day not in daily_requests:
                            daily_requests[day] = []
                        daily_requests[day].append(staff)
        
        # 1. 月回数上限との競合チェック
        print("\n1. 月回数上限との競合チェック:")
        for staff, count in staff_request_counts.items():
            is_role = (self.staff.loc[staff,'Floor'] in [9,10]) and (self.staff.loc[staff,'主任以上']==True)
            max_count = 1 if is_role else 2
            
            if count > max_count:
                issues_found = True
                role_label = "役職者・外来" if is_role else "通常スタッフ"
                print(f"  ⚠️ スタッフ{staff}（{role_label}）: 希望{count}回 > 上限{max_count}回")
        
        if not any(count > (1 if (self.staff.loc[s,'Floor'] in [9,10]) and (self.staff.loc[s,'主任以上']==True) else 2) 
                for s, count in staff_request_counts.items()):
            print("  ✓ 問題なし")
        
        # 2. 同日の希望者数チェック
        print("\n2. 同日の希望者数チェック:")
        days_with_no_requests = []
        days_with_excess_requests = []
        
        for day in range(1, self.days + 1):
            request_count = len(daily_requests.get(day, []))
            if request_count == 0:
                days_with_no_requests.append(day)
            elif request_count > 2:
                days_with_excess_requests.append((day, daily_requests[day]))
        
        if days_with_no_requests:
            print(f"  ℹ️  希望者なし（自動割り当て対象）: {len(days_with_no_requests)}日")
            if len(days_with_no_requests) <= 5:
                print(f"     日付: {days_with_no_requests}")
        else:
            print("  ✓ 全日に希望者あり")
        
        if days_with_excess_requests:
            issues_found = True
            print(f"  ⚠️ 希望過剰日（3人以上）: {len(days_with_excess_requests)}日")
            for day, staff_list in days_with_excess_requests[:3]:  # 最初の3日を表示
                print(f"     {day}日: {len(staff_list)}人 - {staff_list[:5]}")
        else:
            print("  ✓ 希望過剰日なし")
        
        # 3. 同性ペアリングチェック
        print("\n3. 同性ペアリングチェック:")
        gender_conflicts = []
        for day, staff_list in daily_requests.items():
            if len(staff_list) >= 2:
                genders = [self.staff.loc[s, 'Sex'] for s in staff_list]
                if len(set(genders)) > 1:
                    gender_conflicts.append((day, staff_list))
        
        if gender_conflicts:
            issues_found = True
            print(f"  ⚠️ 異性混在日: {len(gender_conflicts)}日")
            for day, staff_list in gender_conflicts[:3]:
                genders = [f"{s}({self.staff.loc[s, 'Sex']})" for s in staff_list]
                print(f"     {day}日: {genders}")
        else:
            print("  ✓ 問題なし")
        
        # 4. 役職者ペアリングチェック
        print("\n4. 役職者ペアリングチェック:")
        role_conflicts = []
        for day, staff_list in daily_requests.items():
            if len(staff_list) >= 2:
                roles = [self.staff.loc[s, '主任以上'] for s in staff_list]
                if sum(roles) >= 2:
                    role_conflicts.append((day, staff_list))
        
        if role_conflicts:
            issues_found = True
            print(f"  ⚠️ 役職者2名以上の日: {len(role_conflicts)}日")
            for day, staff_list in role_conflicts[:3]:
                roles = [f"{s}(役職)" if self.staff.loc[s, '主任以上'] else s for s in staff_list]
                print(f"     {day}日: {roles}")
        else:
            print("  ✓ 問題なし")
        
        print("\n" + "="*40)
        if issues_found:
            print("⚠️  警告：競合が検出されました。解が見つからない可能性があります。")
        else:
            print("✓ 事前検証完了：重大な競合は検出されませんでした。")
        
        #5 当直希望日の翌日チェック（前日ブロック競合)e
        print("\n5. 当直希望日の翌日チェック（前日ブロック競合）:")
        blocking_hope_labels = {0:"休み", 1:"出勤", 2:"当直不可", 3:"育休", 5:"慶弔休暇", 6:"研修", 7:"なし", 8:"当直"}
        oncall_blocked_conflicts = []
        
        for staff in self.staff.index:
            if self.staff.loc[staff,'当直']==False or self.staff.loc[staff,'休職']==True:
                continue
            for day in range(1,self.days+1):
                if self._hope_matches(self._get_hope_value(staff, day, default=7), {8}):  # 当直希望日
                    next_day = day + 1
                    if next_day <= self.days:
                        next_day_hope = self._get_hope_value(staff, next_day, default=7)
                        if next_day_hope in [0, 3, 5, 6]:  # ブロックする希望
                            oncall_blocked_conflicts.append((staff, day, blocking_hope_labels[next_day_hope]))
        if oncall_blocked_conflicts:
            print(f"  ⚠️ 当直希望日の翌日にブロックする希望があるケース: {len(oncall_blocked_conflicts)}件")
            for staff, day, hope_label in oncall_blocked_conflicts[:5]:  # 最初の5件を表示
                print(f"     スタッフ{staff}の{day}日当直希望 → {day+1}日が{hope_label}希望")
        else:
            print("  ✓ 問題なし")
            
        print("="*40 + "\n")
        
        return daily_requests  # 後続処理で使用するため返す
        
    def apply_oncall_requests(self):                   
        """当直希望を叶える == 8 ハード制約に変更（希望過剰日は公平性基準で選択）"""
        print("当直希望を反映します")

        blocking_hope_labels = {
            0: "休み",
            1: "出勤",
            2: "当直不可",
            3: "育休",
            5: "慶弔休暇",
            6: "研修",
            7: "なし",
            8: "当直",
        }

        # 当直日に専属業務(休み/明け以外)へ配置可能かを先に把握
        staff_has_primary_work_option = {}
        for staff_name in self.staff.index:
            primary_sections = [
                section
                for section in self.primary_sections
                if section in self.get_eligible_sections[staff_name] and section not in (0, 17)
            ]
            staff_has_primary_work_option[staff_name] = len(primary_sections) > 0
        
        # 希望を集計
        oncall_request_days = {}
        for staff in self.staff.index:
            if self.staff.loc[staff,'当直']==False or self.staff.loc[staff,'休職']==True:
                continue
            staff_requests = self.hope_list.loc[staff]
            for day in range(1,self.days +1):
                if self._hope_matches(self._get_hope_value(staff, day, default=7), {8}):
                    oncall_request_days[(staff,day)] = True
                    print(f"  スタッフ{staff}の{day}日の当直希望を反映します。")
                            
        # 同じ日の希望者をグループ化
        daily_requests = {}
        for (staff,day) in oncall_request_days.keys():
            if day not in daily_requests:
                daily_requests[day] = []
            daily_requests[day].append(staff)
        
        # 希望過剰日（3人以上）を公平性基準で処理
        fairness_penalties = []
        request_penalties = []
        
        for day, staff_list in daily_requests.items():
            compatible_pair_vars_by_staff = {}
            
            for staff in staff_list:
                compatible_partners = []
                exclusion_reason_counts = {}
                excluded_partners = []
                
                for other_staff in self.staff.index:
                    if staff == other_staff:
                        continue

                    reasons = []
                    pair_var = self.optimizer.get_oncall_pair(staff, other_staff, day)
                    if pair_var is None:
                        reasons.append("pair_var未定義")

                    if not bool(self.staff.loc[other_staff, '当直']):
                        reasons.append("相手:当直不可")
                    if bool(self.staff.loc[other_staff, '休職']):
                        reasons.append("相手:休職")

                    if self.staff.loc[staff, 'Sex'] != self.staff.loc[other_staff, 'Sex']:
                        reasons.append("異性ペア")

                    if self.staff.loc[staff, '同期変数'] == self.staff.loc[other_staff, '同期変数']:
                        reasons.append("同期ペア")

                    if bool(self.staff.loc[staff, '主任以上']) and bool(self.staff.loc[other_staff, '主任以上']):
                        reasons.append("主任以上同士")

                    staff_hope = self._get_hope_value(staff, day, default=7)
                    other_hope = self._get_hope_value(other_staff, day, default=7)
                    if self._hope_matches(staff_hope, {0, 2, 3, 5, 6}):
                        reasons.append(f"本人希望={staff_hope}")
                    if self._hope_matches(other_hope, {0, 2, 3, 5, 6}):
                        reasons.append(f"相手希望={other_hope}")

                    # 厳密モードでは翌日が休み系希望だと当直翌日(明け)と衝突しやすい
                    next_day = day + 1
                    if next_day <= self.days:
                        staff_next_hope = self._get_hope_value(staff, next_day, default=7)
                        other_next_hope = self._get_hope_value(other_staff, next_day, default=7)
                        if self._hope_matches(staff_next_hope, {0, 3, 5, 6,11}):
                            reasons.append(f"本人翌日希望={blocking_hope_labels.get(staff_next_hope, staff_next_hope)}")
                        if self._hope_matches(other_next_hope, {0, 3, 5, 6,11}):
                            reasons.append(f"相手翌日希望={blocking_hope_labels.get(other_next_hope, other_next_hope)}")

                    if not staff_has_primary_work_option.get(staff, True):
                        reasons.append("本人:専属業務候補なし")
                    if not staff_has_primary_work_option.get(other_staff, True):
                        reasons.append("相手:専属業務候補なし")

                    if reasons:
                        excluded_partners.append((other_staff, reasons))
                        for reason in reasons:
                            exclusion_reason_counts[reason] = exclusion_reason_counts.get(reason, 0) + 1
                    else:
                        compatible_partners.append(other_staff)

                compatible_pair_vars = [
                    self.optimizer.get_oncall_pair(staff, other_staff, day)
                    for other_staff in compatible_partners
                ]
                compatible_pair_vars_by_staff[staff] = [
                    pair_var for pair_var in compatible_pair_vars if pair_var is not None
                ]
                if not compatible_partners:
                    print(
                        f"[DEBUG当直希望警告] Day{day}:staff={staff} は実質候補0です。"
                        f"除外詳細(最大10件)={excluded_partners[:10]}"
                    )
                
            
            if len(staff_list) <= 2:
                # 希望は実現可能な範囲で優先し、間隔制約との競合時は未達を許容する
                for staff in staff_list:
                    oncall_pairs = compatible_pair_vars_by_staff[staff]
                    if oncall_pairs:
                        staff_selected = self.model.NewBoolVar(
                            f'staff_{staff}_selected_day_{day}'
                        )
                        self.model.Add(sum(oncall_pairs) >= 1).OnlyEnforceIf(staff_selected)
                        self.model.Add(sum(oncall_pairs) == 0).OnlyEnforceIf(staff_selected.Not())
                        request_penalty = self.model.NewBoolVar(
                            f'oncall_request_penalty_{staff}_{day}'
                        )
                        self.model.Add(request_penalty + staff_selected == 1)
                        request_penalties.append(request_penalty)
                    else:
                        print(
                            f"  ⚠️ スタッフ{staff}の{day}日の希望は、"
                            "他の制約と両立するペアがないため未達として扱います"
                        )
                        request_penalty = self.model.NewBoolVar(
                            f'oncall_request_penalty_{staff}_{day}'
                        )
                        self.model.Add(request_penalty == 1)
                        request_penalties.append(request_penalty)
            else:
                # 3人以上の場合は、公平性基準でソフト制約化
                print(f"  ℹ️  {day}日: {len(staff_list)}人希望 → 公平性基準で2人選択")
                
                # 各希望者が選ばれた場合のペナルティを設定（月累計が多いほどペナルティ大）
                for staff in staff_list:
                    # このスタッフがこの日に当直に入るかどうかの変数
                    staff_selected = self.model.NewBoolVar(f'staff_{staff}_selected_day_{day}')
                    
                    oncall_pairs = compatible_pair_vars_by_staff[staff]
                    
                    if oncall_pairs:
                        # staff_selectedとペア変数を連動
                        self.model.Add(sum(oncall_pairs) >= 1).OnlyEnforceIf(staff_selected)
                        self.model.Add(sum(oncall_pairs) == 0).OnlyEnforceIf(staff_selected.Not())
                        
                        # 公平性ペナルティ：月累計回数 × 選択フラグ × 重み
                        if staff in self.monthly_oncall_counts:
                            # 月累計回数が多い人ほどペナルティが大きい
                            penalty_var = self.model.NewIntVar(0, 100, f'fairness_penalty_{staff}_{day}')
                            # penalty = monthly_count * 10 (重み) * staff_selected
                            self.model.Add(penalty_var == self.monthly_oncall_counts[staff] * 10).OnlyEnforceIf(staff_selected)
                            self.model.Add(penalty_var == 0).OnlyEnforceIf(staff_selected.Not())
                            fairness_penalties.append(penalty_var)
                    else:
                        print(f"  ⚠️ スタッフ{staff}の{day}日の希望を満たせません（ペアなし）")
                        self.model.Add(staff_selected == 0)

                    request_penalty = self.model.NewBoolVar(
                        f'oncall_request_penalty_{staff}_{day}'
                    )
                    self.model.Add(request_penalty + staff_selected == 1)
                    request_penalties.append(request_penalty)
                
                # この日は最大2人まで
                day_staff_vars = []
                for staff in staff_list:
                    staff_var = self.model.NewBoolVar(f'staff_{staff}_oncall_check_{day}')
                    oncall_pairs = compatible_pair_vars_by_staff[staff]
                    if oncall_pairs:
                        self.model.Add(sum(oncall_pairs) >= 1).OnlyEnforceIf(staff_var)
                        self.model.Add(sum(oncall_pairs) == 0).OnlyEnforceIf(staff_var.Not())
                        day_staff_vars.append(staff_var)
                
                if day_staff_vars:
                    # 希望者が多くても、最大2人まで（ハード制約）
                    self.model.Add(sum(day_staff_vars) <= 2)
        
        # 公平性ペナルティを目的関数に追加（後で apply_weighted_objective に渡す）
        self.fairness_penalties = fairness_penalties
        self.request_penalties = request_penalties
        print(f"  公平性ペナルティ変数: {len(fairness_penalties)}個作成")
        print(f"  当直希望未達ペナルティ変数: {len(request_penalties)}個作成")
    #なるべく叶える制約の重みづけを行う
    def apply_weighted_objective(self):
        """重みづけした目的関数を設定"""
        print("重みづけした目的関数を設定します")        
        floor_penalties = self.oncall_paring_floor()
        #役職者同士の当直を避けるペナルティを取得
        executive_penalties = self.add_oncall_paring_role_constaints()
        # 同期同士の当直を避けるペナルティを取得
        sync_penalties = self.add_oncall_paring_sync_constraints()
        # 当直回数の偏り（max-min）を抑える公平性ペナルティ
        fairness_penalties = self.add_oncall_fairness_penalties()
        prev_month_balance_penalties = self.add_oncall_prev_month_balance_penalties()
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
        WEIGHT_ONCALL_SAME_FLOOR = 20#同フロアの当直ペアリングを避ける重み
        WEIGHT_EXECUTIVE_PAIR = self._soft_oncall_rule_configs['executive_pair']['weight']  # 役職者同士の当直ペアリングを避ける重み
        WEIGHT_SYNC = self._soft_oncall_rule_configs['sync']['weight']  # 同期ペアリングを避ける重み
        WEIGHT_SECOND_FRIDAY = self._soft_oncall_rule_configs['second_friday_conference']['weight']#
        WEIGHT_SECOND_FRIDAY_PREV = self._soft_oncall_rule_configs['second_friday_conference_prev']['weight']
        WEIGHT_FAIRNESS = 20  # 当直回数の偏りを抑える公平性ペナルティの重み
        WEIGHT_ONCALL_REQUEST = 1000  # 当直希望を7日間隔より下位のソフト制約として優先する重み
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

        #結合した目的関数
        total_penalty = (
            WEIGHT_EXECUTIVE_PAIR * sum(executive_penalties) +
            WEIGHT_ONCALL_SAME_FLOOR * sum(floor_penalties) +
            WEIGHT_FAIRNESS * sum(fairness_penalties) +
            WEIGHT_ONCALL_PREV_MONTH_BALANCE * sum(prev_month_balance_penalties) +
            WEIGHT_ONCALL_REQUEST * sum(getattr(self, 'request_penalties', [])) +
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
            WEIGHT_PMSHIFT_PREV * sum(pm_shift_prev_penalties)
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
        print(f"    - 同フロア回避ペナルティ: {len(floor_penalties)}個 (重み={WEIGHT_ONCALL_SAME_FLOOR})")
        print(f"    - 公平性ペナルティ: {len(fairness_penalties)}個 (重み={WEIGHT_FAIRNESS})")
        print(f"    - 薬審前日当直回避ペナルティ: {len(yakushin_nextday)}個 (重み={WEIGHT_YAKUSHIN_NEXTDAY})")
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
        print(f"    - 役職者会議前日当直回避ペナルティ: {len(exective_meeting_penalties)}個 (重み={WEIGHT_EXECTIVE_MEETING})")
        print(f"    - 役職者会議前々日当直回避ペナルティ: {len(exective_meeting_prev_penalties)}個 (重み={WEIGHT_EXECTIVE_MEETING_PREV})")
        print(f"    - 認知症せん妄ラウンド前日当直回避ペナルティ: {len(dementia_round_penalties)}個 (重み={WEIGHT_DEMENTIA_ROUND})")
        print(f"    - 認知症せん妄ラウンド前々日当直回避ペナルティ: {len(dementia_round_prev_penalties)}個 (重み={WEIGHT_DEMENTIA_ROUND_PREV})")
        print(f"  合計ペナルティ: {total_penalty}")
        self.optimizer.register_objective_term("oncall_constraints", total_penalty)

    def add_oncall_prev_month_balance_penalties(self):
        """
        ソフト制約
        - 前月1回のスタッフはなるべく今月2回、前月2回のスタッフはなるべく今月1回
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
                shortfall = self.model.NewIntVar(0, 2, f'oncall_prev1_shortfall_{staff}')
                self.model.Add(shortfall == 2 - monthly_count)
                penalties.append(shortfall)
            elif previous_count >= 2:
                excess = self.model.NewIntVar(0, 1, f'oncall_prev2_excess_{staff}')
                self.model.Add(excess >= monthly_count - 1)
                penalties.append(excess)
        print(f"前月当直回数バランスペナルティ: {len(penalties)}個")
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