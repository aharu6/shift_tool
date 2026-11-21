"""スタッフ条件.xlsx からスタッフ条件 JSON を作成する（#152）。

- スタッフ条件フォルダ内に xlsx があれば、ファイル名から読める
  最新の年月のものを取り込んで JSON 化する
- 該当ファイルがなければ、列名だけを入れた空の JSON を作成する

作成される JSON の形式は staff_conditions_json.py の定義に従う。
実データの JSON は .gitignore で管理対象外にしている（実名を含むため）。
"""
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from optimizer.method.staff_conditions import read_staff_conditions
from staff_conditions.staff_conditions_json import (
    COLUMNS,
    COLUMN_NAMES,
    SCHEMA_VERSION,
    normalize_name,
    save_staff_conditions,
)

DEFAULT_FOLDER = Path("読み込み用ファイル") / "スタッフ条件"
DEFAULT_OUTPUT = Path(__file__).parent / "staff_conditions.json"


def find_latest_staff_conditions_xlsx(folder):
    """フォルダ直下の xlsx から、ファイル名の年月が最新のものを返す。

    年月がファイル名から読めないものは、年月が読めるものがある場合は
    対象外とし、1つも読めない場合のみ更新日時の最新を使う。
    候補がなければ None を返す。
    """
    candidates = sorted(
        path for path in Path(folder).glob("*.xlsx")
        if "スタッフ条件" in path.stem
    )
    if not candidates:
        return None

    def year_month(path):
        match = re.search(r"(\d{4})\D{0,3}?(\d{1,2})", path.stem)
        if match is None:
            return None
        return int(match.group(1)), int(match.group(2))

    dated = [(year_month(path), path) for path in candidates]
    dated = [(ym, path) for ym, path in dated if ym is not None]
    if dated:
        latest_ym = max(ym for ym, _ in dated)
        same_month = [path for ym, path in dated if ym == latest_ym]
        return max(same_month, key=lambda path: path.stat().st_mtime)
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _convert_value(value, column):
    """xlsx のセル値を JSON の型に合わせる。空欄は None（bool列は False）。"""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return False if column["type"] == "bool" else None
    if column["type"] == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "1.0")
        return bool(value)
    if column["type"] == "int":
        return int(value)
    text = str(value)
    if column["name"] == "Name":
        return normalize_name(text)
    return text


def staff_dataframe_to_records(dataframe):
    """read_staff_conditions の DataFrame を JSON のレコード列に変換する。"""
    records = []
    for _, row in dataframe.iterrows():
        record = {}
        for column in COLUMNS:
            name = column["name"]
            value = row[name] if name in dataframe.columns else None
            record[name] = _convert_value(value, column)
        records.append(record)
    return records


def create_staff_conditions_json(folder=DEFAULT_FOLDER, output=DEFAULT_OUTPUT):
    """スタッフ条件 JSON を作成する。

    戻り値: (出力パス, 取り込み元ファイル名 or None, 件数)
    """
    output = Path(output)
    source = find_latest_staff_conditions_xlsx(folder)
    if source is None:
        data = {
            "version": SCHEMA_VERSION,
            "columns": COLUMN_NAMES,
            "staff": [],
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return output, None, 0
    records = staff_dataframe_to_records(read_staff_conditions(source))
    save_staff_conditions(output, records)
    return output, source.name, len(records)


if __name__ == "__main__":
    output_path, source_name, count = create_staff_conditions_json()
    if source_name is None:
        print(f"対象のxlsxが無いため、空のJSONを作成しました: {output_path}")
    else:
        print(f"{source_name} から {count}名を取り込みました: {output_path}")
