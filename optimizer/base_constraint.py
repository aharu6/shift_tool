from abc import ABC, abstractmethod
from ortools.sat.python import cp_model
import datetime
import pandas as pd
import re
from config.sections import PRIMARY_SECTIONS

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
        self.previous_year_december_30_staff = set(
            getattr(optimizer, 'previous_year_december_30_staff', set())
        )#30日勤務者の初期化
        self.previous_december_31_staff = set(
            getattr(optimizer, 'previous_december_31_staff', set())
        )#31日勤務者の初期化
        self.previous_january_1_staff = set(
            getattr(optimizer,'previous_january_1_staff',set())
        )#1月1日勤務者の初期化
        self.previous_january_2_staff = set(
            getattr(optimizer,'previous_january_2_staff',set())
        )#1月2日勤務者の初期化
        self.previous_january_3_staff = set(
            getattr(optimizer,'previous_january_3_staff',set())
        )#1月3日勤務者の初期化
        self.holiday_dates = self._build_holiday_date_set(self.holidays)
        self.hope_day_column_map = self._build_hope_day_column_map()
        self.debug_enabled = bool(getattr(self.optimizer, 'debug_enabled', False))

        if hasattr(self.optimizer, '_eligible_sections_cache'):
            self.get_eligible_sections = self.optimizer._eligible_sections_cache
        else:
            self.get_eligible_sections = self._get_eligible_sections()
            self.optimizer._eligible_sections_cache = self.get_eligible_sections

        if hasattr(self.optimizer, '_ri_priority_map_cache'):
            self.ri_priority_map = self.optimizer._ri_priority_map_cache
        else:
            self.ri_priority_map = self._build_ri_priority_map()
            self.optimizer._ri_priority_map_cache = self.ri_priority_map

    def _is_enabled_value(self, value):
        if pd.isna(value):
            return False
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0

        text = str(value).strip().lower()
        if text in {'', '0', 'false', 'f', 'no', 'n', 'off', 'なし', '無'}:
            return False
        return True

    def _parse_ri_priority(self, value, default_priority=99):
        if pd.isna(value):
            return default_priority

        if isinstance(value, (int, float)):
            parsed = int(value)
            return parsed if parsed >= 1 else default_priority

        text = str(value).strip()
        if text == '':
            return default_priority

        if text.isdigit():
            parsed = int(text)
            return parsed if parsed >= 1 else default_priority

        matched = re.search(r'(\d+)', text)
        if matched:
            parsed = int(matched.group(1))
            return parsed if parsed >= 1 else default_priority

        return default_priority

    def _build_ri_priority_map(self):
        ri_priority_map = {}
        has_ri_priority_column = 'RI優先度' in self.staff.columns

        for staff in self.staff.index:
            ri_enabled = self._is_enabled_value(self.staff.loc[staff, 'RI'])
            if not ri_enabled:
                continue

            raw_priority = self.staff.loc[staff, 'RI優先度'] if has_ri_priority_column else None
            ri_priority_map[staff] = self._parse_ri_priority(raw_priority)

        return ri_priority_map

    def get_ri_priority(self, staff):
        return self.ri_priority_map.get(staff, 99)

    def _get_staff_column_value(self, staff, column):
        """staff DataFrameに列が存在しない場合はNaNを返す"""
        if column not in self.staff.columns:
            return pd.NA
        return self.staff.loc[staff, column]#TODO:数字と文字の表記揺れを統一

    def _build_holiday_date_set(self, holidays):
        """祝日の日付セットを構築するメソッド。
        12/30,12/31,1/2,1/3も祝日として扱う
        
        Args:
            holidays (list): 祝日を表すオブジェクトのリスト。各要素はdatetime.date、datetime.datetime、またはタプルである可能性がある。

        Returns:
            set: 祝日の日付(datetime.date)のセット。
        """
        holiday_dates = set()

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
            
        # 12/30, 12/31, 1/2, 1/3も祝日として追加
        special_holidays = {
            12:{30,31},
            1:{2,3}
        }
        for day in special_holidays.get(self.month, set()):
            holiday_dates.add(datetime.date(self.year, self.month, day))
            
        if not holidays:
            return holiday_dates
        print(f"祝日:{holiday_dates}")
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

    def _is_previous_year_december_30_staff(self, staff, day):
        return (
            self.month == 12
            and day == 30
            and staff in self.previous_year_december_30_staff
        )

    def _is_previous_december_31_staff(self,staff,day):
        return (
            self.month == 12
            and day == 31
            and staff in self.previous_december_31_staff
        )
    def _is_previous_january_1_staff(self, staff, day):
        return (
            self.month == 1
            and day == 1
            and staff in self.previous_january_1_staff
        )
    def _is_previous_january_2_staff(self, staff, day):
        return (
            self.month == 1
            and day == 2
            and staff in self.previous_january_2_staff
        )
    def _is_previous_january_3_staff(self, staff, day):
        return (
            self.month == 1
            and day == 3
            and staff in self.previous_january_3_staff
        )
    def _is_holiday(self, day):
        return self._get_date(day) in self.holiday_dates

    def _get_hope_value(self, staff, day, default=7):
        if self.debug_enabled:
            print(f"Getting hope value for Staff: {staff}, Day: {day}")

        if self.hope_list is None or self.hope_list.empty:
            return default

        if staff not in self.hope_list.index:
            return default

        staff_requests = self.hope_list.loc[staff]
        mapped_column = self.hope_day_column_map.get(day)

        def _is_valid(value):
            if isinstance(value, (list, tuple)):#リスト形式、タプル形式の場合は有効とみなす
                return True
            return pd.notna(value)

        if mapped_column is not None and mapped_column in staff_requests.index:
            value = staff_requests.loc[mapped_column]
            if self.debug_enabled:
                print(f"Staff: {staff}, Day: {day}, Hope Value: {value}")
                print(f"Is Valid: {_is_valid(value)}")
            return value if _is_valid(value) else default

        fallback_index = day - 1
        if 0 <= fallback_index < len(staff_requests):
            value = staff_requests.iloc[fallback_index]
            if self.debug_enabled:
                print(f"Staff: {staff}, Day: {day}, Fallback Hope Value: {value}")
                print(f"Is Valid: {_is_valid(value)}")
            return value if _is_valid(value) else default

        return default
    
    def _hope_matches(self, hope_value, targets):
        """希望値が単一値または複数値のいずれでも対象値に一致するか判定する。"""
        if isinstance(hope_value, (list, tuple, set)):
            return any(value in targets for value in hope_value)
        return hope_value in targets
    
    #  割り当て可能なセクション名の登録
    def _get_eligible_sections(self):
        """
        スタッフ条件.xlsxによる割り当て可能な業務名の制約
        出勤の際に割り当てる業務はFloor,もしくはfloor2に制約している業務のみとする。
        floor  、flor2,floor3の定義
        - 化療：化療と調剤室
        - 調剤室：調剤室のみ
        - DI: DIと調剤室,所属病棟
        - 外来：外来のみ
        - 1-2階：1-2階、調剤室、所属病棟
        - 3階：3階、調剤室、所属病棟
        - 4階：4階、調剤室、所属病棟
        - 5階：5階、調剤室、所属病棟
        - floor10：部長
        - floor11：入退院センター
        - floor12：RI
        - floor13:課長
        - floor14:医療安全・感染管理
        - RI優先度:RI配置スタッフの優先度
        - 明け: 全員
        - 研修：全員
        - 学会：全員   
        
        
        """
        eligable_sections_dict = {}
        
        for staff in self.staff.index:
            eligable_sections = []
            if self._is_enabled_value(
                self._get_staff_column_value(staff, '休職')
            ):
                eligable_sections_dict[staff] = eligable_sections
                continue

            #staff.locの列を確認する（列が存在しない場合はNaN扱い）
            floor = self._get_staff_column_value(staff, 'Floor')
            floor2 = self._get_staff_column_value(staff, 'Floor2')
            floor3 = self._get_staff_column_value(staff, 'Floor3')

            kanwa = self._get_staff_column_value(staff, '緩和回診')
            shinhuzen = self._get_staff_column_value(staff, '心不全回診')
            porifa = self._get_staff_column_value(staff, 'ポリファーマシーチーム') #floor列以外で指定の所属チーム
            jishu = self._get_staff_column_value(staff, '実習')
            nst_team = self._get_staff_column_value(staff, 'NST')
            masta_mentenance = self._get_staff_column_value(staff, 'マスター管理')
            ri = self._get_staff_column_value(staff, 'RI')
            safety_wg = self._get_staff_column_value(staff, '医薬品安全使用WG')
            dem_round = self._get_staff_column_value(staff, '認知症せん妄ラウンド')
            infection_control = self._get_staff_column_value(staff, '感染管理,AST')
            
            #floorが有効な値の場合
            if pd.notna(floor) and floor != '':
                #floorごとに対応したprimary_sectionを追加
                match floor:
                    case 1:#1-2
                        eligable_sections.append(4)  # 1-2階
                    case 2:#DI
                        eligable_sections.append(8)  # DI　
                    case 3:#3
                        eligable_sections.append(5)  # 3階
                    case 4:#4
                        eligable_sections.append(6)  # 4階
                    case 5:#5
                        eligable_sections.append(7)  # 5階,primarysections
                    case 6:#化療
                        eligable_sections.append(9)  # 化療,primarysections
                    case 8:#調剤
                        eligable_sections.append(1)  # 調剤室,primarysections
                    case 9:#外来
                        eligable_sections.append(16)  # 外来,primarysections
                    case 10:#部長
                        eligable_sections.append(26)  # 部長,primarysections
                    case 11:#入退院センター
                        eligable_sections.append(3)  # 入退院センター,primarysections
                    case 12:#RI
                        eligable_sections.append(22)  # RI,primarysections
                    case 13:#課長
                        eligable_sections.append(25)#課長,primarysections
                    case 14:#医療安全・感染管理
                        eligable_sections.append(14)#医療安全・感染管理
                    case _:
                        print(f"警告: スタッフ{staff}のFloorの値が不正です: {floor}")
                
            else:
                print(f"警告: スタッフ{staff}のFloorの値が欠損しています。")
            
            #floor2が有効な値の場合
            if pd.notna(floor2) and floor2 != '':
                match floor2:
                    case 1:#1-2
                        eligable_sections.append(4)  # 1-2階
                    case 2:#DI
                        eligable_sections.append(8)  # DI　
                    case 3:#3
                        eligable_sections.append(5)  # 3階
                    case 4:#4
                        eligable_sections.append(6)  # 4階
                    case 5:#5
                        eligable_sections.append(7)  # 5階,primarysections
                    case 6:#化療
                        eligable_sections.append(9)  # 化療,primarysections
                    case 8:#調剤
                        eligable_sections.append(1)  # 調剤室,primarysections
                    case 9:#外来
                        eligable_sections.append(16) # 外来,primarysections
                    case 10:#部長
                        eligable_sections.append(26)
                    case 11:#入退院センター
                        eligable_sections.append(3) #入退院センター,primarysections
                    case 12:#RI
                        eligable_sections.append(22) #RI,primarysections
                    case 13:#課長
                        eligable_sections.append(25) #課長,primarysections
                    case 14:#医療安全・感染管理
                        eligable_sections.append(14)#医療安全・感染管理,primarysections
                    case _:
                        print(f"警告: スタッフ{staff}のFloor2の値が不正です: {floor2}")
            #floor3が有効な値の場合
            if pd.notna(floor3) and floor3 != '':
                match floor3:
                    case 1:#1-2
                        eligable_sections.append(4)  # 1-2階
                    case 2:#DI
                        eligable_sections.append(8)  # DI　
                    case 3:#3
                        eligable_sections.append(5)  # 3階
                    case 4:#4
                        eligable_sections.append(6)  # 4階
                    case 5:#5
                        eligable_sections.append(7)  # 5階,primarysections
                    case 6:#化療
                        eligable_sections.append(9)  # 化療,primarysections
                    case 8:#調剤
                        eligable_sections.append(1)  # 調剤室,primarysections
                    case 9:#外来
                        eligable_sections.append(16) # 外来,primarysections
                    case 10:#部長
                        eligable_sections.append(26)
                    case 11:#入退院センター
                        eligable_sections.append(3) #入退院センター,primarysections
                    case 12:#RI
                        eligable_sections.append(22) #RI,primarysections
                    case 13:#課長
                        eligable_sections.append(25) #課長,primarysections
                    case 14:#医療安全・感染管理
                        eligable_sections.append(14)#医療安全・感染管理,primarysections
                    case _:
                        print(f"警告: スタッフ{staff}のFloor3の値が不正です: {floor3}")

            
        #floor以外の条件を追加
            if pd.notna(kanwa) and kanwa==True:
                eligable_sections.append(10) #緩和回診(専任)
            if pd.notna(shinhuzen) and shinhuzen==True:
                eligable_sections.append(18) #心不全回診　兼務業務だが、所属可能として登録する
            if pd.notna(porifa) and porifa==True:
                eligable_sections.append(11) #ポリファーマシーチーム
            if pd.notna(nst_team) and nst_team==True:
                eligable_sections.append(19) #NST　兼務業務だが、所属可能として登録する用
            if pd.notna(jishu) and jishu==True:
                eligable_sections.append(20) #実習  
            if pd.notna(masta_mentenance) and masta_mentenance==True:
                eligable_sections.append(21) #マスター管理
            if self._is_enabled_value(ri):
                eligable_sections.append(22) #RI  兼務業務だが、所属可能として登録する用
            if pd.notna(safety_wg) and safety_wg==True:
                eligable_sections.append(24) #医薬品安全使用WG  兼務業務だが、所属可能として登録する用
            if pd.notna(dem_round) and dem_round==True:
                eligable_sections.append(12) #認知症せん妄ラウンド  兼務業務だが、所属可能として登録する用
            if pd.notna(infection_control) and infection_control==True:
                eligable_sections.append(27) #感染管理,AST
            
            #休みは全てのスタッフに可能性があるので、割り当て
            eligable_sections.append(0) #休み
            
            #明けは全てのスタッフに可能性があるので、割り当て
            eligable_sections.append(17) #明け
            #研修は全てのスタッフに可能性があるので、割り当て
            eligable_sections.append(28) #研修
            #学会
            eligable_sections.append(29) #学会
            
            eligable_sections_dict[staff] = eligable_sections
            if self.debug_enabled:
                print(f"スタッフ{staff}の割り当て可能なセクション: {eligable_sections}")
            
        return eligable_sections_dict

    #割り当て可能な兼務業務だけのセクションを取得
    def _get_eligible_concurrent_sections(self):
        eligible_concurrent_sections_dict = {}
        for staff in self.staff.index:
            eligible_concurrent_sections = []
            if self._is_enabled_value(
                self._get_staff_column_value(staff,'休職')
            ):
                eligible_concurrent_sections_dict[staff] = eligible_concurrent_sections
                continue
            # ここに他の兼務業務の判定を追加
            kanwa = self._get_staff_column_value(staff, '緩和回診')
            shinhuzen = self._get_staff_column_value(staff, '心不全回診')
            porifa = self._get_staff_column_value(staff, 'ポリファーマシーチーム') #floor列以外で指定の所属チーム
#            jishu = self._get_staff_column_value(staff, '実習')専属業務のためスキップ
            nst_team = self._get_staff_column_value(staff, 'NST')
            masta_mentenance = self._get_staff_column_value(staff, 'マスター管理')
            ri = self._get_staff_column_value(staff, 'RI')
            safety_wg = self._get_staff_column_value(staff, '医薬品安全使用WG')
            dem_round = self._get_staff_column_value(staff, '認知症せん妄ラウンド')
            infection_control = self._get_staff_column_value(staff, '感染管理,AST')
            
            if pd.notna(kanwa) and kanwa==True:
                eligible_concurrent_sections.append(5)
            if pd.notna(shinhuzen) and shinhuzen==True:
                eligible_concurrent_sections.append(1)
            if pd.notna(porifa) and porifa==True:
                eligible_concurrent_sections.append(10)
            if pd.notna(nst_team) and nst_team==True:
                eligible_concurrent_sections.append(2)
            if pd.notna(masta_mentenance) and masta_mentenance==True:
                eligible_concurrent_sections.append(16)
            if pd.notna(ri) and ri==True:
                eligible_concurrent_sections.append(4)
            if pd.notna(safety_wg) and safety_wg==True:
                eligible_concurrent_sections.append(8)
            if pd.notna(dem_round) and dem_round==True:
                eligible_concurrent_sections.append(12)
            if pd.notna(infection_control) and infection_control==True:
                eligible_concurrent_sections.append(15)
            
            eligible_concurrent_sections_dict[staff] = eligible_concurrent_sections
            
        return eligible_concurrent_sections_dict
    
    def _is_prev_year_end_worked_value(self, shift):
        #空白・◎・⚪︎・専属業務名は出勤として扱う　==1、休み・指・有・夏は出勤として扱わない == 0
        if pd.isna(shift):
            return True
        text = str(shift).strip()
        if text in {"", "◎", "⚪︎"} or text in PRIMARY_SECTIONS.values():
            return True
        if text in {"休", "指", "有", "夏", "研", "学"}:
            return False
        return True

    def _cleaning_prev_year_end_shift(self, prev_year_end_shift,day):
        # 前年度年末年始のシフト情報をクリーニングする処理を実装
        #dayごとに作成する
        if prev_year_end_shift is None:
            return {}

        cleaned = {}
        day_key = str(day)
        if isinstance(prev_year_end_shift, pd.DataFrame):
            #DataFrame（Name列＋日付列）の場合は行単位（スタッフ単位）で判定する
            if prev_year_end_shift.empty or 'Name' not in prev_year_end_shift.columns:
                return {}
            day_columns = [col for col in prev_year_end_shift.columns if col != 'Name']
            if day_key not in day_columns:
                return {}
            for _, row in prev_year_end_shift.iterrows():
                staff = row['Name']
                worked = self._is_prev_year_end_worked_value(row[day_key])
                cleaned[staff] = 1 if worked else 0
        else:
            for staff, shift in prev_year_end_shift.items():
                if day_key not in shift:
                    continue
                cleaned[staff] = 1 if self._is_prev_year_end_worked_value(shift[day_key]) else 0

        print(f"クリーニング後の前年度年末年始シフト: {cleaned}")
        return cleaned
    
    def _build_section_availability(
        self,
        section_configs,day,year,
        required_staff_12=None,required_staff_12_assigned=None,
        required_staff_12_available=None,
        di_eligible_staff_ids=None,porifa_staff_ids=None,
        chemo_staff_ids=None,
        remove_members=None,
        ri_staff_ids=None,
        safety_wg_staff_ids=None,
        dem_round_staff_ids=None,
        heart_team_staff_ids=None,
        prev_year_end_shift=None,
        infection_control_staff_ids=None,
        infection_control_pm_staff_ids=None,
        ):
        """
        - 休み希望の場合は除外する
        - 研修希望の場合は除外する
        - 学会希望の場合は除外する
        - 休職TRUEのスタッフは配置しない
        - 休み希望がない場合のみ配置可能スタッフとして割り当てる
        - スタッフ条件に基づく割り当て可能な業務のみを対象とする
        - 当直明けは配置しない
        - すでに別条件で休みが決まっている場合も配置しない
        - 配置可能なスタッフが休み希望や当直明け等で減少する場合の条件は以下の通り
            - 感染管理:人数は0人でも許容
            - 1-2F,3F,4F,5F:日祝日は0人、平日はavailable_staff_countが配置の最低人数とする
        - ポリファーマシー実施日において、対応スタッフは病棟の配置可能リストに含めない
        - 作成シフトが12月または1月の場合、対象期間に前年度年末年始にシフトがあったスタッフは配置対象から除外する
        """
        prev_year_end_shift = self._cleaning_prev_year_end_shift(prev_year_end_shift,day)
        for staff in self.staff.index:
            #休職TRUEのスタッフは配置しない
            if self._is_enabled_value(
                self._get_staff_column_value(staff, '休職')
            ):
                continue
            for section_name,config in section_configs.items():
                section_id = config['section_id']
                if section_id in self.get_eligible_sections[staff]:
                    #当日のスタッフ希望    
                    staff_hope = self._get_hope_value(staff,day,default=7)
                    
                    #休み希望と研修希望と学会希望のチェック
                    check_day_off= config.get('check_day_off',False)
                    is_day_off_request = self._hope_matches(staff_hope, {0, 3, 5, 6, 11,})#休み希望 と研修希望 と学会希望
                    
                    #当直明けの日は配置しない、配置可能メンバーとして登録しない

                    #当日・当該セクションに配置可能かをBoolVarで管理（休み希望/当直明けを厳密反映）
                    is_available_var = self.model.NewBoolVar(
                        f'is_available_{section_name}_{staff}_{day}'
                    )
                    
                    
                    if check_day_off and is_day_off_request:
                        #休み希望(育休、研修,学会含む)がある場合は配置不可
                        #1-2F必須メンバーや、ポリファーマシー、化療、RIなどの兼務業務の配置可能スタッフは、休み希望がある場合は配置不可とする
                        self.model.Add(is_available_var == 0)
                    elif day == 1 and staff in getattr(self.optimizer, 'prev_month_oncall_staff_ids', set()):
                        # 前月末の当直担当者は月初1日も当直明けとして扱い、配置不可にする
                        self.model.Add(is_available_var == 0)
                    elif day > 0:
                        # 当日が当直明け(17)かをチェック　当日が当直の翌日かを判定する
                        today_oncall_next = self.shifts[(staff, day, 17)]
                        self.model.Add(is_available_var == 0).OnlyEnforceIf(today_oncall_next)#当直明けの場合は配置不可
                        self.model.Add(is_available_var == 1).OnlyEnforceIf(today_oncall_next.Not())#当直明けでない場合は配置可能
                    else:
                        self.model.Add(is_available_var == 1)#それ以外は配置可能
                    #病棟業務のセクションには配置しない,section_idのうち、17の当直明けまたは0の休み以外のセクションが病棟業務とする
                    #検証するself.shifts[(staff,day,section_id)] のsection_idには担当可能な病棟業務・休み・当直明けが含まれる
                    #配置不可としたいのは専属業務のみなので、section_idより当直明けと休みを除外する
                    if section_id != 17 and section_id != 0:
                        set_section_id = section_id
                        self.model.Add(self.shifts[(staff, day, set_section_id)] <= is_available_var)
                    
                    chemo_section_id = 9
                    floors = {
                        self.staff.loc[staff,'Floor'],
                        self.staff.loc[staff,'Floor2'],
                        self.staff.loc[staff,'Floor3'],
                    }
                    #get_eligible_sectionsを使用してFloor判定時は、Floor_mapping.pyではなく、sections.pyのフロア番号を参照する
                    print(f"staff {staff} floors: {floors}")
                    is_kacho_chemo = (
                        (chemo_section_id in self.get_eligible_sections.get(staff,[]))
                        and (25 in floors)
                        and (self.staff.loc[staff, '主任以上']==True)
                    )
                    is_chemo = (chemo_section_id in self.get_eligible_sections.get(staff,[])
                                and (9 in floors))#単純な化学療法室配置可能スタッフ
                    print(f"staff {staff} is chemo: {is_chemo}, is_kacho_chemo: {is_kacho_chemo}")
                    #曜日ごとに配置人数が変わる調剤室
                    #平日からは化療かつ課長のスタッフを除外してavailable_listをを更新する
                    if section_name == "調剤室_月木_非祝日":
                        if not is_kacho_chemo:
                            config['assigned_list'].append(self.shifts[(staff, day, section_id)])
                            config['available_list'].append(is_available_var)
                            config.setdefault('available_staff', []).append(staff)
                    elif section_name == "調剤室_金_非祝日":
                        if not is_kacho_chemo:
                            config['assigned_list'].append(self.shifts[(staff, day, section_id)])
                            config['available_list'].append(is_available_var)
                            config.setdefault('available_staff', []).append(staff)
                    elif section_name == "調剤室_土":
                        #化学療法室かつ調整室配置可能スタッフは化学療法で配置してweekly表で調剤室に結合する
                        if not is_chemo:
                            config['assigned_list'].append(self.shifts[(staff, day, section_id)])
                            config['available_list'].append(is_available_var)
                            config.setdefault('available_staff', []).append(staff)
                    elif section_name == "調剤室_日祝":
                        # 当日の出勤希望がない&日曜出勤FALSEのスタッフは日曜祝日配置から除外する
                        if self.debug_enabled:
                            print(f"day{day}当日の日曜出勤{self.staff.loc[:, '日曜出勤']}")
                        can_work_sunday = self.staff.loc[staff,'日曜出勤']==True
                        has_work_request = self._hope_matches(
                            self._get_hope_value(staff, day, default=7), {1}
                        )
                        
                        if not can_work_sunday and not has_work_request:
                            continue
                        else:
                            config['assigned_list'].append(self.shifts[(staff, day, section_id)])
                            config['available_list'].append(is_available_var)
                            config.setdefault('available_staff', []).append(staff)
                    else:
                        config['assigned_list'].append(self.shifts[(staff, day, section_id)])
                        config['available_list'].append(is_available_var)
                        config.setdefault('available_staff', []).append(staff)
                    
                    
                    if required_staff_12 is not None and required_staff_12_assigned is not None and required_staff_12_available is not None:
                        """休み希望はスキップ"""
                        if self.debug_enabled:
                            print(f"Day{day}: staff {staff} required_staff_12 check")
                            print(f"staff{staff} section {section_name}")
                        if check_day_off and is_day_off_request:#休み希望・研修希望・学会希望がある場合は配置不可
                            pass
                        #当直明けの除外はis_available_var/section_idの制約(assigned<=is_available_var)側で既に反映されるためここでは判定しない
                        elif section_name == '1-2F' and staff in required_staff_12:
                            required_staff_12_assigned.append(self.shifts[(staff, day, section_id)])
                            required_staff_12_available.append(is_available_var)
                            if self.debug_enabled:
                                print(f"Day{day}: staff {staff} is in required_staff_12 for section '1-2F'")
                    if di_eligible_staff_ids is not None and section_name == 'DI':
                        if check_day_off and is_day_off_request:#休み希望・研修希望・学会希望がある場合は配置不可
                            pass
                        else:
                            di_eligible_staff_ids.append(staff)
                    if porifa_staff_ids is not None and section_name == 'ポリファーマシー':
                        if check_day_off and is_day_off_request:#休み希望・研修希望・学会希望がある場合は配置不可
                            pass
                        else:
                            porifa_staff_ids.append(staff)
                    if ri_staff_ids is not None and section_name == 'RI':
                        if check_day_off and is_day_off_request:#休み希望・研修希望・学会希望がある場合は配置不可
                            pass
                        else:
                            ri_staff_ids.append(staff)
                    if safety_wg_staff_ids is not None and section_name == '医薬品安全使用WG':
                        if check_day_off and is_day_off_request:#休み希望・研修希望・学会希望がある場合は配置不可
                            pass
                        else:
                            safety_wg_staff_ids.append(staff)
                    if dem_round_staff_ids is not None and section_name == '認知症せん妄ラウンド':
                        if check_day_off and is_day_off_request:#休み希望・研修希望・学会希望がある場合は配置不可
                            pass
                        else:
                            dem_round_staff_ids.append(staff)
                    if heart_team_staff_ids is not None and section_name == '心不全回診':
                        if check_day_off and is_day_off_request:#休み希望・研修希望・学会希望がある場合は配置不可
                            pass
                        else:
                            heart_team_staff_ids.append(staff)  
                    if infection_control_staff_ids is not None and section_name == '感染管理,AST':
                        """
                        PM出勤のスタッフがいれば優先的に配置（別リストで収集）
                        PM出勤のスタッフが他にいなければそのまま感染管理,AST=TRUEのスタッフを配置する(別リストで収集)
                        """                        
                        if check_day_off and is_day_off_request:#休み希望・研修希望・学会希望がある場合は配置不可
                            pass
                        else:
                            infection_control_staff_ids.append(staff)
                            if staff_hope == 10:
                                print(f"Day{day}: 感染管理,AST PM出勤希望スタッフ {staff} を優先的に配置")
                                infection_control_pm_staff_ids.append(staff)
        if self.debug_enabled:
            print(f"day{day}のセクションごとの配置可能スタッフ数{section_configs}")
        return section_configs
        
    @abstractmethod
    def apply(self):
        """制約を適用する"""
        pass

