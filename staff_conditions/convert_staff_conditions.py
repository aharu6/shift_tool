"""スタッフ条件.xlsx からスタッフ条件 JSON を作成する（#152）。

【このモジュールの役割】
既存のスタッフ条件.xlsx を、新しい保存形式である JSON
（staff_conditions_json.py の形式）へ変換する橋渡し役。

main.py の起動時に create_staff_conditions_json() が呼ばれ、次の
流れで JSON が用意される:
1. スタッフ条件フォルダ（読み込み用ファイル/スタッフ条件）直下から、
   ファイル名に「スタッフ条件」を含む xlsx を探す
2. 候補があれば、ファイル名から読める年月が最新のものを取り込む
3. 候補が無ければ、列名だけを記録した空の JSON を作成する
   （新規に使い始める PC でも、まず JSON の置き場所と形が用意される）

【取り込み時の変換ルール】
- xlsx の読み込みは既存の共通関数 read_staff_conditions を使う
  （見出し行が1行目・2行目のどちらでもよい自動判定もそのまま使う）
- xlsx に無い列（古いファイルの「表示名」「当直月1回」など）は
  None / False で補完する
- セルの空欄は、bool 列では False、それ以外では None とする
  （最適化側の従来の解釈「空欄 = 対象でない」に合わせる）
- 数値列（同期変数など）で 29.0 のように小数で読めた値は整数に直す
- スタッフ名は normalize_name で正規化してから保存する
- 保存時に検証（列の過不足・必須列・名前の重複）が走るので、
  xlsx 側に表記ゆれの同名などがあればここでエラーとして気づける

【出力先と Git の関係】
実データの JSON にはスタッフの実名が入るため、出力先
（staff_conditions/staff_conditions.json）は .gitignore で
Git 管理対象外にしている。見本の staff_conditions_sample.json
（ダミーデータ）だけは管理対象に含める。

【将来方針（2026-11-21 合意、#152 にメモ）】
現在は main.py の起動のたびに xlsx から JSON を作り直す。
将来 Web アプリで JSON を直接編集するようになったら、再作成は
「xlsx が JSON より新しい場合だけ」に変え、アプリ側の編集を
上書きしないようにすること。
"""
import json
import math
import re
import sys
from pathlib import Path

# このファイルの2つ上の階層（リポジトリ直下）を import の探索先に加える。
# main.py からも単体実行でも同じように import できるようにするため。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from optimizer.method.staff_conditions import read_staff_conditions
from staff_conditions.staff_conditions_json import (
    COLUMNS,
    COLUMN_NAMES,
    SCHEMA_VERSION,
    normalize_name,
    save_staff_conditions,
)

# 取り込み元フォルダと出力先の既定値。
# フォルダは main.py の実行場所（リポジトリ直下）からの相対パス、
# 出力先はこのモジュールの置き場所を基準にした絶対パスにしている。
DEFAULT_FOLDER = Path("読み込み用ファイル") / "スタッフ条件"
DEFAULT_OUTPUT = Path(__file__).parent / "staff_conditions.json"


def find_latest_staff_conditions_xlsx(folder):
    """フォルダ直下の xlsx から、取り込み対象の最新ファイルを返す。

    対象はファイル名に「スタッフ条件」を含むものだけ
    （希望表など別種の xlsx が同居していても誤って拾わないため）。

    「最新」の決め方:
    - ファイル名から年月（例: スタッフ条件_2026_12.xlsx → 2026年12月）
      が読めるものがあれば、その年月が最大のものを選ぶ。
      同じ年月が複数あれば、ファイルの更新日時が新しい方を選ぶ
    - 年月が読めるものが1つも無い場合に限り、更新日時の最新を使う
      （「スタッフ条件4月以降.xlsx」のような名前への保険）

    候補が無ければ None を返す。
    """
    candidates = sorted(
        path for path in Path(folder).glob("*.xlsx")
        if "スタッフ条件" in path.stem
    )
    if not candidates:
        return None

    def year_month(path):
        """ファイル名から (年, 月) を取り出す。読めなければ None。"""
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
    """xlsx のセル値1つを、JSON の型に合わせて変換する。

    変換ルール（モジュール冒頭の説明も参照）:
    - 空欄（None / NaN）: bool 列は False、それ以外は None
    - bool 列: 文字列で入っている場合は "true"/"1"/"1.0" を True と
      みなす。それ以外は通常の真偽値変換
    - int 列: 29.0 のような小数で読めた値を整数に直す
    - str 列: 文字列化する。Name 列だけは normalize_name で正規化する
    """
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
    """read_staff_conditions の DataFrame を JSON のレコード列に変換する。

    DataFrame に存在しない列は _convert_value に None が渡り、
    列定義に従って None / False で補完される。
    レコードのキー順は COLUMNS の定義順に揃える
    （JSON を目で読んだとき xlsx と同じ並びになるように）。
    """
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
    """スタッフ条件 JSON を作成する（このモジュールの入口）。

    - フォルダに取り込み対象の xlsx があれば、最新月のものを変換して
      保存する（保存時に検証も走る）
    - 無ければ、列名だけを "columns" に記録した空の JSON
      （{"version": ..., "columns": [...], "staff": []}）を作成する

    戻り値: (出力パス, 取り込み元ファイル名 or None, 取り込み件数)
    空 JSON を作った場合は (出力パス, None, 0)。
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
    # 単体実行時: 既定のフォルダ・出力先で JSON を作成し、結果を表示する。
    output_path, source_name, count = create_staff_conditions_json()
    if source_name is None:
        print(f"対象のxlsxが無いため、空のJSONを作成しました: {output_path}")
    else:
        print(f"{source_name} から {count}名を取り込みました: {output_path}")
