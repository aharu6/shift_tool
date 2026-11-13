import datetime

import jpholiday


def date_from_day_number(year, month, day):
    """対象月初からの通し日番号を日付に変換する。"""
    if day < 1:
        raise ValueError(f"日付番号は1以上である必要があります: {day}")
    return datetime.date(year, month, 1) + datetime.timedelta(days=day - 1)


def extend_period_holidays(year, month, days, holidays):
    """指定済みの祝日を維持し、翌月以降の対象期間の祝日を追加する。"""
    end_date = date_from_day_number(year, month, days)
    next_month = (
        datetime.date(year + 1, 1, 1)
        if month == 12 else datetime.date(year, month + 1, 1)
    )
    result = list(holidays)
    known_dates = set()
    for holiday in result:
        value = holiday[0] if isinstance(holiday, tuple) and holiday else holiday
        if isinstance(value, datetime.datetime):
            value = value.date()
        if isinstance(value, datetime.date):
            known_dates.add(value)

    while next_month <= end_date:
        for date, name in jpholiday.month_holidays(next_month.year, next_month.month):
            if date <= end_date and date not in known_dates:
                result.append((date, name))
                known_dates.add(date)
        next_month = (
            datetime.date(next_month.year + 1, 1, 1)
            if next_month.month == 12
            else datetime.date(next_month.year, next_month.month + 1, 1)
        )
    return result
