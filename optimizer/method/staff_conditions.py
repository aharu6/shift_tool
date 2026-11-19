import pandas as pd


def read_staff_conditions(path):
    """スタッフ条件ファイル（member_listシート）を読み込む。

    見出し（Name列）が1行目・2行目のどちらにあっても読み取れるよう、
    最初の2行からName見出しのある行を特定し、その行を見出しとして使う。
    Name見出しが無い場合や複数ある場合はエラーにする。
    """
    first_rows = pd.read_excel(
        path, sheet_name="member_list", header=None, nrows=2
    )
    header_rows = [
        row for row in range(len(first_rows))
        if first_rows.iloc[row].eq("Name").any()
    ]
    if len(header_rows) != 1:
        raise ValueError(
            f"{path} の member_list シートの1行目または2行目に"
            "Name 列の見出しが1つ必要です"
        )
    return pd.read_excel(path, sheet_name="member_list", header=header_rows[0])
