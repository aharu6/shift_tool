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
                
                # 兼務業務は専属業務がある場合のみ割り当て可能
                has_primary = self.model.NewBoolVar(f'has_primary_{staff}_{day}')
                self.model.Add(
                    sum(self.shifts[(staff, day, section)] for section in staff_primary_sections) >= 1
                ).OnlyEnforceIf(has_primary)
                
                # 専属業務がない場合は兼務業務も割り当てない
                for c_section in self.concurrent_sections:
                    self.model.Add(
                        self.concurrent_shifts[(staff, day, c_section)] == 0
                    ).OnlyEnforceIf(has_primary.Not())
                
        
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
                eligable_sections = [8]  # DIのセクションID 
            #name==0は医療安全・感染管理のみ
            elif staff == 0:
                eligable_sections = [14]  # 医療安全・感染管理のセクションID
            #floorが有効な値の場合
            else:
                if pd.notna(floor) and floor != '':
                    print(floor)
                    #floorごとに対応したprimary_sectionを追加
                    match floor:
                        case 1:#1-2
                            eligable_sections = [4,1]  # 1-2階、調剤室
                        case 2:#DI
                            #各スタッフの所属病棟を取得
                            if floor2 ==1:
                                eligable_sections = [8,1,4]  # DI、調剤室、1-2階
                            elif floor2 ==3:
                                eligable_sections = [8,1,5]  # DI、調剤室、3階
                            elif floor2 ==4:
                                eligable_sections = [8,1,6]  # DI、調剤室、4階
                            elif floor2 ==5:
                                eligable_sections = [8,1,7]  # DI、調剤室、5階
                            else:
                                eligable_sections = [8,1]  # DI、調剤室
                        case 3:#3
                            eligable_sections = [5,1]  # 3階、調剤室
                        case 4:#4
                            eligable_sections = [6,1]  # 4階、調剤室
                        case 5:#5
                            eligable_sections = [7,1]  # 5階、調剤室
                        case 6:#化療
                            eligable_sections = [9,1]  # 化療、調剤室
                        case 8:#調剤
                            eligable_sections = [1]  # 調剤室のみ
                        case 9:#外来
                            eligable_sections = [16]  # 外来
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
        - floor=1-2のうちから、月～土は3名選出する
        - スタッフ条件に「1人は必ず出勤にする」の対象者を追加する
        - 選出メンバーの内にnane :[7,10,11,14]を必ず1人含める
        
        """
        #月〜土はflor=1-2が3名必要
        for day in range(1, self.days + 1):
            # FLOOR_MAPPINGから'1-2'のセクションIDを直接取得
            floor_1_2_section_id = FLOOR_MAPPING.get('1-2')
                            
            assigned_staff = []
            required_staff = ["7","10","11","14"]
            required_staff_assigned = []
            for staff in self.staff.index:
                if floor_1_2_section_id in self.eligible_sections[staff]:
                    assigned_staff.append(self.shifts[(staff, day, floor_1_2_section_id)])
                    if staff in required_staff:
                        required_staff_assigned.append(self.shifts[(staff,day,floor_1_2_section_id)])
                        
            if assigned_staff:
                self.model.Add(
                    sum(assigned_staff) >=3
                )
            
            #必須メンバーから1人は必ず割り当てる
            if required_staff_assigned:
                self.model.Add(
                    sum(required_staff_assigned) >=1
                )
                print(required_staff_assigned)