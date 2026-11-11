import datetime
from datetime import datetime, timedelta
import pandas as pd
import numbers
from config.floor_mapping import FLOOR_MAPPING


class BaseShiftOptimizer:
    def _get_days_in_month(self):
        """
        対象月の日数を取得するメソッド
        Returns:
            対象月の日数
        """
        if self.month ==12:
            next_month =datetime(self.year +1,1,1)
        else:
            next_month =datetime(self.year,self.month +1,1)
        last_day = (next_month - timedelta(days=1)).day
        return last_day
    
    
    def get_primary_shift(self, staff, day, section):
        """
        staffの専属業務シフト変数を取得
        
        Args:
            staff: スタッフのインデックス
            day: 日付
            section: 専属業務のセクション
            
        Returns:
            専属業務シフト変数（存在する場合）、存在しない場合はNone
        """
        return self.shifts.get((staff, day, section))

    @staticmethod
    def _normalize_boolean_column(values):
        """ブール列を正規化する。

        Args:
            values (pd.Series): ブール列

        Returns:
            pd.Series: 正規化されたブール列
        
        """
        # 文字列として解釈される「偽」の値のセット
        false_values = {
            '', '0', 'false', 'f', 'no', 'n', 'off',
            'なし', '無', '不可', '当直不可', '×',
        }

        def normalize(value):
            if pd.isna(value):
                return False
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return value != 0
            return str(value).strip().lower() not in false_values

        return values.map(normalize)
    
    @staticmethod
    def _normalize_attendance_mark(value):
        """絵文字の除去と文字列の正規化
        二重丸の正規化"""
        if pd.isna(value):
            return ""
        return (
            str(value)
            .replace("\ufe0f","")
            .replace("\ufe0e","")
            .strip()
        )
    
    @staticmethod
    def _normalize_floor_column(values):
        """Floor列の文字列ラベルと数値IDを内部IDへ正規化する。"""
        valid_ids = set(FLOOR_MAPPING.values())

        def normalize(value):
            if pd.isna(value) or value == '':
                return pd.NA
            if isinstance(value, str):
                label = value.strip()
                if label in FLOOR_MAPPING:
                    return FLOOR_MAPPING[label]
                try:
                    numeric_value = float(label)
                except ValueError:
                    return pd.NA
            else:
                numeric_value = value

            if isinstance(numeric_value, numbers.Real) and float(numeric_value).is_integer():
                numeric_id = int(numeric_value)
                return numeric_id if numeric_id in valid_ids else pd.NA
            return pd.NA

        return values.map(normalize)
