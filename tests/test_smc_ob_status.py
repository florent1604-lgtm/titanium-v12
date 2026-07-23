"""Order-block lifecycle regressions: a later break outranks an earlier touch."""

import pandas as pd

from core.smc_engine import ob_status


def test_buy_ob_break_after_touch_is_broken():
    after = pd.DataFrame([
        {"low": 103.0, "high": 106.0, "close": 104.0},
        {"low": 98.0, "high": 101.0, "close": 99.0},
    ])
    assert ob_status(after, ob_top=105.0, ob_bot=100.0, side="ACHAT") == "broken"


def test_sell_ob_break_after_touch_is_broken():
    after = pd.DataFrame([
        {"low": 99.0, "high": 102.0, "close": 101.0},
        {"low": 104.0, "high": 107.0, "close": 106.0},
    ])
    assert ob_status(after, ob_top=105.0, ob_bot=100.0, side="VENTE") == "broken"


def test_ob_touch_without_later_break_stays_tested():
    after = pd.DataFrame([
        {"low": 103.0, "high": 106.0, "close": 104.0},
        {"low": 102.0, "high": 104.0, "close": 103.0},
    ])
    assert ob_status(after, ob_top=105.0, ob_bot=100.0, side="ACHAT") == "tested"
