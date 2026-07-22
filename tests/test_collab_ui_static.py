from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "collab_ui"
COMPONENTS = [
    UI / "components" / "messages.mjs",
    UI / "components" / "agents.mjs",
    UI / "components" / "actions.mjs",
    UI / "components" / "failures.mjs",
]


def test_components_use_safe_dom_primitives_only():
    source = "\n".join(path.read_text(encoding="utf-8") for path in COMPONENTS)
    for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "eval("):
        assert forbidden not in source
    assert "createElement" in source
    assert "textContent" in source
    assert "replaceChildren" in source


def test_retry_is_not_scheduled_or_started_automatically():
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [*COMPONENTS, UI / "app.mjs"]
    )
    assert not re.search(r"set(?:Timeout|Interval)[\s\S]{0,240}retryIntent", source)
    assert not re.search(r"(?:start|mountCommandDeck)[\s\S]{0,240}retryIntent", source)


def test_index_mounts_the_module_and_keeps_the_permanent_guard():
    html = (UI / "index.html").read_text(encoding="utf-8")
    css = (UI / "styles.css").read_text(encoding="utf-8")
    assert re.search(r'<script\s+type="module"\s+src="\./app\.mjs"', html)
    assert "PAPER ONLY" in html
    assert "RÉEL INTERDIT" in html
    assert re.search(
        r"@media \(max-width: 720px\)[\s\S]*?\.compact-guard\s*\{[^}]*display:\s*flex",
        css,
    )


def test_exact_labels_and_no_direct_host_or_trading_surface():
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [*COMPONENTS, UI / "app.mjs", UI / "index.html"]
    )
    for label in (
        "Conversation",
        "Échecs à suivre",
        "Disponible",
        "Validation requise",
        "Double signature",
        "Bloquée",
        "Indisponible",
    ):
        assert label in source
    for forbidden in ("order_send", "MetaTrader5", "child_process", "powershell", "cmd.exe"):
        assert forbidden not in source
