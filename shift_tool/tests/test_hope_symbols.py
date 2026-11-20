"""希望記号の追加対応（#171・#172・#173）のテスト。

- #171: 二文字記号「×出」が「出×」と同義に認識される
- #172: 「○」（当直明け）が希望コード16として認識され、mode1で出勤不可・
  当直不可・指定休に数えない扱いになる
- #173: セル内改行などの空白を含む希望（例: '出\n×'）が正規化されて認識される
"""

import pandas as pd
import pytest

from config.hope_mapping import HOPE_MAPPING, normalize_hope_string
from optimizer.mode1.shift_optimizer import ShiftOptimizer
from optimizer.mode2.shift_optimizer import ShiftOptimizer as Mode2Optimizer


class TestNormalizeHopeString:
    def test_newline_removed(self):
        assert normalize_hope_string("出\n×") == "出×"

    def test_fullwidth_space_removed(self):
        assert normalize_hope_string("　出　") == "出"

    def test_non_string_passthrough(self):
        assert normalize_hope_string(4) == 4
        assert normalize_hope_string(None) is None


class TestHopeMapping:
    def test_kakeru_shutsu(self):
        assert HOPE_MAPPING["×出"] == [1, 2]

    def test_gakkai_unified_as_gaku(self):
        # 学会・学はどちらも「学」としてコード11に統一する
        assert HOPE_MAPPING["学会"] == 11
        assert HOPE_MAPPING["学"] == 11

    def test_kenshu_unified_as_ken(self):
        # 研修・研はどちらも「研」としてコード6に統一する
        assert HOPE_MAPPING["研修"] == 6
        assert HOPE_MAPPING["研"] == 6


class TestMode2GakuKenAttendance:
    """mode2では学・研（学会・研修）の日は休み扱いとする（従来通り）。

    mode1は出勤扱いだが、mode2で出勤扱いにすると専属業務の割り当て
    制約等に広く影響するため、安定性優先で休み扱いを維持する
    （2026-11-20 決定）。
    """

    def _optimizer(self, mark, hope):
        optimizer = Mode2Optimizer.__new__(Mode2Optimizer)
        optimizer.mode1_attendance_list = pd.DataFrame(
            {1: [mark]}, index=["A"]
        )
        optimizer.hope_input = pd.DataFrame({"1": [hope]}, index=["A"])
        optimizer.hope_day_column_map = {1: "1"}
        return optimizer

    @pytest.mark.parametrize("mark", ["学", "学会", "研", "研修"])
    def test_gaku_ken_marks_are_not_attending(self, mark):
        optimizer = self._optimizer(mark, mark)
        assert optimizer.get_period_attendance_status("A", 1, "AM") is False
        assert optimizer.get_period_attendance_status("A", 1, "PM") is False

    @pytest.mark.parametrize("mark", ["有", "指", "育"])
    def test_leave_marks_stay_not_attending(self, mark):
        optimizer = self._optimizer(mark, mark)
        assert optimizer.get_period_attendance_status("A", 1, "AM") is False
        assert optimizer.get_period_attendance_status("A", 1, "PM") is False
        assert HOPE_MAPPING["×出"] == HOPE_MAPPING["出×"]

    def test_ake_code(self):
        assert HOPE_MAPPING["○"] == 16


class TestNormalizeMode1Hope:
    def test_kakeru_shutsu(self):
        assert ShiftOptimizer._normalize_mode1_hope("×出") == [1, 2]

    def test_newline_cell(self):
        assert ShiftOptimizer._normalize_mode1_hope("出\n×") == [1, 2]

    def test_ake(self):
        assert ShiftOptimizer._normalize_mode1_hope("○") == 16


class TestSymbolVariants:
    """記号の表記揺れ（◯・⭕・✖・❌など）を正規形に統一する。"""

    def test_large_circle(self):
        assert normalize_hope_string("◯") == "○"

    def test_emoji_circle_with_selector(self):
        assert normalize_hope_string("⭕️") == "○"

    def test_emoji_cross(self):
        assert normalize_hope_string("❌") == "×"
        assert normalize_hope_string("✖出") == "×出"

    def test_mode1_variant_ake(self):
        assert ShiftOptimizer._normalize_mode1_hope("◯") == 16

    def test_mode1_variant_cross(self):
        assert ShiftOptimizer._normalize_mode1_hope("✖出") == [1, 2]
        assert ShiftOptimizer._normalize_mode1_hope("出✕") == [1, 2]

    def test_attendance_mark_variant(self):
        from optimizer.method.baseshiftoptimizer import BaseShiftOptimizer

        assert BaseShiftOptimizer._normalize_attendance_mark("◯") == "○"
        assert BaseShiftOptimizer._normalize_attendance_mark("◎") == "◎"


class TestNormalizeMode2Hope:
    def test_ake(self):
        assert Mode2Optimizer._normalize_mode2_hope("○") == 16

    def test_newline_cell_not_crash(self):
        # mode2 は複合希望を AM/PM 状態で解釈するため '出×' は 0（休み扱い）に
        # ならないことだけ確認する（少なくとも未登録で素通りしない）
        result = Mode2Optimizer._normalize_mode2_hope("出\n×")
        assert result != "出\n×"


class TestAkeSemantics:
    def test_oncall_blocked(self):
        from optimizer.mode1.night_shift.oncall_constraints import (
            ONCALL_BLOCKED_TODAY_HOPES,
        )

        assert 16 in ONCALL_BLOCKED_TODAY_HOPES

    def test_not_in_forced_off(self):
        # 当直明けは休み希望ではないので FORCED_OFF には含めない
        from config.forced_off_hope_values import FORCED_OFF_HOPE_VALUES

        assert 16 not in FORCED_OFF_HOPE_VALUES

    def test_non_counted(self):
        from optimizer.mode1.primary_shift.work_constraints import WorkConstraints

        assert 16 in WorkConstraints.NON_COUNTED_HOPES

    def test_full_day_off_for_attendability(self):
        from optimizer.mode1.primary_shift.work_constraints import WorkConstraints

        assert WorkConstraints._is_full_day_off_hope(16) is True
