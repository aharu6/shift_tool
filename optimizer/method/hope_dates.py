import datetime
import re

import pandas as pd


def build_hope_day_column_map(columns, year, month, days):
    """希望表の日付列を対象月初からの通し日番号に対応付ける。"""
    day_column_map = {}
    for column in columns:
        day_value = None

        if isinstance(column, int):
            day_value = column
        elif isinstance(column, str):
            stripped = column.strip()
            if stripped.isdigit():
                day_value = int(stripped)
            elif stripped.endswith("日") and stripped[:-1].isdigit():
                day_value = int(stripped[:-1])
            elif month == 12 and days > 31 and re.fullmatch(r"[1-3]\.1", stripped):
                day_value = 31 + int(stripped[0])
        else:
            parsed = pd.to_datetime(column, errors="coerce")
            if pd.notna(parsed):
                start_date = datetime.date(year, month, 1)
                day_value = (parsed.date() - start_date).days + 1

        if day_value is not None and 1 <= day_value <= days:
            if day_value in day_column_map:
                if month == 12 and day_value > 31:
                    raise ValueError(f"希望表の日付列が重複しています: 日付番号 {day_value}")
                continue
            day_column_map[day_value] = column

    return day_column_map
