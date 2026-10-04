"""``RpcSession``: a ``ChatSession`` whose callbacks become JSON-RPC events."""

from __future__ import annotations

import logging
import threading
import uuid
from typing import TYPE_CHECKING, Any

from clite.agent import AgentCallbacks
from clite.agent.messages import content_text
from clite.core.config import config_get
from clite.core.errors import CliteError
from clite.rpc.contracts import schema
from clite.runtime.commands import BUSY_ALLOW, resolve_command, split_command
from clite.runtime.presentation import result_failed, tool_preview
from clite.runtime.session import ACTION_NEW, ACTION_SUBMIT, ChatSession
from clite.state.db import get_session_db

if TYPE_CHECKING:
    from clite.rpc.server import RpcServer

logger = logging.getLogger("clite.rpc.session")

RESULT_PREVIEW_CHARS = 400


class RpcSession:
    def __init__(self, server: RpcServer, params: schema.SessionCreateParams) -> None:
        self.server = server
        self.id = ""  # the runtime id; set by the server when the session is registered
        stored_id = None
        if params.resume:
            row = get_session_db().find_session(params.resume)
            if row is None:
                raise CliteError(f"no stored session matches {params.resume!r}")
            stored_id = row["id"]
        self.chat = ChatSession(
            platform=params.platform or server.platform, callbacks=self._callbacks(), session_id=stored_id,
            model=params.model, provider=params.provider, toolsets=params.toolsets, cwd=params.cwd, yolo=params.yolo,
            client=server.client_factory() if server.client_factory else None,
        )
        self._lock = threading.Lock()
        self._queue: list[tuple[str, str]] = []  # (turn id, text) waiting for the running turn
        self._worker: threading.Thread | None = None

    # ── callbacks -> events ──────────────────────────────────────────────────────────────

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        self.server.emit(event_type, self.id, payload)

    def _callbacks(self) -> AgentCallbacks:
        def on_message(message: dict[str, Any]) -> None:
            self._emit("message.complete", {
                "role": message.get("role", "assistant"), "text": content_text(message.get("content")),
                "tool_calls": [call["function"]["name"] for call in message.get("tool_calls") or []],
            })

        def on_tool_complete(call_id: str, name: str, args: dict[str, Any], result: str, seconds: float) -> None:
            self._emit("tool.complete", {"call_id": call_id, "name": name, "duration": round(seconds, 3),
                                         "failed": result_failed(result), "result_preview": result[:RESULT_PREVIEW_CHARS]})

        def on_status(kind: str, text: str) -> None:
            if kind == "title":
                self._emit("session.info", self.info())
            else:
                self._emit("status.update", {"kind": kind, "text": text})

        def approve(*, command: str, description: str, pattern_keys: list[str]) -> str:
            reply = self.server.request_client(
                "approval.request",
                {"session_id": self.id, "command": command, "description": description, "pattern_keys": pattern_keys},
                timeout=float(config_get("approvals.timeout", 300) or 300),
            )
            return reply["choice"] if reply else "deny"  # no answer is a no

        def clarify(question: str, choices: list[str]) -> str:
            reply = self.server.request_client("clarify.request",
                                               {"session_id": self.id, "question": question, "choices": choices})
            return reply["answer"] if reply else ""

        return AgentCallbacks(
            on_delta=lambda text: self._emit("message.delta", {"text": text}),
            on_reasoning=lambda text: self._emit("reasoning.delta", {"text": text}),
            on_step=lambda iteration: self._emit("turn.step", {"iteration": iteration}),
            on_message=on_message,
            on_tool_start=lambda call_id, name, args: self._emit(
                "tool.start", {"call_id": call_id, "name": name, "args": args, "preview": tool_preview(name, args)}),
            on_tool_complete=on_tool_complete,
            on_status=on_status,
            on_subagent=lambda kind, payload: self._emit("subagent.update", {
                "event": kind, "index": int(payload.get("index", 0)), "goal": str(payload.get("goal", "")),
                "tool": str(payload.get("tool", "")), "status": str(payload.get("status", ""))}),
            approve=approve,
            clarify=clarify,
        )

    # ── state ────────────────────────────────────────────────────────────────────────────

    @property
    def busy(self) -> bool:
        worker = self._worker
        return self.chat.busy or (worker is not None and worker.is_alive())

    def info(self) -> schema.SessionInfo:
        info = self.chat.info()
        stored = info.pop("session_id")
        return schema.SessionInfo(session_id=self.id, stored_session_id=stored, **info)

    def history(self) -> list[schema.TranscriptMessage]:
        return [
            schema.TranscriptMessage(
                role=message["role"], text=content_text(message.get("content")), tool_name=message.get("name") or "",
                tool_calls=[call["function"]["name"] for call in message.get("tool_calls") or []],
                is_summary=bool(message.get("is_summary")), timestamp=message.get("timestamp"),
            )
            for message in self.chat.agent.messages
        ]

    # ── turns ────────────────────────────────────────────────────────────────────────────

    def submit(self, text: str, busy_mode: str | None = None) -> schema.PromptSubmitResult:
        from clite.rpc.server import SESSION_BUSY, RpcError

        mode = busy_mode or str(config_get("display.busy_input_mode", "interrupt"))
        turn_id = uuid.uuid4().hex[:12]
        with self._lock:
            if self.busy:
                if mode == "steer":
                    self.chat.steer(text)
                    return schema.PromptSubmitResult(accepted=True, queued=False)
                if mode == "reject":
                    raise RpcError(SESSION_BUSY, "a turn is running; interrupt it or wait for turn.complete")
                self._queue.append((turn_id, text))
                if mode == "interrupt":
                    self.chat.interrupt()
                return schema.PromptSubmitResult(accepted=True, turn_id=turn_id, queued=True)
            self._queue.append((turn_id, text))
            self._worker = threading.Thread(target=self._drain, name=f"clite-turn-{self.id}", daemon=True)
            self._worker.start()
        return schema.PromptSubmitResult(accepted=True, turn_id=turn_id)

    def _drain(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    self._worker = None
                    return
                turn_id, text = self._queue.pop(0)
            self._run_turn(turn_id, text)

    def _run_turn(self, turn_id: str, text: str) -> None:
        self._emit("turn.start", {"turn_id": turn_id, "text": text[:2000]})
        try:
            result = self.chat.submit(text)
            payload = result.to_dict()
            self._emit("turn.complete", {
                "turn_id": turn_id, "final_response": payload["final_response"], "completed": payload["completed"],
                "interrupted": payload["interrupted"], "error": payload["error"], "exit_reason": payload["exit_reason"],
                "api_calls": payload["api_calls"], "duration": payload["duration"], "usage": payload["usage"],
            })
        except Exception as exc:  # noqa: BLE001 - the client must always get a turn.complete
            logger.exception("turn failed in RPC session %s", self.id)
            self._emit("error", {"message": f"{type(exc).__name__}: {exc}"})
            self._emit("turn.complete", {"turn_id": turn_id, "final_response": "", "completed": False,
                                         "error": f"{type(exc).__name__}: {exc}", "exit_reason": "internal_error"})

    def run_slash(self, command: str) -> schema.SlashExecResult:
        from clite.rpc.server import SESSION_BUSY, RpcError

        name, _ = split_command(command)
        definition = resolve_command(name)
        if self.busy and (definition is None or definition.busy_policy != BUSY_ALLOW):
            raise RpcError(SESSION_BUSY, f"/{name} has to wait: a turn is running. Use /stop first, or try again after it.")
        result = self.chat.run_slash(command)
        if result.action == ACTION_SUBMIT:
            started = self.submit(result.text, "queue")
            return schema.SlashExecResult(text="", action=ACTION_SUBMIT, turn_id=started.turn_id, data=result.data)
        if result.action == ACTION_NEW or name in ("model", "title", "yolo", "reload", "tools", "reasoning", "compress", "undo"):
            self._emit("session.info", self.info())
        return schema.SlashExecResult(text=result.text, action=result.action, data=_jsonable(result.data))

    def close(self) -> None:
        with self._lock:
            self._queue.clear()
        self.chat.interrupt()
        worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=5)
        self.chat.close("rpc_closed")


def _jsonable(data: dict[str, Any]) -> dict[str, Any]:
    import json

    return json.loads(json.dumps(data, default=str))
