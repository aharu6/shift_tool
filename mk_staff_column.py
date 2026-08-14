from datetime import datetime, timedelta
import pandas as pd
from config.floor_mapping import FLOOR_MAPPING
from staff_name_matching import normalize_name_index


class MkStafflist:
    def __init__(self,shift_requests_primary,shift_requests_concurrent,shift_results_oncall,staff_list_pass,year,month):
        self.shift_requests_primary = shift_requests_primary
        self.shift_requests_concurrent = shift_requests_concurrent
        self.shift_results_oncall = shift_results_oncall
        self.staff_list_pass = staff_list_pass
        self.year = year
        self.month = month
        self.days = self._get_days_in_month()   
        self.staff = pd.read_excel(self.staff_list_pass, sheet_name="member_list", skiprows=1)
        self.staff = normalize_name_index(
            self.staff,
            source_label="スタッフ条件.xlsx",
            name_column="Name",
            allow_index_fallback=False,
        )
        #floorカラムを数値IDに変換
        if 'Floor' in self.staff.columns:
            self.staff['Floor'] = self.staff['Floor'].map(FLOOR_MAPPING)
    
    def _get_days_in_month(self):
        if self.month ==12:
            next_month =datetime(self.year +1,1,1)
        else:
            next_month =datetime(self.year,self.month +1,1)
        last_day = (next_month - timedelta(days=1)).day
        return last_day
    
    def make_stafflist_primary(self):
        #専属業務のスタッフリストをここで作成
        #人数分、日付ぶんの空リストを作成[staff_num,day,-)]==[スタッフ名、日付、シフト]
        for staff in self.staff.index:
            for day in range(1,self.days +1):
                self.shift_requests_primary.append([staff,day,'-'])
                
        return self.shift_requests_primary
    
    def make_stafflist_concurrent(self):
        #兼務業務のスタッフリストをここで作成
        pass
    
    def make_stafflist_oncall(self):
        #当直業務のスタッフリストをここで作成
        pass