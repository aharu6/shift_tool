import re

#数値を変更したらFORCED_OFF_HOPE_VALUESも更新すること
# 16: 当直明け希望（○）。休み希望ではないためFORCED_OFF_HOPE_VALUESには含めない
HOPE_MAPPING = {
    "休み":0,
    "出勤":1,
    "出":1,
    "当直不可":2,
    "当×":2,
    "×":2,
    "出当×":[1,2],
    "育休":3,
    "育":3,
    "有":4,
    "慶弔休暇":5,
    "慶":5,
    "研修":6,
    "研":6,
    "なし":7,   
    "当直":8,
    "◎":8,
    "当":8,
    "AM出":9,
    "AM出勤":9,
    "PM出":10,    
    "PM出勤":10,    
    "学会":11,
    '産':12,
    "出×":[1,2],
    "×出":[1,2],
    "○":16,
    "出◎":[1,8],
    "AM夏PM有":[15,4],
    "特":13,
    "AM指×":[14,2],
    "指":14,
    "夏":15,
}


# 記号の表記揺れを正規形に統一する変換表
# （大きな丸・漢数字のゼロ・絵文字の丸/バツ・全角/半角の O, X など）
HOPE_SYMBOL_TRANSLATION = str.maketrans({
    "◯": "○",  # U+25EF LARGE CIRCLE
    "〇": "○",  # U+3007 IDEOGRAPHIC NUMBER ZERO
    "⭕": "○",  # U+2B55 HEAVY LARGE CIRCLE（絵文字）
    "Ｏ": "○",  # 全角 O
    "O": "○",
    "✕": "×",  # U+2715 MULTIPLICATION X
    "✖": "×",  # U+2716 HEAVY MULTIPLICATION X（絵文字）
    "❌": "×",  # U+274C CROSS MARK（絵文字）
    "╳": "×",  # U+2573 BOX DRAWINGS LIGHT DIAGONAL CROSS
    "Ｘ": "×",  # 全角 X
    "X": "×",
    "x": "×",
})


def normalize_hope_string(value):
    """希望セルの文字列を正規化する。

    - 記号の表記揺れ（◯・⭕・✖・❌など）を正規形（○・×）に統一する
    - 絵文字のバリエーションセレクタ（U+FE0E/U+FE0F）を取り除く
    - 空白類（改行・半角/全角スペース等）を全て取り除く
      （セル内改行の例: '出\\n×' → '出×'）

    文字列以外はそのまま返す。
    """
    if isinstance(value, str):
        value = value.replace("\ufe0e", "").replace("\ufe0f", "")
        value = value.translate(HOPE_SYMBOL_TRANSLATION)
        return re.sub(r"\s+", "", value)
    return value