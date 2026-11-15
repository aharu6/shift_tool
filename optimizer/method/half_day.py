import re

import pandas as pd


_TOKEN = re.compile(r"(AM|PM)(指|有|夏|出勤|出)")


def parse_half_day(value):
    """半日単位の記号を、各時間帯の出勤可否と休暇種別に変換する。"""
    if pd.isna(value):
        return None
    text = re.sub(r"\s+", "", str(value))
    if text.endswith("×"):
        text = text[:-1]
    tokens = _TOKEN.findall(text)
    if not tokens or "".join(period + kind for period, kind in tokens) != text:
        if "AM" in text or "PM" in text:
            raise ValueError(f"未対応の半日勤務記号です: {value}")
        return None
    if len(tokens) > 2 or len({period for period, _ in tokens}) != len(tokens):
        raise ValueError(f"半日希望の時間帯が重複しています: {value}")

    states = {}
    leave = {}
    for period, kind in tokens:
        states[period] = kind in {"出", "出勤"}
        if kind not in {"出", "出勤"}:
            leave[period] = kind
    if len(states) == 1:
        period = next(iter(states))
        states["PM" if period == "AM" else "AM"] = not states[period]
    return states, leave


def is_oncall_mark(value):
    if pd.isna(value):
        return False
    text = str(value).strip()
    if text in {"◎", "出◎", "出勤◎"}:
        return True
    return text.endswith("◎") and parse_half_day(text[:-1]) is not None
