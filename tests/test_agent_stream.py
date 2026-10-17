"""Trace d'exécution des sous-agents : protocole, coalescence, capture par le parser et le recorder, routes."""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from studio.agent_stream import PREFIX, coalesce, encode, merge_stream_text, parse_line, stream_lines, trim
from studio.launcher import StreamParser, _tool_result_text

RUN_DIR = "/runs/p1"


def _ev(line: str) -> dict:
    event = parse_line(line)
    assert event is not None
    return event


def test_parse_line_tolerates_raw_and_invalid() -> None:
    assert parse_line("--- Démarrage ---") is None
    assert parse_line(PREFIX + "{pas du json") is None
    assert parse_line(PREFIX + '["liste"]') is None
    assert _ev(encode({"type": "assistant", "text": "é"}))["text"] == "é"


def test_stream_lines_translates_subagent_messages() -> None:
    tool_use = {"type": "assistant", "parent_tool_use_id": "a1", "message": {"content": [
        {"type": "thinking", "thinking": "", "signature": "x"},
        {"type": "text", "text": "Je lis le brief."},
        {"type": "tool_use", "id": "t1", "name": "Write",
         "input": {"file_path": f"{RUN_DIR}/scenario.json", "content": "x" * 5000}},
    ]}}
    lines = stream_lines(tool_use, run_dir=RUN_DIR)
    assert [_ev(line)["type"] for line in lines] == ["assistant", "tool_call"]  # réflexion vide ignorée
    call = _ev(lines[1])
    assert call["status"] == "running" and call["args"]["file_path"] == "scenario.json"
    assert len(call["args"]["content"]) < 700

    result = {"type": "user", "parent_tool_use_id": "a1", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": [{"type": "text", "text": "refusé"}]},
    ]}}
    (line,) = stream_lines(result, result_text=_tool_result_text)
    assert _ev(line) == {"type": "tool_call", "callId": "t1", "status": "error", "result": "refusé"}

    progress = {"type": "system", "subtype": "task_progress", "tool_use_id": "a1", "description": "Reading brief.json",
                "usage": {"total_tokens": 12483, "tool_uses": 1, "duration_ms": 1717}}
    assert _ev(stream_lines(progress)[0]) == {
        "type": "task", "description": "Reading brief.json", "tokens": 12483, "tool_uses": 1, "duration_ms": 1717,
    }
    prompt = {"type": "user", "parent_tool_use_id": "a1", "message": {"content": [{"type": "text", "text": "consignes"}]}}
    assert stream_lines(prompt) == []


def test_coalesce_merges_tool_call_by_call_id() -> None:
    buf: list[str] = ["--- Démarrage ---"]
    coalesce(buf, encode({"type": "tool_call", "callId": "t1", "name": "Bash", "status": "running", "args": {"command": "a"}}))
    coalesce(buf, encode({"type": "tool_call", "callId": "t2", "name": "Read", "status": "running", "args": {"file_path": "b"}}))
    merged = coalesce(buf, encode({"type": "tool_call", "callId": "t1", "status": "completed", "result": "ok"}))
    assert len(buf) == 3
    assert _ev(buf[1]) == _ev(merged) == {
        "type": "tool_call", "callId": "t1", "name": "Bash", "status": "completed", "args": {"command": "a"}, "result": "ok",
    }


def test_coalesce_without_call_id_matches_last_running_same_name() -> None:
    buf: list[str] = []
    coalesce(buf, encode({"type": "tool_call", "name": "Bash", "status": "running", "args": {"command": "a"}}))
    coalesce(buf, encode({"type": "tool_call", "name": "Bash", "status": "completed", "args": {"command": "zzz"}, "result": "r"}))
    assert len(buf) == 1 and _ev(buf[0])["args"] == {"command": "a"} and _ev(buf[0])["result"] == "r"


def test_coalesce_texts_and_task() -> None:
    buf: list[str] = []
    coalesce(buf, encode({"type": "assistant", "text": "Bon"}))
    coalesce(buf, encode({"type": "assistant", "text": "Bonjour"}))  # cumulatif
    coalesce(buf, encode({"type": "assistant", "text": " à tous"}))  # delta
    assert len(buf) == 1 and _ev(buf[0])["text"] == "Bonjour à tous"
    coalesce(buf, encode({"type": "assistant", "text": "Bonjour à tous !", "done": True}))  # fin du bloc
    coalesce(buf, encode({"type": "assistant", "text": "Autre", "done": True}))  # bloc terminé : pas de fusion
    assert len(buf) == 2 and _ev(buf[0]) == {"type": "assistant", "text": "Bonjour à tous !", "done": True}
    coalesce(buf, encode({"type": "task", "tool_uses": 1}))
    coalesce(buf, "--- brut ---")
    coalesce(buf, encode({"type": "task", "tool_uses": 2}))
    assert sum(1 for line in buf if (parse_line(line) or {}).get("type") == "task") == 1
    assert _ev(buf[2])["tool_uses"] == 2
    assert merge_stream_text("abc", "b") == "abc"


def test_trim_caps_lines_and_bytes() -> None:
    lines = [f"ligne {i} " + "x" * 100 for i in range(3000)]
    assert len(trim(lines)) == 2000
    small = trim(lines, max_bytes=10_000)
    assert sum(len(line) for line in small) <= 10_000 and small[-1] == lines[-1]


def _line(payload: dict) -> str:
    return json.dumps(payload) + "\n"


def test_stream_parser_emits_agent_stream_per_subagent() -> None:
    parser = StreamParser(RUN_DIR)
    for agent_id, role in (("a1", "scenariste"), ("a2", "voix")):
        parser.feed(_line({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": agent_id, "name": "Agent", "input": {"subagent_type": role}},
        ]}}))
    events = parser.feed(_line({"type": "assistant", "parent_tool_use_id": "a2", "message": {"content": [
        {"type": "tool_use", "id": "t9", "name": "Bash", "input": {"command": "python -m studio.tools tts"}},
    ]}}))
    assert [kind for kind, _ in events] == ["tool", "agent_stream"]
    assert events[1][1]["id"] == "a2" and events[1][1]["role"] == "voix"
    progress = parser.feed(_line({"type": "system", "subtype": "task_progress", "tool_use_id": "a1", "description": "x"}))
    assert progress[0][0] == "agent_stream" and progress[0][1]["id"] == "a1"
    # Messages du producteur : pas de trace.
    assert parser.feed(_line({"type": "assistant", "message": {"content": [{"type": "text", "text": "plan"}]}})) == []


class _FakeSession:
    def __init__(self, store: dict) -> None:
        self.store = store

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    def add(self, obj) -> None:
        obj.id = uuid.uuid4()
        self.store[obj.id] = {"log": list(obj.log), "status": obj.status}

    async def execute(self, stmt) -> None:
        values = {col.key: val.value for col, val in stmt._values.items()}
        target = stmt.whereclause.right.value  # un id, ou une liste pour `id IN (…)`
        for run_id in target if isinstance(target, list) else [target]:
            self.store[run_id].update(values)

    async def commit(self) -> None:
        return None


@pytest.mark.asyncio
async def test_recorder_writes_log_progressively(monkeypatch) -> None:
    from agent.core import claude_studio

    store: dict = {}
    monkeypatch.setattr(claude_studio, "AsyncSessionFactory", lambda: _FakeSession(store))
    monkeypatch.setattr(claude_studio, "LOG_FLUSH_INTERVAL_S", 0.05)
    recorder = claude_studio._ProgressRecorder(uuid.uuid4())

    await recorder("agent_start", {"id": "a1", "role": "monteur", "description": "Montage it. 1", "prompt": "p"})
    (run_id,) = store
    assert store[run_id]["log"] == ["--- Démarrage : Montage it. 1 ---"]

    running = encode({"type": "tool_call", "callId": "t1", "name": "Bash", "status": "running", "args": {"command": "render"}})
    await recorder("agent_stream", {"id": "a1", "role": "monteur", "lines": [running]})
    await asyncio.sleep(0.15)  # écriture différée : l'outil long est visible sans attendre la suite
    assert store[run_id]["log"][-1] == running

    done = encode({"type": "tool_call", "callId": "t1", "status": "completed", "result": "ok"})
    await recorder("agent_stream", {"id": "a1", "role": "monteur", "lines": [done]})
    await recorder("agent_end", {"id": "a1", "role": "monteur", "is_error": False, "output": "rendu ok"})
    log = store[run_id]["log"]
    assert store[run_id]["status"] == "success"
    assert _ev(log[1])["status"] == "completed" and log[-1] == "--- Fin : succès ---"
    assert recorder._pending == {}

    await recorder("agent_start", {"id": "a2", "role": "critique", "description": "Critique", "prompt": "p"})
    await recorder.close_dangling("stopped", "Arrêté")
    (run2,) = [k for k in store if k != run_id]
    assert store[run2]["status"] == "stopped" and store[run2]["log"][-1] == "--- Interrompu : Arrêté ---"


def test_log_stream_route_sends_history_lines_and_done(monkeypatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from agent.core.database import get_db
    from api.deps import get_current_user
    from api.routes import agents

    tool = {"type": "tool_call", "callId": "t1", "name": "Bash", "status": "running"}
    states = iter([
        {"lines": ["--- Démarrage ---"], "running": True},  # contrôle d'accès de la route
        {"lines": ["--- Démarrage ---"], "running": True},  # history
        {"lines": ["--- Démarrage ---", encode(tool)], "running": True},
        {"lines": ["--- Démarrage ---", encode({**tool, "status": "completed"}), "--- Fin : succès ---"], "running": False},
    ])

    async def fake_read_log(*_args):
        return next(states)

    async def allowed(*_args):
        return None

    class _InjectedSession:
        closed = False

        async def close(self):
            _InjectedSession.closed = True

    class _Session:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc):
            return None

    monkeypatch.setattr(agents, "_read_log", fake_read_log)
    monkeypatch.setattr(agents, "get_user_project", allowed)
    monkeypatch.setattr(agents, "AsyncSessionFactory", _Session)
    monkeypatch.setattr(agents, "LOG_POLL_INTERVAL_S", 0)
    app = FastAPI()
    app.include_router(agents.router)
    app.dependency_overrides[get_db] = _InjectedSession
    app.dependency_overrides[get_current_user] = lambda: object()

    url = f"/api/v1/agents/runs/{uuid.uuid4()}/{uuid.uuid4()}/log/stream"
    with TestClient(app).stream("GET", url) as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"
        body = "".join(response.iter_text())
    events = [
        (block.split("\n")[0].removeprefix("event: "), json.loads(block.split("\n")[1].removeprefix("data: ")))
        for block in body.strip().split("\n\n")
    ]
    assert [kind for kind, _ in events] == ["history", "line", "line", "line", "done"]
    assert events[0][1] == {"lines": ["--- Démarrage ---"], "running": True}
    assert _ev(events[2][1]["line"])["status"] == "completed"  # ligne modifiée renvoyée, le client la re-coalesce
    assert events[3][1]["line"] == "--- Fin : succès ---"
    assert _InjectedSession.closed  # connexion du pool rendue avant le flux, pas après


class _SlowFlushSession(_FakeSession):
    """Écriture de trace seule (flush différé) lente à valider ; écriture finale (avec statut) immédiate."""

    writes: list[str] = []

    async def execute(self, stmt) -> None:
        self._stmt = stmt

    async def commit(self) -> None:
        stmt = getattr(self, "_stmt", None)
        if stmt is None:  # création de l'AgentRun (add), rien à mettre à jour
            return
        values = {col.key: val.value for col, val in stmt._values.items()}
        if "status" not in values:
            await asyncio.sleep(0.2)
        self.writes.append("final" if "status" in values else "flush")
        self.store[stmt.whereclause.right.value].update(values)


@pytest.mark.asyncio
async def test_final_log_waits_for_in_flight_flush(monkeypatch) -> None:
    from agent.core import claude_studio

    store: dict = {}
    _SlowFlushSession.writes = []
    monkeypatch.setattr(claude_studio, "AsyncSessionFactory", lambda: _SlowFlushSession(store))
    monkeypatch.setattr(claude_studio, "LOG_FLUSH_INTERVAL_S", 0)
    recorder = claude_studio._ProgressRecorder(uuid.uuid4())
    await recorder("agent_start", {"id": "a1", "role": "monteur", "description": "Montage", "prompt": "p"})
    (run_id,) = store

    await recorder("agent_stream", {"id": "a1", "role": "monteur", "lines": [encode({"type": "task", "tool_uses": 1})]})
    await asyncio.sleep(0.05)  # le flush est en train d'écrire
    await recorder("agent_end", {"id": "a1", "role": "monteur", "is_error": False, "output": "ok"})

    assert _SlowFlushSession.writes == ["flush", "final"]  # écriture en cours attendue, pas écrasée après coup
    assert store[run_id]["log"][-1] == "--- Fin : succès ---" and store[run_id]["status"] == "success"


@pytest.mark.asyncio
async def test_subagent_stopped_by_usage_limit_is_interrupted(monkeypatch) -> None:
    from agent.core import claude_studio

    store: dict = {}
    monkeypatch.setattr(claude_studio, "AsyncSessionFactory", lambda: _FakeSession(store))
    recorder = claude_studio._ProgressRecorder(uuid.uuid4())
    await recorder("agent_start", {"id": "a1", "role": "monteur", "description": "Montage", "prompt": "p"})
    (run_id,) = store
    await recorder("agent_end", {"id": "a1", "role": "monteur", "is_error": True,
                                 "output": "Agent terminated early due to an API error: You've hit your session limit"})
    # Échec tant que la session n'est pas mise en pause (clé API, ou session qui finit quand même).
    assert store[run_id]["status"] == "failed" and recorder.limit_failures == [run_id]
    await recorder.mark_limit_interrupted()  # appelé par le runner au moment de la pause
    assert store[run_id]["status"] == "interrupted" and store[run_id]["error"] == "Limite d'usage Claude atteinte"
    assert recorder.limit_failures == []
