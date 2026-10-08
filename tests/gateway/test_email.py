"""Email platform plugin tests against local IMAP and SMTP protocol fakes."""

from __future__ import annotations

import socketserver
import threading
import time
from email import policy
from email.parser import BytesParser
from typing import Any, cast

from clite.gateway.platforms.base import PLATFORMS
from clite.plugins.manager import ensure_plugins_loaded


class _ImapHandler(socketserver.StreamRequestHandler):
    message = (
        b"From: Allowed <allowed@example.test>\r\n"
        b"To: bot@example.test\r\n"
        b"Subject: Question\r\n"
        b"Message-ID: <question@example.test>\r\n"
        b"References: <root@example.test>\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Please reply.\r\n"
    )

    def handle(self) -> None:
        self.wfile.write(b"* OK fake IMAP ready\r\n")
        self.wfile.flush()
        while line := self.rfile.readline():
            tag, command, *_args = line.decode().strip().split()
            command = command.upper()
            if command == "CAPABILITY":
                self.wfile.write(b"* CAPABILITY IMAP4rev1\r\n")
                self.wfile.write(f"{tag} OK capability completed\r\n".encode())
            elif command == "LOGIN":
                self.wfile.write(f"{tag} OK logged in\r\n".encode())
            elif command == "SELECT":
                self.wfile.write(b"* 1 EXISTS\r\n")
                self.wfile.write(f"{tag} OK selected\r\n".encode())
            elif command == "SEARCH":
                self.wfile.write(b"* SEARCH 1\r\n")
                self.wfile.write(f"{tag} OK search completed\r\n".encode())
            elif command == "FETCH":
                self.wfile.write(f"* 1 FETCH (RFC822 {{{len(self.message)}}}\r\n".encode())
                self.wfile.write(self.message)
                self.wfile.write(b")\r\n")
                self.wfile.write(f"{tag} OK fetch completed\r\n".encode())
            elif command in {"STORE", "CLOSE", "LOGOUT"}:
                self.wfile.write(f"{tag} OK done\r\n".encode())
                if command == "LOGOUT":
                    return
            else:
                self.wfile.write(f"{tag} BAD unsupported\r\n".encode())
            self.wfile.flush()


def _address(command: str) -> str:
    """``FROM:<a@b>`` or ``TO:<a@b>`` -> ``a@b``."""
    return command.partition(":")[2].strip().strip("<>")


class _SmtpHandler(socketserver.StreamRequestHandler):
    """Just enough SMTP for the reply the plugin sends to land in ``server.messages``.

    ``smtpd`` and ``asyncore``, which this used to lean on, are gone from the standard library
    since Python 3.12; the fake is small enough to write out.
    """

    def handle(self) -> None:
        server = cast("_SmtpServer", self.server)
        mailfrom = ""
        rcpttos: list[str] = []
        self.wfile.write(b"220 fake SMTP ready\r\n")
        self.wfile.flush()
        while line := self.rfile.readline():
            verb, _, rest = line.decode("latin-1").strip().partition(" ")
            verb = verb.upper()
            if verb in {"HELO", "EHLO"}:
                self.wfile.write(b"250 fake\r\n")
            elif verb == "MAIL":
                mailfrom = _address(rest)
                self.wfile.write(b"250 sender ok\r\n")
            elif verb == "RCPT":
                rcpttos.append(_address(rest))
                self.wfile.write(b"250 recipient ok\r\n")
            elif verb == "DATA":
                self.wfile.write(b"354 send it\r\n")
                self.wfile.flush()
                data = b""
                while (chunk := self.rfile.readline()) and chunk not in {b".\r\n", b".\n"}:
                    data += chunk
                server.messages.append((mailfrom, rcpttos, data))
                self.wfile.write(b"250 accepted\r\n")
            elif verb == "QUIT":
                self.wfile.write(b"221 bye\r\n")
                self.wfile.flush()
                return
            else:
                self.wfile.write(b"250 ok\r\n")
            self.wfile.flush()


class _SmtpServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _SmtpHandler)
        self.messages: list[tuple[str, list[str], bytes]] = []

    def close(self) -> None:
        self.server_close()


def _wait_for(predicate, timeout: float = 3) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_email_plugin_polls_local_imap_and_replies_over_local_smtp(monkeypatch):
    imap = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _ImapHandler)
    imap.daemon_threads = True
    imap_thread = threading.Thread(target=imap.serve_forever, daemon=True)
    imap_thread.start()
    smtp = _SmtpServer()
    smtp_thread = threading.Thread(target=smtp.serve_forever, daemon=True)
    smtp_thread.start()
    monkeypatch.setenv("EMAIL_IMAP_PASSWORD", "imap-secret")
    monkeypatch.setenv("EMAIL_SMTP_PASSWORD", "smtp-secret")

    class Runner:
        def __init__(self) -> None:
            self.events: list[Any] = []

        def dispatch(self, event):
            self.events.append(event)
            adapter.send(
                event.source.chat_id,
                "The answer",
                reply_to=event.message_id,
                thread_id=event.source.thread_id,
            )

    try:
        ensure_plugins_loaded()
        runner = Runner()
        adapter = PLATFORMS["email"](
            {
                "imap_host": "127.0.0.1",
                "imap_port": imap.server_address[1],
                "imap_ssl": False,
                "smtp_host": "127.0.0.1",
                "smtp_port": smtp.socket.getsockname()[1],
                "smtp_starttls": False,
                "smtp_auth": False,
                "from_address": "bot@example.test",
                "allowed_users": ["allowed@example.test"],
                "poll_interval": 0.01,
            },
            runner,
        )
        adapter.connect()
        assert _wait_for(lambda: len(smtp.messages) == 1)
        assert len(runner.events) == 1
        event = runner.events[0]
        assert event.source.user_id == "allowed@example.test"
        assert event.source.thread_id == "<root@example.test>"
        sent = BytesParser(policy=policy.default).parsebytes(smtp.messages[0][2])
        assert sent["To"] == "allowed@example.test"
        assert sent["In-Reply-To"] == "<question@example.test>"
        assert sent["References"] == "<root@example.test>"
        assert sent.get_content().strip() == "The answer"
        rejected = _ImapHandler.message.replace(b"allowed@example.test", b"stranger@example.test")
        assert adapter.to_event(rejected) is None
    finally:
        if "adapter" in locals():
            adapter.disconnect()
        smtp.close()
        imap.shutdown()
        imap.server_close()
