from optimizer.base_constraint import BaseConstraint
class OncallConstraints(BaseConstraint):
    """当直に関する制約条件を定義するクラス"""
    def __init__(self, model,optimizer):
        super().__init__(model, optimizer)
        
    def apply(self):
        self.add_daily_oncall()
        self.add_oncall_constraints()
        self.add_oncall_paring_constraints()
        self.oncall_paring_floor()
        self.add_oncall_paring_role_constaints()
        self.add_oncall_paring_sync_constraints()
        
    
    def add_daily_oncall(self):
        """
        毎日誰かが当直になるようにする
        """
        print("毎日の当直を確保します。")
        for day in range(1,self.days +1):
            daily_oncalls = []
            for staff1 in self.staff.index:
                staff_oncall = self.model.NewBoolVar(f'staff_{staff1}_oncall_day_{day}')
                #スタッフがペアの1番目または2番目にいる場合、当直に入っている
                oncall_pairs = []
                for other_staff in self.staff.index:
                    if staff1 != other_staff:
                        oncall_pairs.append(self.night_shifts.get((staff1,other_staff,day),0))
                        oncall_pairs.append(self.night_shifts.get((other_staff,staff1,day),0))
                        
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
                            self.model.Add(
                                self.night_shifts.get((staff,other_staff,day),0)==0
                            )
                            self.model.Add(self.night_shifts.get((other_staff,staff,day),0)==0)
            #休職中のスタッフは当直割り当てを行わない
            elif self.staff.loc[staff,'休職']==True:
                print(f"{staff}さんは休職中のため、当直割り当てを行いません。")
                for day in range(1,self.days +1):                
                    for other_staff in self.staff.index:
                        if staff != other_staff:
                            self.model.Add(
                                self.night_shifts.get((staff,other_staff,day),0)==0
                            )
                            self.model.Add(self.night_shifts.get((other_staff,staff,day),0)==0)
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
                        7:"なし"
                    }
                    """
                    if self.hope_list.loc[staff].iloc[day-1]==2:#当直不可の日を避ける
                        staff_not_oncall_days.append(day)
                        
                    if self.hope_list.loc[staff].iloc[day-1]==0:#休み希望の日を避ける
                        staff_holidays.append(day)
                        if day+1 <= self.days:
                            staff_holidays.append(day+1)#休み希望の次の日も避ける
                    
                    if self.hope_list.loc[staff].iloc[day-1]==5:#慶弔休暇の日を避ける
                        staff_keichou_days.append(day)
                    
                    if self.hope_list.loc[staff].iloc[day-1]==3:#育休の日を避ける
                        staff_iku_days.append(day)
                    
                    if self.hope_list.loc[staff].iloc[day-1]==6:#研修の日を避ける
                        staff_kenshu_days.append(day)
                        
                #当直不可の日を避ける
                for not_oncall_day in staff_not_oncall_days:
                    for other_staff in self.staff.index:
                        if staff != other_staff:
                            self.model.Add(self.night_shifts.get((staff,other_staff,not_oncall_day),0)==0)            
                            self.model.Add(self.night_shifts.get((other_staff,staff,not_oncall_day),0)==0)
                            
                #休み希望の日と次の日の当直を避ける
                for holiday in staff_holidays:
                    for other_staff in self.staff.index:
                        if staff != other_staff:
                            self.model.Add(self.night_shifts.get((staff,other_staff,holiday),0)==0)
                            self.model.Add(self.night_shifts.get((other_staff,staff,holiday),0)==0)
                            
                
                #慶弔休暇の日の当直を避ける
                for keichou_day in staff_keichou_days:
                    for other_staff in self.staff.index:
                        if staff != other_staff:
                            self.model.Add(self.night_shifts.get((staff,other_staff,keichou_day),0)==0)
                            self.model.Add(self.night_shifts.get((other_staff,staff,keichou_day),0)==0)
                            
                #育休の日の当直を避ける
                for iku_day in staff_iku_days:
                    for other_staff in self.staff.index:
                        if staff != other_staff:
                            self.model.Add(self.night_shifts.get((staff,other_staff,iku_day),0)==0)
                            self.model.Add(self.night_shifts.get((other_staff,staff,iku_day),0)==0)
                            
                #研修の日の当直を避ける
                for kenshu_day in staff_kenshu_days:
                    for other_staff in self.staff.index:
                        if staff != other_staff:
                            self.model.Add(self.night_shifts.get((staff,other_staff,kenshu_day),0)==0)
                            self.model.Add(self.night_shifts.get((other_staff,staff,kenshu_day),0)==0)
                            
                            
                #外来部門、役職者の当直は月1回まで
                if (self.staff.loc[staff,'Floor'] in [9,10]) and (self.staff.loc[staff,'主任以上']==True):
                    for day in range(1,self.days +1):
                        for other_staff in self.staff.index:
                            if staff != other_staff:
                                # staffが1番目の位置でnight_shiftに入る場合
                                total_oncalls_role.append(self.night_shifts.get((staff,other_staff,day),0))
                                # staffが2番目の位置でnight_shiftに入る場合
                                total_oncalls_role.append(self.night_shifts.get((other_staff,staff,day),0))
                    self.model.Add(sum(total_oncalls_role)<=1)  
                else:
                    #月2回までの制約
                    for day in range(1,self.days +1):
                        for other_staff in self.staff.index:
                            if staff != other_staff:
                                # staffが1番目の位置でnight_shiftに入る場合
                                total_oncalls.append(self.night_shifts.get((staff,other_staff,day),0))
                                # staffが2番目の位置でnight_shiftに入る場合
                                total_oncalls.append(self.night_shifts.get((other_staff,staff,day),0))
                            
                    #月1回以上、2回までの制約を追加
                    self.model.Add(sum(total_oncalls)>=1)
                    self.model.Add(sum(total_oncalls)<=2)

#7.当直は同性のスタッフで構成、同じフロアの組み合わせを避ける
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
                            self.model.Add(
                                self.night_shifts.get((staff1,staff2,day),0)==0
                            )
    
    def oncall_paring_floor(self)    :
        """
        当直のペアリング設定,ソフト制約
        - なるべく同じフロアのスタッフでの組み合わせは避ける
        """
        print("当直のペアリング設定（同フロア避ける）を適用します。")
        floor_penalties = []
        for day in range(1,self.days +1):
            for staff1 in self.staff.index:
                for staff2 in self.staff.index:
                    if staff1 != staff2:
                        if self.staff.loc[staff1,'Floor'] == self.staff.loc[staff2,'Floor']:
                            penalty_var = self.model.NewBoolVar(f'oncall_floor_penalty_{staff1}_{staff2}_{day}')
                            self.model.Add(
                                self.night_shifts.get((staff1,staff2,day),0)==1
                            ).OnlyEnforceIf(penalty_var)
                            floor_penalties.append(penalty_var)
        self.model.Minimize(sum(floor_penalties))
    
    def add_oncall_paring_role_constaints(self):
        """役職者どうしのペアリングは避ける"""
        print("当直のペアリング設定（役職者避ける）を適用します。")
        for day in range(1,self.days +1):
            for staff1 in self.staff.index:
                for staff2 in self.staff.index:
                    if staff1 != staff2:
                        if (self.staff.loc[staff1,'主任以上']==True) and (self.staff.loc[staff2,'主任以上']==True):
                            self.model.Add(
                                self.night_shifts.get((staff1,staff2,day),0)==0
                            )
    def add_oncall_paring_sync_constraints(self):
        """同期のペアリングは避ける"""
        print("当直のペアリング設定（同期避ける）を適用します。")
        for day in range(1,self.days +1):
            for staff1 in self.staff.index:
                for staff2 in self.staff.index:
                    if staff1 != staff2:
                        if self.staff.loc[staff1,'勤続年数']==self.staff.loc[staff2,'勤続年数']:
                            self.model.Add(
                                self.night_shifts.get((staff1,staff2,day),0)==0
                            )
    #7.当直明けはなるべく休み
    
    
    #8.前回の当直から次回の当直までは最低7日間空けるe
    def add_oncall_spacing_constraints(self):
        """
        当直の間隔に関する制約
        - スタッフにつき、前回から次回の当直までは最低７日間空ける
        """
        oncall_days = {}
        for staff in self.staff.index:
            oncall_days[staff] = []