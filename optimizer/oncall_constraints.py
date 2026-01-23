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
        
    
    def add_daily_oncall(self):
        """
        毎日誰かが当直になるようにする
        """
        print("毎日の当直を確保します。")
        for day in range(1,self.days +1):
            daily_oncalls = []
            for staff1 in self.staff.index:
                for staff2 in self.staff.index:
                    if staff1 != staff2:
                        daily_oncalls.append(self.night_shifts.get((staff1,staff2,day),0))
            self.model.Add(sum(daily_oncalls) >=1)
    
    #6.当直は月2回まで,当直不可のスタッフは除外する
    def add_oncall_constraints(self):
        """
        当直の基本制約
        - 当直不可のスタッフは除外
        - 月2回まで
        """
        print("当直の基本制約を適用します。")
        for staff in self.staff.index:
            if self.staff.loc[staff,'当直']==False:
                for day in range(1,self.days +1):
                    for other_staff in self.staff.index:
                        if staff != other_staff:
                            self.model.Add(
                                self.night_shifts.get((staff,other_staff,day),0)==0
                            )
            else:
                total_oncalls = []
                for day in range(1,self.days +1):
                    for other_staff in self.staff.index:
                        if staff != other_staff:
                            total_oncalls.append(self.night_shifts.get((other_staff,staff,day),0))
                self.model.Add(
                    sum(total_oncalls)<=2
                )
    
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
        
    #7.当直明けはなるべく休み
    
    #8.前回の当直から次回の当直までは最低7日間空ける