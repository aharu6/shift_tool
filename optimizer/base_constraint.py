from abc import ABC, abstractmethod
from ortools.sat.python import cp_model
import datetime
import pandas as pd

class BaseConstraint(ABC):
    """制約条件の基底クラス"""
    def __init__(self, model: cp_model.CpModel, optimizer):
        self.model = model
        self.optimizer = optimizer
        self.staff = optimizer.staff
        self.days = optimizer.days
        self.year = optimizer.year
        self.month = optimizer.month
        self.holidays = optimizer.holidays
        self.shifts = optimizer.shifts#専属業務用の変数辞書
        self.concurrent_shifts = optimizer.concurrent_shifts  # 兼務業務用の変数辞書
        self.hope_list = optimizer.hope_list#休み・出勤希望リスト
        self.primary_sections = optimizer.primary_sections #TODO：役職。会議等で決まる出勤希望リストを別で作成する必要なケければ不要
        self.concurrent_sections = optimizer.concurrent_sections #TODO：役職。会議等で決まる出勤希望リストを別で作成する必要なケければ不要
        self.concurrent_sections = optimizer.concurrent_sections
        self.night_shifts = optimizer.night_shifts
        self.holiday_dates = self._build_holiday_date_set(self.holidays)
        self.hope_day_column_map = self._build_hope_day_column_map()
        self.get_eligible_sections = self._get_eligible_sections()

    def _build_holiday_date_set(self, holidays):
        holiday_dates = set()
        if not holidays:
            return holiday_dates

        for holiday in holidays:
            date_obj = None
            if isinstance(holiday, tuple) and holiday:
                date_obj = holiday[0]
            else:
                date_obj = holiday

            if hasattr(date_obj, "date"):
                date_obj = date_obj.date()

            if isinstance(date_obj, datetime.date):
                holiday_dates.add(date_obj)

        return holiday_dates

    def _build_hope_day_column_map(self):
        if self.hope_list is None or self.hope_list.empty:
            return {}

        day_column_map = {}
        for column in self.hope_list.columns:
            day_value = None

            if isinstance(column, int):
                day_value = column
            elif isinstance(column, str):
                stripped = column.strip()
                if stripped.isdigit():
                    day_value = int(stripped)
                elif stripped.endswith("日") and stripped[:-1].isdigit():
                    day_value = int(stripped[:-1])
            else:
                parsed = pd.to_datetime(column, errors="coerce")
                if pd.notna(parsed):
                    if parsed.year == self.year and parsed.month == self.month:
                        day_value = int(parsed.day)

            if day_value is not None and 1 <= day_value <= self.days and day_value not in day_column_map:
                day_column_map[day_value] = column

        return day_column_map

    def _get_date(self, day):
        return datetime.date(self.year, self.month, day)

    def _get_weekday(self, day):
        return self._get_date(day).weekday()

    def _is_holiday(self, day):
        return self._get_date(day) in self.holiday_dates

    def _get_hope_value(self, staff, day, default=7):#デフォルトは希望なしの7に設定
        if self.hope_list is None or self.hope_list.empty:
            return default

        if staff not in self.hope_list.index:
            return default

        staff_requests = self.hope_list.loc[staff]
        mapped_column = self.hope_day_column_map.get(day)
        if mapped_column is not None and mapped_column in staff_requests.index:
            value = staff_requests.loc[mapped_column]
            return value if pd.notna(value) else default

        fallback_index = day - 1
        if 0 <= fallback_index < len(staff_requests):
            value = staff_requests.iloc[fallback_index]
            return value if pd.notna(value) else default

        return default
        
    #  割り当て可能なセクション名の登録
    def _get_eligible_sections(self):
        """
        スタッフ条件.xlsxによる割り当て可能な業務名の制約
        出勤の際に割り当てる業務はFloor,もしくはfloor2に制約している業務のみとする。
        floor  、flor2,floor3の定義
        - 化療：化療と調剤室
        - 調剤室：調剤室のみ
        - DI: DIと調剤室,所属病棟
        - ただし、name=6はDIのみ
        - 外来：外来のみ
        - 1-2階：1-2階、調剤室、所属病棟
        - 3階：3階、調剤室、所属病棟
        - 4階：4階、調剤室、所属病棟
        - 5階：5階、調剤室、所属病棟
        - floor10：医療安全・感染管理のみ
        
        """
        eligable_sections_dict = {}
        
        for staff in self.staff.index:
            eligable_sections = []
            #staff.locの列を確認する
            floor = self.staff.loc[staff,'Floor']
            floor2 = self.staff.loc[staff,'Floor2']
            floor3 = self.staff.loc[staff,'Floor3'] 
            
            kanwa = self.staff.loc[staff,'緩和回診']
            shinhuzen = self.staff.loc[staff,'心不全回診']
            porifa = self.staff.loc[staff,'ポリファーマシーチーム'] #floor列以外で指定の所属チーム
            jishu = self.staff.loc[staff,'実習']
            nst_team = self.staff.loc[staff,'NST']
            masta_mentenance = self.staff.loc[staff,'マスター管理']
            ri = self.staff.loc[staff,'RI']
            
            #name==6は課長業務セクションのみ
            if staff == 6:
                eligable_sections.extend([23])  # 課長業務のセクションID
            #floorが有効な値の場合
            else:
                if pd.notna(floor) and floor != '':
                    #floorごとに対応したprimary_sectionを追加
                    match floor:
                        case 1:#1-2
                            eligable_sections.extend([4,1])  # 1-2階、調剤室
                        case 2:#DI
                            eligable_sections.extend([8,1])  # DI
                            #各スタッフの所属病棟を取得
                            if floor2 ==1:
                                eligable_sections.append(4)  # DI、調剤室、1-2階
                            elif floor2 ==2:
                                eligable_sections.append(8)
                            elif floor2 ==3:
                                eligable_sections.append(5)  # DI、調剤室、3階
                            elif floor2 ==4:
                                eligable_sections.append(6)  # DI、調剤室、4階
                            elif floor2 ==5:
                                eligable_sections.append(7)  # DI、調剤室、5階
                            elif floor2 ==6:
                                eligable_sections.append(9)  # DI、調剤室、化療

                        case 3:#3
                            eligable_sections.extend([5,1])  # 3階、調剤室
                            if floor2 ==1:
                                eligable_sections.append(4)  # 1-2階
                            elif floor2 ==2:
                                eligable_sections.append(8)  # DI
                            elif floor2 ==3:
                                eligable_sections.append(5)  # 3階
                            elif floor2 ==4:
                                eligable_sections.append(6)  # 4階
                            elif floor2 ==5:
                                eligable_sections.append(7)  # 5階
                            elif floor2 ==6:
                                eligable_sections.append(9)  # 化療

                            if floor3==11:
                                eligable_sections.append(3)  # 入退院センター
                        case 4:#4
                            eligable_sections.extend([6,1])  # 4階、調剤室
                            if floor2 ==1:
                                eligable_sections.append(4)  # 1-2階
                            elif floor2 ==3:
                                eligable_sections.append(5)  # 3階,primarysections
                            elif floor2 ==4:
                                eligable_sections.append(6)  # 4階,primarysections
                            elif floor2 ==5:
                                eligable_sections.append(7)  # 5階,primarysections
                            elif floor2 ==6:
                                eligable_sections.append(9)  # 化療,primarysections
                            if floor3==11:#floormapping
                                eligable_sections.append(3)  # 入退院センター,primarysections
                        case 5:#5
                            eligable_sections.extend([7,1])  # 5階、調剤室,primarysections
                        case 6:#化療
                            eligable_sections.extend([9,1])  # 化療、調剤室,primarysections
                            if floor2 ==8:
                                eligable_sections.append(1)  # 調剤室,primarysections
                            if floor3==11:
                                eligable_sections.append(3)  # 入退院センター,primarysections
                        case 8:#調剤
                            eligable_sections.extend([1])  # 調剤室,primarysections
                            if floor2==11:
                                eligable_sections.append(3)  # 入退院センター,primarysections
                        case 9:#外来
                            eligable_sections.extend([16])  # 外来,primarysections
                            if floor2==11:
                                eligable_sections.append(3)  # 入退院センター,primarysections
                        case 10:#部長（感染管理対応可能）
                            eligable_sections = [14]  # 医療安全・感染管理,primarysections
                        case _:
                            print(f"警告: スタッフ{staff}のFloorの値が不正です: {floor}")
                else:
                    print(f"警告: スタッフ{staff}のFloorの値が欠損しています。")
            #floor以外の条件を追加
                if pd.notna(kanwa) and kanwa==True:
                    eligable_sections.append(10) #緩和回診(専任)
                if pd.notna(shinhuzen) and shinhuzen==True:
                    eligable_sections.append(18) #心不全回診　兼務業務だが、所属可能として登録する
                if pd.notna(porifa) and porifa==True:
                    eligable_sections.append(11) #ポリファーマシーチーム
                if pd.notna(nst_team) and nst_team==True:
                    eligable_sections.append(19) #NST　兼務業務だが、所属可能として登録する
                if pd.notna(jishu) and jishu==True:
                    eligable_sections.append(20) #実習  
                if pd.notna(masta_mentenance) and masta_mentenance==True:
                    eligable_sections.append(21) #マスター管理
                if pd.notna(ri) and ri==True:
                    eligable_sections.append(22) #RI  兼務業務だが、所属可能として登録する
                        
            
            eligable_sections_dict[staff] = eligable_sections
            print(f"スタッフ{staff}の割り当て可能なセクション: {eligable_sections}")
            
        return eligable_sections_dict

    def _build_section_availability(
        self,
        section_configs,day,
        required_staff_12=None,required_staff_12_assigned=None,
        required_staff_12_available=None,
        di_eligible_staff_ids=None,porifa_staff_ids=None,
        remove_members=None,
        ):
        """
        - 休み希望の場合は除外する
        - 休み希望がない場合のみ配置可能スタッフとして割り当てる
        - スタッフ条件に基づく割り当て可能な業務のみを対象とする
        - 当直明けは配置しない
        - すでに別条件で休みが決まっている場合も配置しない
        - 配置可能なスタッフが休み希望や当直明け等で減少する場合の条件は以下の通り
            - 感染管理:人数は0人でも許容
            - 1-2F,3F,4F,5F:日祝日は0人、平日はavailable_staff_countが配置の最低人数とする
        - TODO:ポリファーマシー対応スタッフも休み希望が反映されているか
        - ポリファーマシー実施日において、対応スタッフは病棟の配置可能リストに含めない
        """
        for staff in self.staff.index:
            for section_name,config in section_configs.items():
                section_id = config['section_id']
                if section_id in self.get_eligible_sections[staff]:
                    #休み希望のチェック
                    check_day_off= config.get('check_day_off',False)
                    staff_hope = self._get_hope_value(staff,day,default=7)
                    is_day_off_request = (staff_hope == 0 or staff_hope==3 or staff_hope==6)#休み希望
                    #当直明けの日は配置しない、配置可能メンバーとして登録しない

                    #当日・当該セクションに配置可能かをBoolVarで管理（休み希望/当直明けを厳密反映）
                    is_available_var = self.model.NewBoolVar(
                        f'is_available_{section_name}_{staff}_{day}'
                    )
                    
                    
                    if check_day_off and is_day_off_request:
                        self.model.Add(is_available_var == 0)#休み希望(育休、研修含む)がある場合は配置不可
                    elif day > 1:#当日が当直明け(17)かをチェック
                        today_oncall_next = self.shifts[(staff, day, 17)]
                        self.model.Add(is_available_var == 0).OnlyEnforceIf(today_oncall_next)#当直明けの場合は配置不可
                        self.model.Add(is_available_var == 1).OnlyEnforceIf(today_oncall_next.Not())#当直明けでない場合は配置可能
                    else:
                        self.model.Add(is_available_var == 1)#それ以外は配置可能
                    #病棟業務のセクションには配置しない,section_idのうち、17の当直明けまたは0の休み以外のセクションが病棟業務とする
                    #検証するself.shifts[(staff,day,section_id)] のsection_idには担当可能な病棟業務・休み・当直明けが含まれる
                    #配置不可としたいのは病棟業務のみなので、section_idより当直明けと休みを除外する
                    if section_id != 17 and section_id != 0:
                        set_section_id = section_id
                        self.model.Add(self.shifts[(staff, day, set_section_id)] <= is_available_var)

                    config['assigned_list'].append(self.shifts[(staff, day, section_id)])
                    config['available_list'].append(is_available_var)
                    if required_staff_12 is not None and required_staff_12_assigned is not None and required_staff_12_available is not None:
                        if section_name == '1-2F' and staff in required_staff_12:
                            required_staff_12_assigned.append(self.shifts[(staff, day, section_id)])
                            required_staff_12_available.append(is_available_var)
                    if di_eligible_staff_ids is not None and section_name == 'DI':
                        di_eligible_staff_ids.append(staff)
                    if porifa_staff_ids is not None and section_name == 'ポリファーマシー':
                        porifa_staff_ids.append(staff)
        print(f"day{day}のセクションごとの配置可能スタッフ数{section_configs}")
        return section_configs
        
    @abstractmethod
    def apply(self):
        """制約を適用する"""
        pass
    
    