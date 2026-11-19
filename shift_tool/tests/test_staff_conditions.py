import pandas as pd
import pytest

from optimizer.method.staff_conditions import read_staff_conditions
from optimizer.mode1.shift_optimizer import ShiftOptimizer


def _write_staff_file(tmp_path, frame, header_row):
    path = tmp_path / "staff.xlsx"
    with pd.ExcelWriter(path) as writer:
        frame.to_excel(writer, sheet_name="member_list", index=False, startrow=header_row)
    return path


@pytest.mark.parametrize("header_row", [0, 1])
def test_read_staff_conditions_with_either_header_row(tmp_path, header_row):
    expected = pd.DataFrame({"Name": ["A", "B"], "Floor": [8, 9]})
    path = _write_staff_file(tmp_path, expected, header_row)
    pd.testing.assert_frame_equal(read_staff_conditions(path), expected)


@pytest.mark.parametrize("names", [["Staff", "A"], ["Name", "Name"]])
def test_read_staff_conditions_rejects_missing_or_ambiguous_header(tmp_path, names):
    path = tmp_path / "staff.xlsx"
    pd.DataFrame({"column": names}).to_excel(
        path, sheet_name="member_list", index=False, header=False
    )
    with pytest.raises(ValueError, match="Name 列の見出し"):
        read_staff_conditions(path)


@pytest.mark.parametrize("header_row", [0, 1])
def test_mode1_optimizer_reads_staff_conditions_with_either_header_row(
    tmp_path, header_row
):
    frame = pd.DataFrame(
        {
            "Name": ["A", "B"],
            "Floor": [8, 9],
            "当直": [True, False],
            "休職": [False, False],
            "主任以上": [False, False],
        }
    )
    path = _write_staff_file(tmp_path, frame, header_row)
    hope = pd.DataFrame(
        7, index=pd.Index(["A", "B"], name="Name"), columns=range(1, 32)
    )
    optimizer = ShiftOptimizer(
        year=2026,
        month=10,
        holidays=[],
        staff_list_pass=path,
        hope_list=hope,
        offrequest_day=9,
    )
    assert list(optimizer.staff.index) == ["A", "B"]
    assert list(optimizer.staff["Floor"]) == [8, 9]
