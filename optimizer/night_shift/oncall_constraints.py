from optimizer.base_constraint import BaseConstraint
class OncallConstraints(BaseConstraint):
    """当直に関する制約条件を定義するクラス"""
    def __init__(self, model,optimizer):
        super().__init__(model, optimizer)
        # 月累計当直回数を追跡する変数（公平性判断に使用）
        self.monthly_oncall_counts = {}
        
    def apply(self):
        # 制約の適用順序を変更：除外制約を先に適用してから、毎日の確保を行う
        self.add_oncall_constraints()#当直の基本制約（希望リストによる除外など）
        self._validate_oncall_requests()#事前検証：希望と制約の競合チェック
        self.apply_oncall_requests()#当直希望を叶える
        self.add_oncall_paring_constraints()#同性でペアリング
        self.add_oncall_paring_role_constaints()#役職者どうしのペアリングは避ける
        #self.add_oncall_paring_sync_constraints()#同期のペアリングは避ける TODO:勤務年数確定した情報が手に入ったら有効にする
        self.add_oncall_spacing_constraints()#前回の当直から次回の当直までは最低7日間空ける    
        self.add_daily_oncall()#毎日の当直確保
        self.apply_weighted_objective()#重みづけした目的関数を設定(外来の当直希望、なるべく同じフロア避ける)
        #self._print_oncall_statistics()  # 統計情報を出力
    
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
            for staff1 in self.staff.index:
                staff_oncall = self.model.NewBoolVar(f'staff_{staff1}_oncall_day_{day}')
                #スタッフがペアの1番目または2番目にいる場合、当直に入っている
                oncall_pairs = []
                for other_staff in self.staff.index:
                    if staff1 != other_staff:
                        pair_var = self.optimizer.get_oncall_pair(staff1, other_staff, day)
                        if pair_var is not None:
                            oncall_pairs.append(pair_var)
                        
                #いずれかのペアに入っていればstaff_oncallは1
                self.model.Add(sum(oncall_pairs) >=1).OnlyEnforceIf(staff_oncall)
                self.model.Add(sum(oncall_pairs) ==0).OnlyEnforceIf(staff_oncall.Not())
                
                daily_oncalls.append(staff_oncall)
                
            #最低1人,最高2人が当直になるようにする
            self.model.Add(sum(daily_oncalls) >=1)
            self.model.Add(sum(daily_oncalls) <=2)
    
    #6.当直は月2回まで,当直不可のスタッフは除外する
    def add_oncall_constraints(self):
        """
        当直の基本制約
        - 当直不可のスタッフは除外
        - 休職中のスタッフは除外
        - 役職者、外来部門のスタッフは月1回まで
        - 翌日が当直明けの日はなるべく除外する(薬審の日が当直明けにならないようにする)
        - 月2回まで（1番目でも2番目でも合計で2回まで）役職者、外来部門以外のスタッフは月2回まで、最低月1回
        - 当直不可の日は避ける
        - 休み希望の日は避ける、明けの日が当直にならないように休み希望の次の日も避ける
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
                #役職のチェック 、外来部門・役職者の当直は月１回まで
                
                for day in range(1,self.days +1):
                    #当直不可の日を避ける 
                    """
                    HOPE_MAPPING = {
                        0:"休み",
                        1:"出勤",
                        2:"当直不可",
                        3:"育休",
                        5:"慶弔休暇",
                        6:"研修",
                        7:"なし",
                        8:"当直"
                    }
                    前日も当直に割り当てない
                    - TODO:当直の次の次の日が出勤希望の場合は当直になるべく割り当てない ソフト制約
                    """
                    if self._get_hope_value(staff, day, default=7)==2:#当直不可の日を避ける
                        staff_not_oncall_days.append(day)
                        
                    if self._get_hope_value(staff, day, default=7)==0:#休み希望の日を避ける
                        staff_holidays.append(day)
                        if day+1 <= self.days:
                            staff_holidays.append(day-1)#休み希望の前日も避ける
                    
                    if self._get_hope_value(staff, day, default=7)==5:#慶弔休暇の日を避ける
                        staff_keichou_days.append(day)
                        if day+1 <= self.days:
                            staff_keichou_days.append(day-1)#慶弔休暇の前日も避ける
                    
                    if self._get_hope_value(staff, day, default=7)==3:#育休の日を避ける
                        staff_iku_days.append(day)
                        if day+1 <= self.days:
                            staff_iku_days.append(day-1)#育休の前日も避ける
                    
                    if self._get_hope_value(staff, day, default=7)==6:#研修の日を避ける
                        staff_kenshu_days.append(day)
                        if day+1 <= self.days:  
                            staff_kenshu_days.append(day-1)#研修の前日も避ける
                    
                    if self._get_hope_value(staff, day, default=7)==1:#出勤希望の前日は当直を避ける
                        #出勤希望の前日は当直に割り当てない
                        if day -1 >=1:
                            staff_holidays.append(day -1)
                            
                #当直不可の日を避ける
                for not_oncall_day in staff_not_oncall_days:
                    for other_staff in self.staff.index:
                        if staff != other_staff:
                            pair_var = self.optimizer.get_oncall_pair(staff, other_staff, not_oncall_day)
                            if pair_var is not None:
                                self.model.Add(pair_var == 0)
                            
                #休み希望の日と次の日の当直を避ける
                for holiday in staff_holidays:
                    for other_staff in self.staff.index:
                        if staff != other_staff:
                            pair_var = self.optimizer.get_oncall_pair(staff, other_staff, holiday)
                            if pair_var is not None:
                                self.model.Add(pair_var == 0)
                            
                
                #慶弔休暇の日の当直を避ける
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
                            
                #研修の日の当直を避ける
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
        floor9_penalties = []
        for day in range(1,self.days +1):
            for staff1 in self.staff.index:
                for staff2 in self.staff.index:
                    if staff1 != staff2:
                        pair_var = self.optimizer.get_oncall_pair(staff1, staff2, day)
                        if pair_var is not None:
                            if self.staff.loc[staff1,'Floor'] == 9:
                                penalty_var = self.model.NewBoolVar(f'oncall_floor9_penalty_{staff1}_{staff2}_{day}')
                                self.model.Add(pair_var == 1).OnlyEnforceIf(penalty_var)
                                floor9_penalties.append(penalty_var)
                            else:
                                #そのほかのフロア同士
                                penalty_var = self.model.NewBoolVar(f'oncall_floor_penalty_{staff1}_{staff2}_{day}')
                                self.model.Add(pair_var == 1).OnlyEnforceIf(penalty_var)
                                floor_penalties.append(penalty_var)
        return floor_penalties,floor9_penalties
    
    def add_oncall_paring_role_constaints(self):
        """役職者どうしのペアリングは避ける"""
        print("当直のペアリング設定（役職者避ける）を適用します。")
        for day in range(1,self.days +1):
            for staff1 in self.staff.index:
                for staff2 in self.staff.index:
                    if staff1 != staff2:
                        if (self.staff.loc[staff1,'主任以上']==True) and (self.staff.loc[staff2,'主任以上']==True):
                            pair_var = self.optimizer.get_oncall_pair(staff1, staff2, day)
                            if pair_var is not None:
                                self.model.Add(pair_var == 0)
                            
                            
    def add_oncall_paring_sync_constraints(self):
        """同期のペアリングは避ける"""
        print("当直のペアリング設定（同期避ける）を適用します。")
        for day in range(1,self.days +1):
            for staff1 in self.staff.index:
                for staff2 in self.staff.index:
                    if staff1 != staff2:
                        if self.staff.loc[staff1,'同期変数']==self.staff.loc[staff2,'同期変数']:
                            pair_var = self.optimizer.get_oncall_pair(staff1, staff2, day)
                            if pair_var is not None:
                                self.model.Add(pair_var == 0)
    #7.当直明けはなるべく休み
    
    
    #8.前回の当直から次回の当直までは最低7日間空けるe
    def add_oncall_spacing_constraints(self):
        """
        当直の間隔に関する制約
        - スタッフにつき、前回から次回の当直までは最低７日間空ける
        """
        print("当直の間隔に関する制約を適用します")
        for staff in self.staff.index:
            #当直不可または休職中のスタッフはスキップ
            if self.staff.loc[staff,'当直']==False:
                continue
            if self.staff.loc[staff,'休職']==True:
                continue
                
                
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
                    for offset in range(1,min(8,self.days -day +1)):
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
            request_count = sum(1 for day in range(1, self.days + 1) if self._get_hope_value(staff, day, default=7) == 8)
            
            if request_count > 0:
                staff_request_counts[staff] = request_count
                
                # 日別の希望者をリスト化
                for day in range(1, self.days + 1):
                    if self._get_hope_value(staff, day, default=7) == 8:
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
        print("="*40 + "\n")
        
        return daily_requests  # 後続処理で使用するため返す
                        
    def apply_oncall_requests(self):                   
        """当直希望を叶える == 8 ハード制約に変更（希望過剰日は公平性基準で選択）"""
        print("当直希望を反映します")
        
        # 希望を集計
        oncall_request_days = {}
        for staff in self.staff.index:
            if self.staff.loc[staff,'当直']==False or self.staff.loc[staff,'休職']==True:
                continue
            staff_requests = self.hope_list.loc[staff]
            for day in range(1,self.days +1):
                if self._get_hope_value(staff, day, default=7)==8:
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
        
        for day, staff_list in daily_requests.items():
            if len(staff_list) <= 2:
                # 2人以下の場合は全員の希望を実現（ハード制約）
                if len(staff_list) == 2:
                    staff1, staff2 = staff_list[0], staff_list[1]
                    sex1 = self.staff.loc[staff1, 'Sex']
                    sex2 = self.staff.loc[staff2, 'Sex']
                    if sex1 != sex2:
                        print(f"  ⚠️ {day}日: スタッフ{staff_list}は異性です！ペアを組めません。")
                
                for staff in staff_list:
                    oncall_pairs = []
                    for other_staff in self.staff.index:
                        if staff != other_staff:
                            pair_var = self.optimizer.get_oncall_pair(staff, other_staff, day)
                            if pair_var is not None:
                                oncall_pairs.append(pair_var)
                    if oncall_pairs:
                        self.model.Add(sum(oncall_pairs) >= 1)  # ハード制約
                    else:
                        print(f"  ⚠️ スタッフ{staff}の{day}日の希望を満たせません（ペアなし）")
            else:
                # 3人以上の場合は、公平性基準でソフト制約化
                print(f"  ℹ️  {day}日: {len(staff_list)}人希望 → 公平性基準で2人選択")
                
                # 各希望者が選ばれた場合のペナルティを設定（月累計が多いほどペナルティ大）
                for staff in staff_list:
                    # このスタッフがこの日に当直に入るかどうかの変数
                    staff_selected = self.model.NewBoolVar(f'staff_{staff}_selected_day_{day}')
                    
                    oncall_pairs = []
                    for other_staff in self.staff.index:
                        if staff != other_staff:
                            pair_var = self.optimizer.get_oncall_pair(staff, other_staff, day)
                            if pair_var is not None:
                                oncall_pairs.append(pair_var)
                    
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
                
                # この日は最大2人まで
                day_staff_vars = []
                for staff in staff_list:
                    staff_var = self.model.NewBoolVar(f'staff_{staff}_oncall_check_{day}')
                    oncall_pairs = []
                    for other_staff in self.staff.index:
                        if staff != other_staff:
                            pair_var = self.optimizer.get_oncall_pair(staff, other_staff, day)
                            if pair_var is not None:
                                oncall_pairs.append(pair_var)
                    if oncall_pairs:
                        self.model.Add(sum(oncall_pairs) >= 1).OnlyEnforceIf(staff_var)
                        self.model.Add(sum(oncall_pairs) == 0).OnlyEnforceIf(staff_var.Not())
                        day_staff_vars.append(staff_var)
                
                if day_staff_vars:
                    # 希望者が多くても、最大2人まで（ハード制約）
                    self.model.Add(sum(day_staff_vars) <= 2)
        
        # 公平性ペナルティを目的関数に追加（後で apply_weighted_objective に渡す）
        self.fairness_penalties = fairness_penalties
        print(f"  公平性ペナルティ変数: {len(fairness_penalties)}個作成")
    #なるべく叶える制約の重みづけを行う
    def apply_weighted_objective(self):
        """重みづけした目的関数を設定"""
        print("重みづけした目的関数を設定します")        
        floor_penalties,floor9_penalties = self.oncall_paring_floor()
        
        # 公平性ペナルティを取得（apply_oncall_requestsで設定）
        fairness_penalties = getattr(self, 'fairness_penalties', [])
        
        #重みづけ
        WEIGHT_ONCALL_SAME_FLOOR = 3
        WEIGHT_ONCALL_FLOOR9 = 10
        WEIGHT_FAIRNESS = 20  # 公平性を高優先度に設定
        
        #結合した目的関数
        total_penalty = (
            WEIGHT_ONCALL_SAME_FLOOR * sum(floor_penalties) +
            WEIGHT_ONCALL_FLOOR9 * sum(floor9_penalties) +
            WEIGHT_FAIRNESS * sum(fairness_penalties)
        )
        
        print(f"  目的関数構成:")
        print(f"    - 同フロア回避ペナルティ: {len(floor_penalties)}個 (重み={WEIGHT_ONCALL_SAME_FLOOR})")
        print(f"    - 外来ペナルティ: {len(floor9_penalties)}個 (重み={WEIGHT_ONCALL_FLOOR9})")
        print(f"    - 公平性ペナルティ: {len(fairness_penalties)}個 (重み={WEIGHT_FAIRNESS})")
        
        self.model.Minimize(total_penalty)