"""The bundled dashboard, driven in a real browser against a real backend.

Skipped when Playwright or a browser is not installed. Nothing here mocks the page: the test
types into the prompt and reads what the user would see.
"""

from __future__ import annotations

import io
import threading
import time
from pathlib import Path

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

    thread = threading.Thread(
        target=serve,
        kwargs={"out": io.StringIO(), "on_ready": on_ready, "token": "browser-token"},
        daemon=True,
    )
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
    page.wait_for_function(
        "document.querySelector('#status-model').textContent !== ''"
    )  # the session is open
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

    _send(dashboard, '<img src=x onerror="window.__pwned = true"> **not html**')
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
    dashboard.wait_for_function(
        "document.querySelector('.message.user')?.textContent === 'first conversation'"
    )
    assert dashboard.inner_text(".message.assistant") == "You said: first conversation"


def test_sessions_page_searches_renames_and_pins(dashboard):
    _send(dashboard, "the launch is on friday")
    dashboard.wait_for_selector(".message.assistant")

    dashboard.click("[data-tab=sessions]")
    dashboard.wait_for_selector("#session-results .row")

    # Search across every stored message.
    dashboard.fill("#session-search", "launch")
    dashboard.wait_for_function(
        "document.querySelector('#session-results h3')?.textContent.includes('match')"
    )
    assert "the launch is on friday" in dashboard.inner_text("#session-results")

    # Rename through the dialog. A title is text: markup in it is never interpreted.
    dashboard.fill("#session-search", "")
    dashboard.wait_for_selector("#session-results .row [data-action=rename]")
    dashboard.click("#session-results .row [data-action=rename]")
    dashboard.wait_for_selector("#ask-text")
    dashboard.fill("#ask-text", '<img src=x onerror="window.__pwned = true">')
    dashboard.click("dialog button.primary")
    dashboard.wait_for_function(
        "document.querySelector('#session-results').innerText.includes('<img src=x')"
    )
    assert dashboard.evaluate("window.__pwned") is None

    # Pin it: the row says so, and the sidebar list keeps working.
    dashboard.click("#session-results .row [data-action=pin]")
    dashboard.wait_for_function(
        "document.querySelector('#session-results').innerText.includes('pinned')"
    )

    # Archive hides it; the checkbox brings it back.
    dashboard.click("#session-results .row [data-action=archive]")
    dashboard.wait_for_function(
        "document.querySelector('#session-results').innerText.includes('No sessions yet')"
    )
    dashboard.check("#session-archived")
    dashboard.wait_for_function(
        "document.querySelector('#session-results').innerText.includes('archived')"
    )


def test_config_page_edits_a_setting_and_confirms_a_sensitive_one(dashboard, clite_home):
    dashboard.click("[data-tab=config]")
    dashboard.wait_for_selector("#panel-config .row")
    assert "Configuration (" in dashboard.inner_text("#panel-config h2")

    # A plain setting saves without a question. Waiting on the *attribute* (not the value we
    # just typed) is what proves the panel was rebuilt from the server's answer.
    dashboard.fill("#config-display\\.skin", '"mono"')
    dashboard.click("#panel-config .row[data-key='display.skin'] [data-action=save]")
    dashboard.wait_for_function(
        "document.querySelector('#config-display\\\\.skin').getAttribute('value') === '\"mono\"'"
    )
    assert "skin: mono" in (clite_home / "config.yaml").read_text()

    # A security-relevant setting asks first: cancelling writes nothing.
    dashboard.fill("#config-approvals\\.mode", '"never"')
    dashboard.click("#panel-config .row[data-key='approvals.mode'] [data-action=save]")
    dashboard.wait_for_function("document.querySelector('dialog').open === true")
    assert "without asking" in dashboard.inner_text("#dialog")
    dashboard.click("dialog button:not([data-confirm])")  # Cancel
    dashboard.wait_for_function("document.querySelector('dialog').open === false")
    assert "never" not in (clite_home / "config.yaml").read_text()

    # Confirming writes it. The attribute only changes after the write and the re-render.
    dashboard.click("#panel-config .row[data-key='approvals.mode'] [data-action=save]")
    dashboard.wait_for_function("document.querySelector('dialog').open === true")
    dashboard.click("dialog [data-confirm=yes]")
    dashboard.wait_for_function(
        "document.querySelector('#config-approvals\\\\.mode').getAttribute('value') === '\"never\"'"
    )
    assert "mode: never" in (clite_home / "config.yaml").read_text()


def test_credentials_page_stores_and_deletes_a_secret(dashboard, clite_home):
    from clite.core.env import SecretSpec, register_secret

    register_secret(SecretSpec(name="CLITE_PAGE_CREDENTIAL", description="for the browser test"))
    dashboard.click("[data-tab=credentials]")
    row = "#panel-credentials .row[data-name='CLITE_PAGE_CREDENTIAL']"
    dashboard.wait_for_selector(row)
    assert "not set" in dashboard.inner_text(row)

    dashboard.fill(f"{row} input", "sk-page-1234567890")
    dashboard.click(f"{row} [data-action=save]")
    # The row is rebuilt from the server's answer, which never carries the value.
    dashboard.wait_for_function(
        f"document.querySelector(\"{row}\").classList.contains('filled')"
    )
    assert "sk-page-1234567890" in (clite_home / ".env").read_text()
    assert dashboard.input_value(f"{row} input") == ""  # never read back into the page

    dashboard.click(f"{row} [data-action=delete]")
    dashboard.wait_for_function("document.querySelector('dialog').open === true")
    dashboard.click("dialog [data-confirm=yes]")
    dashboard.wait_for_function(
        f"!document.querySelector(\"{row}\").classList.contains('filled')"
    )
    assert "sk-page-1234567890" not in (clite_home / ".env").read_text()


def test_cron_page_creates_a_job_and_shows_its_last_output(dashboard, clite_home):
    from clite.cron.jobs import get_job_store

    dashboard.click("[data-tab=cron]")
    dashboard.wait_for_selector("#cron-new")
    dashboard.click("#cron-new")
    dashboard.wait_for_selector("#cron-prompt")
    dashboard.fill("#cron-prompt", "summarise the open pull requests")
    dashboard.fill("#cron-schedule", "every 1h")
    dashboard.fill("#cron-name", "hourly digest")
    dashboard.click("dialog [data-action=create]")
    dashboard.wait_for_function(
        "document.querySelector('#panel-cron').innerText.includes('hourly digest')"
    )

    # A finished run's saved output opens in a dialog, as text.
    store = get_job_store()
    job = next(entry for entry in store.list() if entry.get("name") == "hourly digest")
    path = store.save_output(job["id"], "the report body\n<script>window.__pwned = true</script>")
    store.mark_finished(job["id"], status="ok", output_path=str(path))
    dashboard.click("#panel-cron .row [data-action=output]")
    dashboard.wait_for_selector("#cron-output")
    assert "the report body" in dashboard.inner_text("#cron-output")
    assert dashboard.evaluate("window.__pwned") is None  # output is text, never markup


def test_memory_page_adds_edits_and_removes_an_entry(dashboard, clite_home):
    dashboard.click("[data-tab=memory]")
    dashboard.wait_for_selector("#panel-memory [data-action='add-memory']")

    dashboard.click("#panel-memory [data-action='add-memory']")
    dashboard.wait_for_selector("#ask-text")
    dashboard.fill("#ask-text", "the launch is on friday")
    dashboard.click("dialog button.primary")
    dashboard.wait_for_function(
        "document.querySelector('#panel-memory').innerText.includes('the launch is on friday')"
    )
    assert "the launch is on friday" in (clite_home / "memories" / "MEMORY.md").read_text()

    # Edit it through the same dialog.
    dashboard.click("#panel-memory .row[data-target=memory] [data-action=edit]")
    dashboard.wait_for_selector("#ask-text")
    dashboard.fill("#ask-text", "the launch is on monday")
    dashboard.click("dialog button.primary")
    dashboard.wait_for_function(
        "document.querySelector('#panel-memory').innerText.includes('monday')"
    )
    assert "monday" in (clite_home / "memories" / "MEMORY.md").read_text()

    # And remove it. (The user section is empty from the start, so waiting for the text
    # "Empty." would pass at once; wait for the memory row itself to go.)
    dashboard.click("#panel-memory .row[data-target=memory] [data-action=remove]")
    dashboard.wait_for_function(
        "document.querySelectorAll('#panel-memory .row[data-target=memory]').length === 0"
    )
    assert "monday" not in (clite_home / "memories" / "MEMORY.md").read_text()


def test_logs_page_shows_a_filtered_tail(dashboard, clite_home):
    from clite.core.constants import get_logs_dir

    logs = get_logs_dir()
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "agent.log").write_text(
        "2026-10-08 10:00:00 INFO    clite.agent: starting up\n"
        "2026-10-08 10:00:01 ERROR   clite.rpc: <script>window.__pwned = true</script>\n"
    )

    dashboard.click("[data-tab=logs]")
    dashboard.wait_for_selector("#logs-body")
    dashboard.wait_for_function(
        "document.querySelector('#logs-body').textContent.includes('starting up')"
    )
    assert dashboard.evaluate("window.__pwned") is None  # a log line is text, never markup

    dashboard.select_option("#logs-level", "error")
    dashboard.wait_for_function(
        "!document.querySelector('#logs-body').textContent.includes('starting up')"
    )
    assert "clite.rpc" in dashboard.inner_text("#logs-body")


def test_hooks_and_mcp_page_reports_status_only(dashboard, clite_home):
    (clite_home / "config.yaml").write_text(
        "model:\n  provider: mock\n  default: mock-1\n"
        "hooks:\n  pre_tool_call:\n    - command: 'echo checking'\n"
    )
    dashboard.click("[data-tab=hooks]")
    dashboard.wait_for_selector("#panel-hooks .row")
    text = dashboard.inner_text("#panel-hooks")
    assert "pre_tool_call" in text and "waiting for approval" in text
    assert "clite hooks approve" in text
    # Approving is deliberately not offered here: it stays a local command.
    assert dashboard.locator("#panel-hooks button").count() == 0


def test_two_sessions_run_at_once_without_mixing_events(dashboard):
    _send(dashboard, "the first conversation")
    dashboard.wait_for_selector(".message.assistant")
    first = dashboard.inner_text(".message.assistant")

    # A second conversation, open at the same time in the same connection.
    dashboard.click("#new-chat")
    dashboard.wait_for_function("document.querySelectorAll('#open-sessions button').length === 2")
    dashboard.wait_for_function("document.querySelectorAll('#transcript .message').length === 0")
    _send(dashboard, "the second conversation")
    dashboard.wait_for_function(
        "document.querySelector('.message.assistant')?.textContent === 'You said: the second conversation'"
    )

    # Each transcript holds only its own conversation.
    assert "the first conversation" not in dashboard.inner_text("#transcript")

    # Back to the first one (the sidebar keeps them in the order they were opened).
    dashboard.locator("#open-sessions button").nth(0).click()
    dashboard.wait_for_function(
        "document.querySelector('.message.user')?.textContent === 'the first conversation'"
    )
    assert "the second conversation" not in dashboard.inner_text("#transcript")
    assert dashboard.inner_text(".message.assistant") == first

    # The sidebar lists both open conversations, and switching keeps working both ways.
    assert dashboard.locator("#open-sessions button").count() == 2
    dashboard.locator("#open-sessions button").nth(1).click()
    dashboard.wait_for_function(
        "document.querySelector('.message.user')?.textContent === 'the second conversation'"
    )
    assert "the first conversation" not in dashboard.inner_text("#transcript")


def test_closing_an_open_session_keeps_the_other_one(dashboard):
    _send(dashboard, "keep me")
    dashboard.wait_for_selector(".message.assistant")
    dashboard.click("#new-chat")
    dashboard.wait_for_function("document.querySelectorAll('#open-sessions button').length === 2")
    _send(dashboard, "throw me away")
    dashboard.wait_for_function(
        "document.querySelector('.message.assistant')?.textContent === 'You said: throw me away'"
    )

    # Close the active one; the other stays open and becomes active.
    dashboard.click("#open-sessions button.current .close")
    dashboard.wait_for_function("document.querySelectorAll('#open-sessions button').length === 1")
    dashboard.wait_for_function(
        "document.querySelector('.message.user')?.textContent === 'keep me'"
    )
    assert dashboard.inner_text(".message.assistant") == "You said: keep me"


def test_the_dashboard_reconnects_and_keeps_the_conversation(clite_home, browser):
    """The socket drops and comes back: the conversation is still there and still works.

    The drop is forced from the browser side (`route_web_socket`), which is what a flaky network
    or a sleeping laptop looks like to the page.
    """
    box, thread = _start("model:\n  provider: mock\n  default: mock-1\n", clite_home)
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    sockets = []

    def on_socket(socket):
        sockets.append(socket)
        socket.connect_to_server()

    page.route_web_socket(lambda url: "/api/ws" in url, on_socket)
    try:
        page.goto(f"http://127.0.0.1:{box['port']}/#token={box['token']}")
        page.wait_for_selector("#status-connection.online")
        page.wait_for_function("document.querySelector('#status-model').textContent !== ''")
        page.fill("#prompt", "before the drop")
        page.press("#prompt", "Enter")
        page.wait_for_selector(".message.assistant")
        before = page.inner_text(".message.assistant")
        assert len(sockets) == 1

        sockets[0].close()
        page.wait_for_function(
            "document.querySelector('#status-connection').textContent.includes('reconnecting')"
        )
        page.wait_for_function(
            "document.querySelector('#status-connection').textContent === 'connected'",
            timeout=30_000,
        )
        assert len(sockets) == 2  # the page opened a new one by itself

        # The transcript survived the round trip, and the session is usable again.
        assert page.inner_text(".message.assistant") == before
        page.fill("#prompt", "after the drop")
        page.press("#prompt", "Enter")
        page.wait_for_function(
            "(() => { const all = document.querySelectorAll('.message.assistant');"
            " return all.length > 1 && all[all.length - 1].textContent === 'You said: after the drop'; })()"
        )
        assert errors == []
    finally:
        page.close()
        box["server"].should_exit = True
        thread.join(timeout=10)


NOTIFICATION_RECORDER = """(() => {
  window.__notifications = [];
  class FakeNotification {
    static permission = "granted";
    static requestPermission() { return Promise.resolve("granted"); }
    constructor(title, options) {
      window.__notifications.push({title, body: (options || {}).body || ""});
    }
  }
  Object.defineProperty(window, "Notification", {value: FakeNotification, configurable: true});
  // A headless window reports focus; the point of a notification is the window nobody watches.
  Object.defineProperty(document, "hasFocus", {value: () => false, configurable: true});
})()"""


def test_a_finished_turn_notifies_only_when_the_window_is_not_watched(clite_home, browser):
    box, thread = _start("model:\n  provider: mock\n  default: mock-1\n", clite_home)
    page = browser.new_page()
    page.add_init_script(script=NOTIFICATION_RECORDER)
    try:
        page.goto(f"http://127.0.0.1:{box['port']}/#token={box['token']}")
        page.wait_for_selector("#status-connection.online")
        # The socket is up before the first session is: sending now would find no view.
        page.wait_for_function("document.querySelector('#status-model').textContent !== ''")
        page.fill("#prompt", "hello")
        page.press("#prompt", "Enter")
        page.wait_for_function("window.__notifications.length > 0")
        sent = page.evaluate("window.__notifications")
        # A fresh session has no title yet, so the fallback name stands in for it.
        assert sent[0]["title"]
        assert "You said: hello" in sent[0]["body"]

        # A window that has focus already shows the answer: no notification.
        page.evaluate("Object.defineProperty(document, 'hasFocus', {value: () => true})")
        page.evaluate("window.__notifications.length = 0")
        page.fill("#prompt", "again")
        page.press("#prompt", "Enter")
        page.wait_for_function("document.querySelectorAll('.message.assistant').length > 1")
        assert page.evaluate("window.__notifications") == []
    finally:
        page.close()
        box["server"].should_exit = True
        thread.join(timeout=10)


def test_the_notification_setting_can_turn_notifications_off(clite_home, browser):
    box, thread = _start("model:\n  provider: mock\n  default: mock-1\n", clite_home)
    page = browser.new_page()
    page.add_init_script(script=NOTIFICATION_RECORDER)
    try:
        page.goto(f"http://127.0.0.1:{box['port']}/#token={box['token']}")
        page.wait_for_selector("#status-connection.online")
        page.wait_for_function("document.querySelector('#status-model').textContent !== ''")

        # Turned off from the config page, like any other setting.
        page.click("[data-tab=config]")
        page.wait_for_selector("#panel-config .row")
        page.fill("#config-dashboard\\.notifications", "false")
        page.click("#panel-config .row[data-key='dashboard.notifications'] [data-action=save]")
        page.wait_for_function(
            "document.querySelector('#config-dashboard\\\\.notifications')"
            ".getAttribute('value') === 'false'"
        )
        page.click("[data-tab=chat]")

        page.fill("#prompt", "quiet")
        page.press("#prompt", "Enter")
        page.wait_for_selector(".message.assistant")
        page.wait_for_timeout(200)
        assert page.evaluate("window.__notifications") == []
    finally:
        page.close()
        box["server"].should_exit = True
        thread.join(timeout=10)


def test_a_dropped_file_is_attached_and_reaches_the_agent(dashboard, clite_home):
    """Dropping a file puts a chip in the composer, and sending hands the agent a real path."""
    dashboard.evaluate(
        """() => {
          const transfer = new DataTransfer();
          transfer.items.add(new File(["notes from a drop\\n"], "dropped.txt", {type: "text/plain"}));
          document.querySelector("#view-chat").dispatchEvent(
            new DragEvent("drop", {dataTransfer: transfer, bubbles: true, cancelable: true}));
        }"""
    )
    dashboard.wait_for_selector("#attachments .chip[data-name='dropped.txt']")

    _send(dashboard, "read this")
    dashboard.wait_for_function(
        "(() => { const all = document.querySelectorAll('.message.assistant');"
        " return all.length && all[all.length - 1].textContent.includes('[attached: '); })()"
    )
    # The chip is gone, and the file really is on disk where the message said it was.
    assert dashboard.query_selector("#attachments .chip") is None
    shown = dashboard.inner_text(".message.assistant")
    stored = Path(shown.split("[attached: ")[1].rstrip("]"))
    assert stored.read_text() == "notes from a drop\n"
    assert stored.parent == clite_home / "cache" / "attachments"


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


def test_a_plugin_page_runs_in_an_isolated_frame(clite_home, browser):
    """The page a plugin ships is another origin and cannot reach into the dashboard.

    This is the behaviour the server tests can only argue about: here a browser decides. The
    frame has no ``allow-same-origin``, so its document gets an opaque origin (``"null"``) and
    every attempt to read the dashboard — its DOM, its storage, its socket — fails.
    """
    (clite_home / "plugins" / "board" / "dashboard").mkdir(parents=True)
    (clite_home / "plugins" / "board" / "plugin.yaml").write_text(
        "name: board\ndashboard:\n  title: Deploy board\n  page: dashboard/index.html\n"
    )
    (clite_home / "plugins" / "board" / "__init__.py").write_text("def register(ctx):\n    pass\n")
    (clite_home / "plugins" / "board" / "dashboard" / "index.html").write_text(
        "<!doctype html><h1>deploy board</h1>"
    )
    box, thread = _start(
        "model:\n  provider: mock\n  default: mock-1\nplugins:\n  enabled: [board]\n", clite_home
    )
    page = browser.new_page()
    try:
        page.goto(f"http://127.0.0.1:{box['port']}/#token={box['token']}")
        page.wait_for_selector("#status-connection.online")
        page.click("[data-tab=plugins]")
        page.wait_for_selector("iframe.plugin-page")
        frame = page.frame_locator("iframe.plugin-page")

        sandbox = page.get_attribute("iframe.plugin-page", "sandbox")
        assert "allow-scripts" in sandbox and "allow-same-origin" not in sandbox
        assert page.get_attribute("iframe.plugin-page", "referrerpolicy") == "no-referrer"
        # Its own origin: a different port from the dashboard's.
        url = page.get_attribute("iframe.plugin-page", "src")
        assert url.startswith("http://127.0.0.1:") and not url.startswith(f"http://127.0.0.1:{box['port']}/")
        frame.locator("h1").wait_for()
        assert frame.locator("h1").inner_text() == "deploy board"

        # The frame's document has an opaque origin, and the dashboard is out of reach.
        # `self.origin` is the document's own; `location.origin` still serializes the URL.
        handle = page.query_selector("iframe.plugin-page")
        child = handle.content_frame()
        assert child.evaluate("self.origin") == "null"
        with pytest.raises(sync_api.Error):
            child.evaluate("window.parent.document.title")
        # And it neither sees the session token nor can store anything on this origin.
        storage = child.evaluate(
            "(() => { try { return JSON.stringify(Object.entries(sessionStorage)); }"
            " catch (error) { return 'blocked: ' + error.name; } })()"
        )
        assert storage == "[]" or storage.startswith("blocked:")
    finally:
        page.close()
        box["server"].should_exit = True
        thread.join(timeout=10)
