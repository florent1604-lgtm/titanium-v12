from __future__ import annotations


def _casefold_collisions(value: object) -> list[tuple[str, str]]:
    collisions: list[tuple[str, str]] = []
    if isinstance(value, dict):
        seen: dict[str, str] = {}
        for key, child in value.items():
            folded = key.casefold()
            if folded in seen and seen[folded] != key:
                collisions.append((seen[folded], key))
            else:
                seen[folded] = key
            collisions.extend(_casefold_collisions(child))
    elif isinstance(value, list):
        for child in value:
            collisions.extend(_casefold_collisions(child))
    return collisions


def test_api_signal_contract_separates_criteria_from_measurements():
    from api.json_contract import serialize_signal_states

    raw = {
        "BTC/USDT": {
            "ema200_h4": 64_321.5,
            "EMA200_H4": True,
            "rsi_divergence": "bullish",
            "RSI_DIVERGENCE": True,
            "side": "ACHAT",
        }
    }

    result = serialize_signal_states(raw, ("EMA200_H4", "RSI_DIVERGENCE"))

    assert result["BTC/USDT"]["ema200_h4"] == 64_321.5
    assert result["BTC/USDT"]["rsi_divergence"] == "bullish"
    assert result["BTC/USDT"]["criteria"] == {
        "EMA200_H4": True,
        "RSI_DIVERGENCE": True,
    }
    assert "EMA200_H4" not in result["BTC/USDT"]
    assert not _casefold_collisions(result)
    assert "criteria" not in raw["BTC/USDT"]
