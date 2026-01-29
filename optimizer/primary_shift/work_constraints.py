from optimizer.base_constraint import BaseConstraint
from config.floor_mapping import FLOOR_MAPPING
import random
import pandas as pd
class WorkConstraints(BaseConstraint):
    """勤務に関する基本制約"""
    def apply(self):
        self.eligible_sections = self._get_eligible_section_constraints()
        self._add_basic_constraints()
        self._get_eligible_section_constraints()
        self.add_on_call_primary_section_constraint()
        self.add_section_requests12()
#        self.add_consecutive_work_constraints()
        self.add_mandatory_day_off_constraints()
        
    def _add_basic_constraints(self):
        """専属業務は1人1日1セクションのみ"""
        # 1. 専属業務は1人1日1セクションのみ
        for staff in self.staff.index:
            #primary_sections のうち、割り当て可能なセクションのみを対象とする
            staff_primary_sections = [s for s in self.primary_sections if s in self.eligible_sections[staff]]
            #staff_primary_sectionsが空の場合はデフォルトのself.staff_primary_sectionsを使用
                
            for day in range(1, self.days + 1):
                """if not staff_primary_sections:
                    #特に指定がない場合は割り当て可能な業務でランダムに選択する TODO：必要人数があるから、割り当て可能な業務の中から選んでもらう？
                    available_sections = list(self.primary_sections)
                    print(f"スタッフ{staff}のデフォルトの専属業務セクション: {available_sections}")
                    if available_sections:
                        staff_primary_sections =available_sections
                    else:
                        print(f"警告: スタッフ{staff}に割り当て可能な専属業務セクションがありません。")
                        continue
                """    
                    
                self.model.Add(
                    sum(self.shifts[(staff, day, section)] for section in staff_primary_sections) <= 1
                )
                
                for c_section in self.concurrent_sections:
                    for section in staff_primary_sections:
                        # 2. 兼務業務は専属業務がある場合のみ割り当て可能
                        # 専属業務がない場合は兼務業務も割り当てない
                        self.model.Add(
                            self.concurrent_shifts[(staff, day, c_section)] <= self.shifts[(staff, day, section)]
                        )    
                        
        
    #条件.xlsxによる割り当て可能な業務名の制約
    def _get_eligible_section_constraints(self):
        """
        スタッフ条件.xlsxによる割り当て可能な業務名の制約
        出勤の際に割り当てる業務はFloor,もしくはfloor2に制約している業務のみとする。
        floor  、flor2の定義
        - 化療：化療と調剤室
        - 調剤室：調剤室のみ
        - DI: DIと調剤室,所属病棟
        - ただし、name=6はDIのみ
        - 外来：外来のみ
        - 1-2階：1-2階、調剤室、所属病棟
        - 3階：3階、調剤室、所属病棟
        - 4階：4階、調剤室、所属病棟
        - 5階：5階、調剤室、所属病棟
        - name=0：医療安全・感染管理のみ
        
        """
        eligable_sections_dict = {}
        
        for staff in self.staff.index:
            eligable_sections = []
            floor = self.staff.loc[staff,'Floor']
            floor2 = self.staff.loc[staff,'Floor2']
            
            #name==6はDIのみ
            if staff == 6:
                eligable_sections = [0,8]  # DIのセクションID もしくは休み
            #name==0は医療安全・感染管理のみ
            elif staff == 0:
                eligable_sections = [0,14]  # 医療安全・感染管理のセクションID　もしくは休み
            #floorが有効な値の場合
            else:
                if pd.notna(floor) and floor != '':
                    #floorごとに対応したprimary_sectionを追加
                    match floor:
                        case 1:#1-2
                            eligable_sections = [0,4,1]  # 休み、1-2階、調剤室
                        case 2:#DI
                            #各スタッフの所属病棟を取得
                            if floor2 ==1:
                                eligable_sections = [0,8,1,4]  # 休み、DI、調剤室、1-2階
                            elif floor2 ==3:
                                eligable_sections = [0,8,1,5]  # 休み、DI、調剤室、3階
                            elif floor2 ==4:
                                eligable_sections = [0,8,1,6]  # 休み、DI、調剤室、4階
                            elif floor2 ==5:
                                eligable_sections = [0,8,1,7]  # 休み、DI、調剤室、5階
                            else:
                                eligable_sections = [0,8,1]  # 休み、DI、調剤室
                        case 3:#3
                            eligable_sections = [0,5,1]  # 休み、3階、調剤室
                        case 4:#4
                            eligable_sections = [0,6,1]  # 休み、4階、調剤室
                        case 5:#5
                            eligable_sections = [0,7,1]  # 休み、5階、調剤室
                        case 6:#化療
                            eligable_sections = [0,9,1]  # 休み、化療、調剤室
                        case 8:#調剤
                            eligable_sections = [0,1]  # 休み、調剤室のみ
                        case 9:#外来
                            eligable_sections = [0,16]  # 休み、外来
                        case _:
                            print(f"警告: スタッフ{staff}のFloorの値が不正です: {floor}")
                else:
                    print(f"警告: スタッフ{staff}のFloorの値が欠損しています。")
                            
                        
            
            eligable_sections_dict[staff] = eligable_sections
            
        return eligable_sections_dict
    
    def add_on_call_primary_section_constraint(self):
        """当直に割り当てられている日に専属業務を休みにしない !=0"""
        for staff in self.staff.index:
            for day in range(1,self.days +1):
                oncall_assigned = []
                for other_staff in self.staff.index:
                    if staff != other_staff:
                        oncall_assigned.append(self.night_shifts.get((staff,other_staff,day),0))
                        oncall_assigned.append(self.night_shifts.get((other_staff,staff,day),0))
                if oncall_assigned:
                    self.model.Add(
                        sum(oncall_assigned) <= sum(
                            self.shifts[(staff,day,section)] for section in self.primary_sections
                        )
                    )
                        
    ##配置
    def add_section_requests12(self):
        """
        1～2階は月～土は3名
        （nane :[7,10,11,14]のうち1人は必ず出勤にする）
        - 日祝日は0名
        - floor=1-2のうちから、月～土は3名選出する
        - スタッフ条件に「1人は必ず出勤にする」の対象者を追加する
        - 選出メンバーの内にnane :[7,10,11,14]を必ず1人含める
        
        """
        #月〜土はflor=1-2が3名必要
        for day in range(1, self.days + 1):
            # primarty_sectionでfloor=1-2に対応するセクションID
            floor_1_2_section_id = 4
            #3F
            floor_3_section_id = 5
            #4F
            floor_4_section_id = 6
            #5F
            floor_5_section_id = 7
                            
            assigned_staff_12 = []
            assigned_staff_3 = []
            assigned_staff_4 = []
            assigned_staff_5 = []
            
            required_staff_12 = ["7","10","11","14"]
            required_staff_12_assigned = [] #12Fで必須メンバーが割り当てられた変数リスト
            
            for staff in self.staff.index:
                if floor_1_2_section_id in self.eligible_sections[staff]:
                    assigned_staff_12.append(self.shifts[(staff, day, floor_1_2_section_id)])
                    if staff in required_staff_12:
                        required_staff_12_assigned.append(self.shifts[(staff,day,floor_1_2_section_id)])
                if floor_3_section_id in self.eligible_sections[staff]:
                    assigned_staff_3.append(self.shifts[(staff, day, floor_3_section_id)])
                if floor_4_section_id in self.eligible_sections[staff]:
                    assigned_staff_4.append(self.shifts[(staff, day, floor_4_section_id)])
                if floor_5_section_id in self.eligible_sections[staff]:
                    assigned_staff_5.append(self.shifts[(staff, day, floor_5_section_id)])
                    
            """日曜祝日は0人"""
            weekend = [7]
            holiday = self.holidays
            is_holiday = False
            for h in holiday:
                if h[0].day == day:
                    is_holiday = True
                    break
                
            
            """12階、3階、4階、5階:日曜祝日は0人"""
            if day == 7 or is_holiday:
                self.model.Add(
                    sum(assigned_staff_12) ==0
                )
                self.model.Add(
                    sum(assigned_staff_3) ==0
                )
                self.model.Add(
                    sum(assigned_staff_4) ==0
                )
                self.model.Add(
                    sum(assigned_staff_5) ==0
                )
                continue
            
            """12F:weekdayの場合、3人配置"""
            if day not in weekend and not is_holiday:    
                if assigned_staff_12:
                    self.model.Add(
                        sum(assigned_staff_12) >=3
                    )
            
                #必須メンバーから1人は必ず割り当てる
                if required_staff_12_assigned:
                    self.model.Add(
                        sum(required_staff_12_assigned) >=1
                    )
            """
            3階は火曜のみ5名、他は4名。
            - 日曜祝日は0名、上で定義済み
            """
            if day==2:
                if assigned_staff_3:
                    self.model.Add(
                        sum(assigned_staff_3) >=5
                    )
            else:
                if assigned_staff_3:
                    self.model.Add(
                        sum(assigned_staff_3) >=4
                    )
                    
            """
            4階：月のみ5名、他は4名。
            - 日曜祝日は0名、上で定義済み
            """
            if day==1:
                if assigned_staff_4:
                    self.model.Add(
                        sum(assigned_staff_4) >=5
                    )
            else:
                if assigned_staff_4:
                    self.model.Add(
                        sum(assigned_staff_4) >=4
                    )
            """
            5階：連休明けでない火曜は4名、月・水は5名、木～土は4名
            - 日曜祝日は0名、上で定義済み
            - 連休明けの定義：前日が祝日、もしくは祝日の次の日が火曜日の場合
            - 連休明け火曜は5名
            - それ以外の火曜は4名
            """
            if day==2 and day-1 in holiday:#連休明け火曜
                if assigned_staff_5:
                    self.model.Add(
                        sum(assigned_staff_5) >=5
                    )
            if day==1 or day==3:#月・水
                if assigned_staff_5:
                    self.model.Add(
                        sum(assigned_staff_5) >=5
                    )
            if day==2:#通常の火曜は0名
                if assigned_staff_5:
                    self.model.Add(
                        sum(assigned_staff_5) >=4
                    )
            else:
                if assigned_staff_5:
                    self.model.Add(
                        sum(assigned_staff_5) >=4
                    )
            

        
    def add_consecutive_work_constraints(self):
        """
        連続出勤の制限
        - 当直明けを含めると6日まで
        - 休み0以外のprimary_sectionが7日以上連続しないようにする
        """
        
        for staff in self.staff.index:             
            # 7日間の連続する期間をチェック
            for start_day in range(1, self.days - 6 + 1):
                # いずれかのwork_sectionに割り当てられた日数の合計が6日以内
                #0以外のセクションを指定 1~16
                self.model.Add(
                    sum(
                        self.shifts[(staff, start_day + offset_day, 14)]
                        for offset_day in range(7)
                    ) <= 6
                )
                #すべての
                
    #7日間に1日は休みになる
    def add_mandatory_day_off_constraints(self):
        """
        7日間に1日は必ず休みにする
        月末付近の日数不足にも対応
        """
        print("7日間に1日休みの制約を適用します。")
        for staff in self.staff.index:
            # 割り当て可能なセクションに休み(0)が含まれているか確認
            if 0 not in self.eligible_sections.get(staff, []):
                print(f"警告: スタッフ{staff}の割り当て可能セクションに休み(0)が含まれていません")
                continue
            
            # 日数が7日未満の場合は全期間で1日休みを確保
            if self.days < 7:
                self.model.Add(
                    sum(
                        self.shifts[(staff, day, 0)]
                        for day in range(1, self.days + 1)
                    ) >= 1
                )
                continue
            
            # 7日間のウィンドウごとに休みを確保（ソフト制約に変更）
            for start_day in range(1, self.days - 6 + 1):
                # ペナルティ変数を使用してソフト制約化
                penalty_var = self.model.NewBoolVar(f'no_dayoff_penalty_{staff}_{start_day}')
                
                # 7日間で1日以上休みがある場合、ペナルティなし
                self.model.Add(
                    sum(
                        self.shifts[(staff, start_day + offset_day, 0)]
                        for offset_day in range(7)
                    ) >= 1
                ).OnlyEnforceIf(penalty_var.Not())
                
                # ペナルティをなるべく避ける（目的関数で最小化）
                # この変数を後で目的関数に追加する必要があります