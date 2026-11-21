"""スタッフ条件を JSON ファイルで保持するためのモジュール（#152）。

スタッフ条件の保存形式は JSON を正とする（2026-11-21 方針決定）。
- テキスト＋UTF-8固定で、Excel の Mac/Windows 往復で起きる
  不可視の差異（空白・正規化形の違い）を持ち込まない
- 真偽値・数値などの型を保持する
- 保存時にスタッフ名を正規化し、正規化後の名前で重複チェックを行う

このモジュールは mode1 / mode2 からは独立している。
最適化側への接続（JSON → DataFrame）は次の段階で行う。
"""
import json
import re
import unicodedata
from pathlib import Path

SCHEMA_VERSION = 1

# スタッフ条件の列定義（現行のスタッフ条件.xlsx の列名・並びに合わせる）。
# type は "str" / "bool" / "int"、optional は None（未設定）を許すか。
COLUMNS = [
    {"name": "Name", "type": "str", "optional": False},
    {"name": "表示名", "type": "str", "optional": True},
    {"name": "同期変数", "type": "int", "optional": True},
    {"name": "当直", "type": "bool", "optional": False},
    {"name": "当直月1回", "type": "bool", "optional": True},
    {"name": "休職", "type": "bool", "optional": False},
    {"name": "Sex", "type": "str", "optional": False},
    {"name": "Floor", "type": "str", "optional": False},
    {"name": "Floor2", "type": "str", "optional": True},
    {"name": "Floor3", "type": "str", "optional": True},
    {"name": "主任以上", "type": "bool", "optional": False},
    {"name": "必須メンバー", "type": "bool", "optional": True},
    {"name": "緩和回診", "type": "bool", "optional": False},
    {"name": "心不全回診", "type": "bool", "optional": False},
    {"name": "ポリファーマシーチーム", "type": "bool", "optional": False},
    {"name": "実習", "type": "bool", "optional": False},
    {"name": "NST", "type": "bool", "optional": False},
    {"name": "マスター管理", "type": "bool", "optional": False},
    {"name": "RI", "type": "bool", "optional": False},
    {"name": "RI優先度", "type": "int", "optional": True},
    {"name": "医薬品安全使用WG", "type": "bool", "optional": False},
    {"name": "認知症せん妄ラウンド", "type": "bool", "optional": False},
    {"name": "日曜出勤", "type": "bool", "optional": False},
    {"name": "感染管理,AST", "type": "bool", "optional": False},
    {"name": "ICT", "type": "bool", "optional": False},
]

COLUMN_NAMES = [column["name"] for column in COLUMNS]


def normalize_name(name):
    """スタッフ名を正規化する。

    - Unicode 正規化（NFC）
    - 半角スペースを全角スペースに統一し、連続する空白を1つにする
    - 前後の空白を取り除く
    """
    normalized = unicodedata.normalize("NFC", str(name))
    normalized = re.sub(r"\s+", "　", normalized)
    return normalized.strip("　")


def validate_staff_list(staff_list):
    """スタッフ一覧を検証し、問題があれば ValueError を送出する。

    - 列の過不足
    - 必須列の未設定
    - 正規化後の名前の重複
    """
    seen_names = {}
    for index, staff in enumerate(staff_list):
        missing = [name for name in COLUMN_NAMES if name not in staff]
        if missing:
            raise ValueError(f"{index + 1}件目: 列が不足しています: {missing}")
        extra = [name for name in staff if name not in COLUMN_NAMES]
        if extra:
            raise ValueError(f"{index + 1}件目: 未知の列があります: {extra}")
        for column in COLUMNS:
            if not column["optional"] and staff[column["name"]] is None:
                raise ValueError(
                    f"{index + 1}件目: {column['name']} が未設定です"
                )
        normalized = normalize_name(staff["Name"])
        if normalized in seen_names:
            raise ValueError(
                f"スタッフ名が重複しています: {staff['Name']} "
                f"（{seen_names[normalized] + 1}件目と正規化後に一致）"
            )
        seen_names[normalized] = index


def save_staff_conditions(path, staff_list):
    """スタッフ一覧を検証して JSON ファイルに保存する。"""
    validate_staff_list(staff_list)
    data = {"version": SCHEMA_VERSION, "staff": staff_list}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def load_staff_conditions(path):
    """JSON ファイルからスタッフ一覧を読み込む。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("version") != SCHEMA_VERSION:
        raise ValueError(
            f"未対応のバージョンです: {data.get('version')} "
            f"（対応バージョン: {SCHEMA_VERSION}）"
        )
    staff_list = data["staff"]
    validate_staff_list(staff_list)
    return staff_list


def dummy_staff_list():
    """動作確認用のダミーデータ（架空のスタッフ3名）。"""
    base = {column["name"]: None for column in COLUMNS}
    for column in COLUMNS:
        if column["type"] == "bool" and not column["optional"]:
            base[column["name"]] = False

    def make(**values):
        staff = dict(base)
        staff.update(values)
        return staff

    return [
        make(
            Name="山田　太郎", 表示名="山田", 同期変数=29,
            当直=False, 休職=False, Sex="M",
            Floor="部長", Floor2="医療安全・感染管理",
            主任以上=True, 医薬品安全使用WG=True,
        ),
        make(
            Name="佐藤　花子", 表示名="佐藤", 同期変数=18,
            当直=True, 休職=False, Sex="F",
            Floor="化療", Floor2="調剤",
            主任以上=True, 日曜出勤=True,
            ポリファーマシーチーム=True,
        ),
        make(
            Name="鈴木　一郎", 表示名="鈴木", 同期変数=None,
            当直=True, 当直月1回=True, 休職=False, Sex="M",
            Floor="調剤",
            主任以上=False, 日曜出勤=True,
        ),
    ]


if __name__ == "__main__":
    sample_path = Path(__file__).parent / "staff_conditions_sample.json"
    save_staff_conditions(sample_path, dummy_staff_list())
    print(f"ダミーデータを保存しました: {sample_path}")
    loaded = load_staff_conditions(sample_path)
    print(f"読み込み確認: {len(loaded)}名")
