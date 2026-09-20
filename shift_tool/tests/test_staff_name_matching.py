import pandas as pd
import pytest

from staff_name_matching import normalize_name_index, normalize_staff_name, validate_name_alignment


def test_normalize_staff_name_nfkc_and_strip():
    assert normalize_staff_name("  Name1  ") == "Name1"
    assert normalize_staff_name("Ｎａｍｅ１") == "Name1"


def test_normalize_name_index_raises_on_duplicate_names():
    df = pd.DataFrame({"Name": ["Name1", " Name1 "]})

    with pytest.raises(ValueError, match="重複"):
        normalize_name_index(df, source_label="staff")


def test_validate_name_alignment_raises_on_mismatch():
    staff_df = pd.DataFrame(index=["Name1", "Name2"])
    hope_df = pd.DataFrame(index=["Name1", "Name3"])

    with pytest.raises(ValueError, match="存在しない"):
        validate_name_alignment(staff_df, hope_df)
