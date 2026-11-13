import datetime


def date_from_day_number(year, month, day):
    """対象月初からの通し日番号を日付に変換する。"""
    if day < 1:
        raise ValueError(f"日付番号は1以上である必要があります: {day}")
    return datetime.date(year, month, 1) + datetime.timedelta(days=day - 1)
