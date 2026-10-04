"""The bundled dashboard, driven in a real browser against a real backend.

Skipped when Playwright or a browser is not installed. Nothing here mocks the page: the test
types into the prompt and reads what the user would see.
"""

from __future__ import annotations

import io
import threading
import time

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from clite.server.run import serve  # noqa: E402

pytestmark = [pytest.mark.browser, pytest.mark.platforms("posix")]


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as playwright:
        try:
            instance = playwright.chromium.launch(args=["--no-sandbox"])
        except Exception as exc:  # noqa: BLE001 - no browser on this machine
            pytest.skip(f"cannot launch Chromium: {exc}")
        yield instance
        instance.close()


def _start(config_text, clite_home):
    (clite_home / "config.yaml").write_text(config_text)
    ready, box = threading.Event(), {}

    def on_ready(port, token, server):
        box.update(port=port, token=token, server=server)
        ready.set()

    thread = threading.Thread(target=serve, kwargs={"out": io.StringIO(), "on_ready": on_ready, "token": "browser-token"},
                              daemon=True)
    thread.start()
    assert ready.wait(10)
    return box, thread


@pytest.fixture
def dashboard(clite_home, browser, tmp_path):
    box, thread = _start("model:\n  provider: mock\n  default: mock-1\n", clite_home)
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(f"http://127.0.0.1:{box['port']}/#token={box['token']}")
    page.wait_for_selector("#status-connection.online")
    page.wait_for_function("document.querySelector('#status-model').textContent !== ''")  # the session is open
    yield page
    assert errors == [], f"JavaScript errors on the page: {errors}"
    page.close()
    box["server"].should_exit = True
    thread.join(timeout=10)


def _send(page, text):
    page.fill("#prompt", text)
    page.press("#prompt", "Enter")


def test_connects_and_hides_the_token(dashboard):
    assert dashboard.inner_text("#status-connection") == "connected"
    assert "mock-1" in dashboard.inner_text("#status-model")
    assert "token" not in dashboard.url  # removed from the address bar once read


def test_chat_round_trip_streams_into_the_transcript(dashboard):
    _send(dashboard, "hello dashboard")
    dashboard.wait_for_selector(".message.assistant")
    dashboard.wait_for_function("document.querySelector('#send').hidden === false")
    assert dashboard.inner_text(".message.user") == "hello dashboard"
    assert dashboard.inner_text(".message.assistant") == "You said: hello dashboard"
    assert dashboard.input_value("#prompt") == ""


def test_tool_calls_are_shown_with_their_outcome(dashboard, tmp_path):
    (tmp_path / "notes.txt").write_text("the meeting moved to 3pm\n")
    _send(dashboard, '!read_file {"path": "notes.txt"}')
    dashboard.wait_for_selector(".tool:not(.running)")
    assert dashboard.inner_text(".tool").startswith("✓ read_file notes.txt")
    dashboard.wait_for_selector(".message.assistant")
    assert "the meeting moved to 3pm" in dashboard.inner_text(".message.assistant")


def test_dangerous_command_asks_for_approval_in_a_dialog(dashboard, tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    _send(dashboard, '!terminal {"command": "rm -rf ./scratch"}')
    dashboard.wait_for_selector("#approval-command")
    assert dashboard.inner_text("#approval-command") == "rm -rf ./scratch"
    assert scratch.exists()  # nothing ran while the question was open
    dashboard.click("[data-choice=once]")
    dashboard.wait_for_selector(".tool:not(.running)")
    deadline = time.monotonic() + 5
    while scratch.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not scratch.exists()


def test_denying_keeps_the_files(dashboard, tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    _send(dashboard, '!terminal {"command": "rm -rf ./scratch"}')
    dashboard.click("[data-choice=deny]")
    dashboard.wait_for_selector(".tool.failed")
    assert scratch.exists()


def test_slash_commands_and_script_injection_safety(dashboard):
    _send(dashboard, "/status")
    dashboard.wait_for_selector(".message.notice")
    assert "mock-1 via mock" in dashboard.inner_text(".message.notice")

    _send(dashboard, "<img src=x onerror=\"window.__pwned = true\"> **not html**")
    dashboard.wait_for_selector(".message.assistant")
    assert dashboard.evaluate("window.__pwned") is None  # text is never interpreted as markup
    assert "<img src=x" in dashboard.inner_text(".message.assistant")


def test_sessions_can_be_started_and_reopened(dashboard):
    _send(dashboard, "first conversation")
    dashboard.wait_for_selector("#sessions button")
    dashboard.click("#new-chat")
    dashboard.wait_for_function("document.querySelectorAll('#transcript .message').length === 0")
    _send(dashboard, "second conversation")
    dashboard.wait_for_function("document.querySelectorAll('#sessions button').length === 2")
    dashboard.locator("#sessions button", has_text="first conversation").click()
    dashboard.wait_for_function("document.querySelector('.message.user')?.textContent === 'first conversation'")
    assert dashboard.inner_text(".message.assistant") == "You said: first conversation"


def test_other_tabs_list_what_is_installed(dashboard):
    dashboard.click("[data-tab=skills]")
    dashboard.wait_for_selector("#panel-skills .row")
    assert "/skill-authoring" in dashboard.inner_text("#panel-skills")
    dashboard.click("[data-tab=plugins]")
    dashboard.wait_for_selector("#panel-plugins .row")
    assert "audit-log" in dashboard.inner_text("#panel-plugins")
    dashboard.locator("#panel-plugins .row", has_text="audit-log").locator("button").click()
    dashboard.wait_for_function("document.querySelector('#panel-plugins').innerText.includes('loaded')")
    dashboard.click("[data-tab=tools]")
    dashboard.wait_for_selector("#panel-tools .row")
    assert "read_file" in dashboard.inner_text("#panel-tools")
    dashboard.click("[data-tab=cron]")
    dashboard.wait_for_selector("#panel-cron .empty")


def test_first_run_setup_screen(clite_home, browser):
    box, thread = _start("", clite_home)
    page = browser.new_page()
    try:
        page.goto(f"http://127.0.0.1:{box['port']}/#token={box['token']}")
        page.wait_for_selector("#setup-provider")
        page.select_option("#setup-provider", "ollama")
        page.fill("#setup-model", "llama-local")
        page.click("dialog button.primary")
        page.wait_for_function("document.querySelector('#status-model').textContent.includes('llama-local')")
        assert "provider: ollama" in (clite_home / "config.yaml").read_text()
    finally:
        page.close()
        box["server"].should_exit = True
        thread.join(timeout=10)
