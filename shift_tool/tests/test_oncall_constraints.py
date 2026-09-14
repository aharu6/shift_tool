import pandas as pd

from optimizer.night_shift.oncall_constraints import OncallConstraints


def test_required_floor_ignores_missing_values():
    assert OncallConstraints._has_required_floor(
        [pd.NA, 3, None],
        [1, 2, 3, 4, 5],
    )


def test_required_floor_rejects_missing_and_non_floor_values():
    assert not OncallConstraints._has_required_floor(
        [pd.NA, "調剤", None],
        [1, 2, 3, 4, 5],
    )