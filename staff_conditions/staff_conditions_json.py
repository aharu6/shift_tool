"""スタッフ条件を JSON ファイルで保持するためのモジュール（#152）。

【このモジュールの役割】
スタッフ条件（誰が・どのフロアに所属し・当直や各チームの対象か、といった
勤務表作成の前提データ）を、Excel ファイルではなく JSON ファイルで
保持するための読み書きを担当する。

【なぜ Excel ではなく JSON なのか】
スタッフ条件の保存形式は JSON を正とする（2026-11-21 方針決定）。
従来の運用は「Mac で作成したスタッフ条件.xlsx をコピーして Windows PC
で使う」というものだったが、Mac で作った Excel を Windows で編集して
から最適化に使うと「スタッフ名が重複している」というエラーが出ること
があった。原因は、Excel の往復で名前の中に目に見えない差異
（半角/全角スペースの違い、前後の空白、Unicode の正規化形の違いなど）
が混入し、見た目は同じ名前が別物として扱われることだと考えられる。

JSON であれば:
- テキスト形式で文字コードも UTF-8 に固定されるため、OS 間の差異が
  入り込みにくい
- 真偽値（true/false）や数値などの型が保持される（Excel から読み込むと
  文字列化されてしまい、正規化処理が各所で必要になっていた）
- ファイルの中身をそのまま目で確認でき、変更差分も追いやすい

【JSON ファイルの形式】
    {
      "version": 1,
      "staff": [
        {"Name": "山田　太郎", "表示名": "山田", "当直": false, ...},
        ...
      ]
    }
- "version" は形式の版数。形式を変更したら版数を上げ、古い版数の
  ファイルは読み込み時にエラーにすることで、静かなデータ破壊を防ぐ
- "staff" はスタッフ1名を1つの辞書（オブジェクト）とするリスト。
  各辞書のキー（列）は下記の COLUMNS 定義と過不足なく一致させる
- 空データ（スタッフ0名）のファイルは、変換モジュール
  （convert_staff_conditions.py）が "columns" キーを追加して列名だけを
  記録することがある。読み込み側は "columns" キーがあっても無視する

【名前の正規化について】
保存・検証の前に、スタッフ名は normalize_name() で正規化する。
重複チェックも正規化後の名前で行うため、「山田　太郎」と「山田 太郎」
（半角スペース）のような、見た目が同じで表記だけ違う名前が混入しても
重複として検出できる。これが Excel 運用で起きた問題への直接の対策。

【このモジュールの範囲】
ここでは JSON の読み書きと検証だけを行う。最適化（mode1/mode2）への
接続（JSON → DataFrame 変換）は次の段階で行う。
xlsx からの取り込みは convert_staff_conditions.py を参照。
"""
import json
import re
import unicodedata
from pathlib import Path

SCHEMA_VERSION = 1

# スタッフ条件の列定義。
#
# 現行のスタッフ条件.xlsx（実ファイル）の列名と並び順に合わせている。
# 各列は次の情報を持つ:
#   name     : 列名（xlsx の見出し・JSON のキーと一致させる）
#   type     : "str"（文字列） / "bool"（真偽値） / "int"（整数）
#   optional : True なら None（未設定）を許す。
#              False の列が None のレコードは検証エラーになる。
#
# 【列の意味メモ】
#   Name         : 氏名（姓名の間は全角スペース）。スタッフの識別子
#   表示名       : 出勤表などでの短い表示名（名字のみ等）
#   同期変数     : 前月データ引き継ぎ用の数値（未設定なら None）
#   当直         : 当直に入るかどうか
#   当直月1回    : True の人は当直を月1回までに制限する（#175 で追加）
#   休職         : 休職中かどうか
#   Sex          : "M" / "F"
#   Floor        : 主所属フロア（文字列ラベル。例: "調剤" "化療" "外来"）
#   Floor2/Floor3: 兼務フロア（無ければ None）
#   主任以上     : 役職者かどうか（当直の月回数制限の自動判定に使う）
#   必須メンバー : 会議等の必須メンバー指定（未設定なら None）
#   緩和回診〜ICT: 各種チーム・回診・当番への所属フラグ
#   RI優先度     : RI 担当の優先度（数値。未設定なら None）
#   日曜出勤     : 日曜・祝日に出勤するかどうか
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
    """スタッフ名を正規化して返す。

    見た目が同じ名前の表記ゆれを吸収するための処理で、次の3つを行う:
    1. Unicode 正規化（NFC）: 合成済み文字に統一する
       （例: 「ガ」を「カ＋濁点」の分解形ではなく1文字の形にする）
    2. 空白の統一: 半角スペース・タブ・全角スペースなど、あらゆる空白の
       連続を全角スペース1つに置き換える
    3. 前後の空白を取り除く

    例:
        "山田 太郎"（半角スペース）   → "山田　太郎"
        "　山田　　太郎　"（余分な空白）→ "山田　太郎"

    この正規化を通してから比較することで、Excel の往復で混入した
    不可視の差異があっても同一人物を同一として扱える。
    """
    normalized = unicodedata.normalize("NFC", str(name))
    normalized = re.sub(r"\s+", "　", normalized)
    return normalized.strip("　")


def validate_staff_list(staff_list):
    """スタッフ一覧（レコードのリスト）を検証する。

    問題があれば ValueError を送出する。チェック内容:
    - 各レコードの列が COLUMNS と過不足なく一致すること
      （列が足りない・未知の列がある場合はエラー）
    - optional でない列が None になっていないこと
    - 正規化後のスタッフ名が重複していないこと
      （表記ゆれだけが違う同名も重複として検出する）

    保存時（save_staff_conditions）と読み込み時
    （load_staff_conditions）の両方から呼ばれるので、手で編集した
    JSON を読み込んだ場合でも、不正なデータがそのまま使われる
    ことはない。
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
    """スタッフ一覧を検証してから JSON ファイルに保存する。

    保存形式は {"version": 版数, "staff": [...]}。
    ensure_ascii=False で日本語をそのまま書き出す（\\uXXXX 形式に
    しない）ため、テキストエディタで開いて目視確認できる。
    保存先のフォルダが無ければ作成する。

    戻り値: 保存したパス（Path）
    """
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
    """JSON ファイルからスタッフ一覧を読み込んで返す。

    - "version" が SCHEMA_VERSION と違うファイルはエラーにする
      （形式変更に追随していない古い・新しすぎるファイルの誤用防止）
    - 読み込んだ内容は validate_staff_list で検証する
    - 空データ用ファイルに付いている "columns" キーは無視する

    戻り値: スタッフ1名を表す辞書のリスト
    """
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
    """動作確認用のダミーデータ（架空のスタッフ3名）を返す。

    実在のスタッフとは無関係の名前・所属で、列の使い方の見本も兼ねる:
    - 山田　太郎: 部長（主任以上）。当直なし
    - 佐藤　花子: 化療フロア所属、ポリファーマシーチーム、当直あり
    - 鈴木　一郎: 調剤フロア所属、当直月1回=True の例
      （#175 の制限対象）

    未指定の列は、bool 列は False、それ以外は None で埋める。
    """
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
    # 単体実行時の動作確認: ダミーデータでサンプル JSON を作成し、
    # そのまま読み戻して件数を表示する。
    # サンプルは見本として Git 管理対象に含める（実データは含めない）。
    sample_path = Path(__file__).parent / "staff_conditions_sample.json"
    save_staff_conditions(sample_path, dummy_staff_list())
    print(f"ダミーデータを保存しました: {sample_path}")
    loaded = load_staff_conditions(sample_path)
    print(f"読み込み確認: {len(loaded)}名")
