import json

import pandas as pd
import pytest

from staff_conditions.convert_staff_conditions import (
    create_staff_conditions_json,
    find_latest_staff_conditions_xlsx,
    staff_dataframe_to_records,
)
from staff_conditions.staff_conditions_json import (
    COLUMN_NAMES,
    dummy_staff_list,
    load_staff_conditions,
    normalize_name,
    save_staff_conditions,
    validate_staff_list,
)


def test_normalize_name_unifies_spaces():
    assert normalize_name("山田 太郎") == "山田　太郎"
    assert normalize_name("　山田　　太郎　") == "山田　太郎"


def test_validate_detects_duplicate_after_normalization():
    staff = dummy_staff_list()
    duplicate = dict(staff[0])
    duplicate["Name"] = "山田 太郎"  # 半角スペース版
    with pytest.raises(ValueError, match="重複"):
        validate_staff_list(staff + [duplicate])


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "staff_conditions.json"
    save_staff_conditions(path, dummy_staff_list())
    assert load_staff_conditions(path) == dummy_staff_list()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert len(data["staff"]) == 3


def test_load_rejects_unknown_version(tmp_path):
    path = tmp_path / "staff_conditions.json"
    path.write_text('{"version": 99, "staff": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="バージョン"):
        load_staff_conditions(path)


def _write_staff_xlsx(folder, filename, frame, header_row=0):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    with pd.ExcelWriter(path) as writer:
        frame.to_excel(
            writer, sheet_name="member_list", index=False, startrow=header_row
        )
    return path


def test_find_latest_picks_newest_month(tmp_path):
    frame = pd.DataFrame({"Name": ["A"], "Floor": ["調剤"]})
    _write_staff_xlsx(tmp_path, "スタッフ条件_2025_12.xlsx", frame)
    latest = _write_staff_xlsx(tmp_path, "スタッフ条件_2026_12.xlsx", frame)
    _write_staff_xlsx(tmp_path, "希望リスト_2027_01.xlsx", frame)
    assert find_latest_staff_conditions_xlsx(tmp_path) == latest


def test_find_latest_returns_none_without_candidates(tmp_path):
    assert find_latest_staff_conditions_xlsx(tmp_path) is None


def test_dataframe_to_records_fills_missing_and_converts_types():
    frame = pd.DataFrame(
        {
            "Name": ["山田 太郎"],
            "当直": [True],
            "同期変数": [29.0],
            "Floor": ["調剤"],
        }
    )
    (record,) = staff_dataframe_to_records(frame)
    assert record["Name"] == "山田　太郎"  # 正規化される
    assert record["同期変数"] == 29
    assert record["当直"] is True
    assert record["休職"] is False  # bool列の空欄は False
    assert record["表示名"] is None  # 無い列は None で補完
    assert list(record.keys()) == COLUMN_NAMES


def test_create_from_xlsx(tmp_path):
    frame = pd.DataFrame(
        {
            "Name": ["山田　太郎", "佐藤　花子"],
            "当直": [True, False],
            "休職": [False, False],
            "Sex": ["M", "F"],
            "Floor": ["調剤", "化療"],
            "主任以上": [False, True],
            "日曜出勤": [True, True],
        }
    )
    _write_staff_xlsx(tmp_path, "スタッフ条件_2026_12.xlsx", frame, header_row=1)
    output = tmp_path / "staff_conditions.json"
    _, source_name, count = create_staff_conditions_json(tmp_path, output)
    assert source_name == "スタッフ条件_2026_12.xlsx"
    assert count == 2
    assert len(load_staff_conditions(output)) == 2


def test_create_empty_when_no_xlsx(tmp_path):
    output = tmp_path / "staff_conditions.json"
    _, source_name, count = create_staff_conditions_json(tmp_path, output)
    assert source_name is None
    assert count == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["columns"] == COLUMN_NAMES
    assert data["staff"] == []
