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
        
        
    @abstractmethod
    def apply(self):
        """制約を適用する"""
        pass