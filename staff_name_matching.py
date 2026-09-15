import unicodedata

import pandas as pd


def normalize_staff_name(value):
    """Normalize staff name for stable matching across input files.
    
    NaN値をサポートし、文字列を正規化する処理:
    - NaNまたはNone: 空文字列に変換
    - 文字列: NFKC正規化(全角・半角の統一)と前後の空白削除
    """
    if pd.isna(value):
        return ""
    return unicodedata.normalize("NFKC", str(value)).strip()


def normalize_name_index(df, source_label, name_column="Name", allow_index_fallback=False):
    """
    インデックスがスタッフ名になるようにDataFrameを正規化する。
    
    - Name columnが存在する場合はそれを使用し、存在しない場合にはallow_index_fallbackがTrueであれば既存のインデックスを使用する。
    - Name columnが存在せずallow_index_fallback=Trueの場合には既存のインデックスを使用する。
    - 空の名前や重複する名前がある場合にはValueErrorを発生させる。
    """
    if name_column in df.columns:
        raw_names = df[name_column]
    elif allow_index_fallback:
        raw_names = pd.Series(df.index, index=df.index)
    else:
        raise ValueError(f"{source_label} に '{name_column}' 列がありません。")

    # 全ての名前を正規化
    names = raw_names.map(normalize_staff_name)
    if (names == "").any():
        empty_rows = [str(i) for i in names[names == ""].index.tolist()]
        raise ValueError(
            f"{source_label} のスタッフ名に空値があります。対象行: {', '.join(empty_rows)}"
        )

    duplicated = names[names.duplicated(keep=False)]
    if not duplicated.empty:
        duplicate_names = sorted(set(duplicated.tolist()))
        raise ValueError(
            f"{source_label} のスタッフ名が重複してます。リストを確認してください。同性同名の場合には末尾に数字やアルファベットをつけるなど重複しないように変更してください。: {duplicate_names}"
        )

    result = df.copy()
    result.index = pd.Index(names.tolist(), name=name_column)
    return result


def validate_name_alignment(staff_df, hope_df):
    """Ensure staff and hope lists have exactly the same normalized name set.
    
    スタッフリストと希望リストの名前が完全に一致することを確認:
    - スタッフにいるがリストにいない名前をチェック
    - リストにいるがスタッフにいない名前をチェック
    - 不一致がある場合はValueErrorを発生させる
    """
    staff_names = set(staff_df.index)
    hope_names = set(hope_df.index)

    # スタッフリストにあるが希望リストにない名前
    missing_in_hope = sorted(staff_names - hope_names)
    missing_in_staff = sorted(hope_names - staff_names)

    if missing_in_hope or missing_in_staff:
        messages = []
        if missing_in_hope:
            messages.append(f"希望リストに存在しないスタッフ: {missing_in_hope}")
        if missing_in_staff:
            messages.append(f"スタッフ条件に存在しないスタッフ: {missing_in_staff}")
        raise ValueError(" / ".join(messages))


def normalize_name_list(values):
    """Normalize a list-like of staff names and drop empty values.
    
    名前のリストを正規化し、空値を除外:
    - 各要素をnormalize_staff_nameで正規化
    - 空文字列となった要素は除外
    - 正規化済みの名前のリストを返す
    """
    normalized = []
    for value in values:
        name = normalize_staff_name(value)
        if name:
            normalized.append(name)
    return normalized