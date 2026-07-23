from pathlib import Path


ORBE = Path(__file__).resolve().parents[1] / "titanium_orbe.html"


def _source() -> str:
    return ORBE.read_text(encoding="utf-8")


def test_clock_is_explicitly_rendered_in_paris_time() -> None:
    source = _source()
    assert 'timeZone:"Europe/Paris"' in source
    assert 'id="hud-zone"' in source
    assert "EUROPE/PARIS" in source


def test_risk_base_does_not_present_mixed_currencies_as_euros() -> None:
    source = _source()
    assert "BASE&nbsp;RISQUE&nbsp;R3" in source
    assert "eqEur" in source
    assert "eqCrypto" in source
    assert 'fmtEur(eqEur)+" + "+fmtUsdt(eqCrypto)' in source


def test_saturated_cluster_shows_ratio_and_paper_scope() -> None:
    source = _source()
    assert "clusterAlerts" in source
    assert "· LIMITE DÉPASSÉE +" in source
    assert "GARDE R3 —" in source
    assert "(PAPER)" in source
    assert "SURVEILLANCE — PLAFOND SATURÉ OU FLUX RALENTI" not in source
