"""Drive the ASGI WebSocket protocol directly, including idle disconnect cleanup."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError

from app import read_api
from app.main import app
from app.read_schemas import TrainETA


@asynccontextmanager
async def socket(path="/ws/trains/12301"):
    incoming, outgoing = asyncio.Queue(), asyncio.Queue()
    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0"},
        "scheme": "ws",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
        "subprotocols": [],
        "state": {},
    }
    task = asyncio.create_task(app(scope, incoming.get, outgoing.put))
    await incoming.put({"type": "websocket.connect"})
    try:
        yield incoming, outgoing, task
    finally:
        await incoming.put({"type": "websocket.disconnect", "code": 1000})
        await asyncio.wait_for(task, timeout=3)


async def receive(queue):
    return await asyncio.wait_for(queue.get(), timeout=3)


def snapshot():
    return TrainETA(
        generated_at=datetime.now(UTC),
        train_number="12301",
        status="no_data",
        journey_id=None,
        position_id=None,
        as_of=None,
        journey_started_at=None,
        timing_basis="unavailable",
        current_delay_minutes=None,
        features=None,
        stations=[],
    )


def test_socket_initial_update_no_duplicates_changed_state_and_reconnect(monkeypatch):
    state = [snapshot()]
    monkeypatch.setattr(read_api, "socket_snapshot", lambda _: state[0])

    async def scenario():
        async with socket() as (incoming, outgoing, _):
            assert (await receive(outgoing))["type"] == "websocket.accept"
            initial = json.loads((await receive(outgoing))["text"])
            assert initial["type"] == "eta_update" and initial["data"]["status"] == "no_data"
            # A changed generated_at alone must not create an update.
            state[0] = state[0].model_copy(update={"generated_at": datetime.now(UTC)})
            await incoming.put({"type": "websocket.receive", "bytes": b"ignored"})
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(outgoing.get(), timeout=1.1)
            state[0] = state[0].model_copy(update={"position_id": uuid4(), "status": "stale"})
            update = json.loads((await receive(outgoing))["text"])
            assert update["data"]["status"] == "stale"
        async with socket() as (_, outgoing, _):
            assert (await receive(outgoing))["type"] == "websocket.accept"
            update = json.loads((await receive(outgoing))["text"])
            assert update["data"]["position_id"] == str(state[0].position_id)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "error,code,close",
    [
        (HTTPException(404, "Train is not in the seeded network"), 404, 1008),
        (OperationalError("private SQL", {}, Exception("secret-password")), 503, 1011),
    ],
)
def test_socket_errors_are_sanitized_and_closed(monkeypatch, error, code, close):
    def fail(_):
        raise error

    monkeypatch.setattr(read_api, "socket_snapshot", fail)

    async def scenario():
        async with socket() as (_, outgoing, _):
            assert (await receive(outgoing))["type"] == "websocket.accept"
            response = await receive(outgoing)
            assert "secret-password" not in response["text"]
            assert json.loads(response["text"])["code"] == code
            assert (await receive(outgoing))["code"] == close

    asyncio.run(scenario())


def test_socket_rejects_malformed_train_number():
    async def scenario():
        async with socket("/ws/trains/abc") as (_, outgoing, _):
            message = await receive(outgoing)
            assert message["type"] == "websocket.close" and message["code"] == 1008

    asyncio.run(scenario())
