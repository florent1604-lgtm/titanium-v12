from pathlib import Path
import os

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.environ.get("COLLAB_UI_URL", "http://127.0.0.1:4174")


def install_runtime_stubs(page) -> None:
    page.add_init_script(
        """
        window.chrome = {webview: {postMessage: () => Promise.resolve(true)}};
        window.WebSocket = class FakeWebSocket {
          constructor() { queueMicrotask(() => this.onopen?.()); }
          close() { queueMicrotask(() => this.onclose?.({code: 1000})); }
        };
        """
    )
    page.route(
        "**/v1/messages?*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"messages":[]}',
        ),
    )
    page.route(
        "**/v1/failures",
        lambda route: route.fulfill(
            status=401,
            content_type="application/json",
            body='{"reason_code":"SESSION_REQUIRED"}',
        ),
    )


def assert_layout(page, width: int, height: int) -> None:
    page.set_viewport_size({"width": width, "height": height})
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    page.get_by_role("tab", name="Conversation").wait_for()
    metrics = page.evaluate(
        """() => ({
          body: document.body.scrollWidth,
          document: document.documentElement.scrollWidth,
          viewport: window.innerWidth,
        })"""
    )
    assert metrics["body"] <= metrics["viewport"] + 1, metrics
    assert metrics["document"] <= metrics["viewport"] + 1, metrics

    if width == 390:
        compact = page.locator(".compact-guard")
        assert compact.is_visible()
        assert "PAPER ONLY" in compact.inner_text()
        assert "RÉEL INTERDIT" in compact.inner_text()
    else:
        desktop = page.locator(".rail-guard")
        assert desktop.is_visible()
        assert desktop.locator("br").count() == 1
        assert "PAPER ONLYRÉEL INTERDIT" not in desktop.text_content()
        filters_box = page.locator(".filters").bounding_box()
        last_filter_box = page.locator(".filters .filter").last.bounding_box()
        assert filters_box is not None and last_filter_box is not None
        assert abs(
            (filters_box["x"] + filters_box["width"])
            - (last_filter_box["x"] + last_filter_box["width"])
        ) <= 2


def assert_snapshot_preserves_draft(page) -> None:
    page.evaluate(
        """async () => {
          const [{mountCommandDeck}, {HostBridge}, {createState, reduce}] = await Promise.all([
            import('/app.mjs'),
            import('/host_bridge.mjs'),
            import('/state.mjs'),
          ]);
          let current = {connectionStatus: 'connected', state: createState()};
          let subscriber = () => {};
          const app = {
            snapshot: () => current,
            subscribe(listener) { subscriber = listener; listener(current); return () => {}; },
            loadOlder: () => Promise.resolve([]),
          };
          const bridge = new HostBridge(() => Promise.resolve(true));
          mountCommandDeck({
            root: document.querySelector('[data-command-deck-root]'),
            app,
            bridge,
          });
          window.__emitSnapshot = () => {
            current = {
              connectionStatus: 'connected',
              state: reduce(current.state, {
                type: 'messages.loaded',
                messages: [{
                  message_id: 'message-8',
                  global_offset: 8,
                  created_at: '2026-07-22T10:00:00Z',
                  principal: 'codex',
                  kind: 'review',
                  task_id: 'COMMAND_DECK',
                  content: 'Snapshot temps réel',
                }],
              }),
            };
            subscriber(current);
          };
        }"""
    )
    composer = page.locator('[data-action="compose-message"]')
    composer.fill("Brouillon non publié")
    composer.evaluate("node => { node.focus(); node.setSelectionRange(4, 12, 'forward'); }")
    page.evaluate("window.__emitSnapshot()")
    restored = page.locator('[data-action="compose-message"]')
    assert restored.input_value() == "Brouillon non publié"
    selection = restored.evaluate(
        "node => ({focused: document.activeElement === node, start: node.selectionStart, end: node.selectionEnd})"
    )
    assert selection == {"focused": True, "start": 4, "end": 12}


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page_errors = []
        console_errors = []
        for width, height in ((1024, 800), (390, 844)):
            page = browser.new_page()
            page.set_default_timeout(5_000)
            page.set_default_navigation_timeout(10_000)
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.on(
                "console",
                lambda message: console_errors.append(message.text)
                if message.type == "error"
                else None,
            )
            install_runtime_stubs(page)
            assert_layout(page, width, height)
            if width == 1024:
                page.get_by_role("tab", name="Échecs à suivre").click()
                page.get_by_text("Échecs indisponibles", exact=False).wait_for()
                page.get_by_role("tab", name="Conversation").click()
                assert_snapshot_preserves_draft(page)
            page.screenshot(
                path=ROOT / ".superpowers" / "sdd" / f"ui-task-3-{width}.png",
                full_page=True,
            )
            page.close()
        browser.close()
    assert page_errors == [], page_errors
    forbidden_console = ("unhandled", "uncaught", "token", "secret", "x-collab-session")
    assert not any(
        fragment in message.lower()
        for message in console_errors
        for fragment in forbidden_console
    ), console_errors
    print("headless PASS: 1024x800, 390x844, draft/focus/selection, no page errors/unhandled")


if __name__ == "__main__":
    main()
