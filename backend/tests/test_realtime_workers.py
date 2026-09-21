"""Two independent API processes prove Redis delivery and shared rate limiting."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from sqlalchemy import delete
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from websockets.asyncio.client import connect

from app import realtime
from app.models import Event, LivePosition
from simulator.engine import Fleet


def test_cross_process_updates_under_one_second_and_shared_budget(
    db_engine, redis_client, dataset, tmp_path
):
    database = make_url(os.environ["TEST_DATABASE_URL"])
    env = os.environ | {
        "POSTGRES_HOST": database.host,
        "POSTGRES_PORT": str(database.port or 5432),
        "POSTGRES_DB": database.database,
        "POSTGRES_USER": database.username,
        "POSTGRES_PASSWORD": database.password,
        "REDIS_URL": os.environ["TEST_REDIS_URL"],
        "REDIS_KEY_PREFIX": realtime.KEY_PREFIX,
        "INGEST_RATE_LIMIT_PER_MINUTE": "12",
    }
    processes, ports, logs = [], [], []
    train = Fleet(dataset, datetime.now(UTC), seed=42).trains[0]
    initial = train.snapshot()
    # Keep the bound socket open until the child inherits it: no free-port race.
    script = (
        "import socket,sys,uvicorn; "
        "sock=socket.socket(fileno=int(sys.argv[1])); "
        "uvicorn.Server(uvicorn.Config('app.main:app',proxy_headers=False,"
        "log_level='warning')).run(sockets=[sock])"
    )

    async def scenario():
        async with httpx.AsyncClient(timeout=3) as client:
            for port in ports:
                for _ in range(100):
                    try:
                        if (await client.get(f"http://127.0.0.1:{port}/health")).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(0.05)
                else:
                    raise AssertionError("API worker did not start")
            # POSTs go ONLY to process 1; the subscribed WebSocket lives on process 2.
            async with connect(f"ws://127.0.0.1:{ports[1]}/ws/trains/12301") as ws:
                message = json.loads(await asyncio.wait_for(ws.recv(), 3))
                assert message["data"]["status"] == "no_data"
                timings = []
                for _ in range(5):
                    instant = datetime.now(UTC)
                    sample = initial | {
                        "id": str(uuid4()),
                        "timestamp": instant.isoformat(),
                        "delay_minutes": (instant - train.started_at).total_seconds() / 60,
                    }
                    started = time.perf_counter()
                    response = await client.post(
                        f"http://127.0.0.1:{ports[0]}/ingest/position", json=sample
                    )
                    assert response.status_code == 201, response.text
                    message = json.loads(await asyncio.wait_for(ws.recv(), 1))
                    latency = time.perf_counter() - started
                    assert message["data"]["position_id"] == sample["id"]
                    assert latency < 1, f"Cross-process update took {latency:.3f}s"
                    timings.append(latency)
                    fleet = await client.get(f"http://127.0.0.1:{ports[1]}/control/fleet-status")
                    assert fleet.status_code == 200
                    assert fleet.json()["trains"][0]["latest_position"]["id"] == sample["id"]
                # A retry republishes for recovery, but does not repeat an unchanged ETA.
                response = await client.post(
                    f"http://127.0.0.1:{ports[0]}/ingest/position", json=sample
                )
                assert response.status_code == 200
                try:
                    await asyncio.wait_for(ws.recv(), 0.1)
                except TimeoutError:
                    pass
                else:
                    raise AssertionError("Retry emitted duplicate ETA")
                # An event at the current observation time must push a new snapshot
                # without requiring another position, even across different API workers.
                incident = {
                    "id": str(uuid4()),
                    "journey_id": sample["journey_id"],
                    "train_number": "12301",
                    "timestamp": sample["timestamp"],
                    "event_type": "weather",
                    "severity": 2,
                    "duration_seconds": 120,
                    "description": "Synthetic cross-process event",
                }
                started = time.perf_counter()
                response = await client.post(
                    f"http://127.0.0.1:{ports[0]}/ingest/event", json=incident
                )
                assert response.status_code == 201, response.text
                event_update = json.loads(await asyncio.wait_for(ws.recv(), 1))["data"]
                assert time.perf_counter() - started < 1
                assert event_update["position_id"] == sample["id"]
                assert [e["id"] for e in event_update["active_events"]] == [incident["id"]]
                assert event_update["features"]["active_event_severity_sum"] == 2
                async with connect(f"ws://127.0.0.1:{ports[1]}/ws/trains/12301") as reconnected:
                    state = json.loads(await asyncio.wait_for(reconnected.recv(), 3))
                    assert state["data"]["position_id"] == sample["id"]
                    assert state["data"]["active_events"] == event_update["active_events"]
                # Seven accepted ingests so far; invalid payloads count toward the same
                # peer budget on either process and forwarding headers cannot evade it.
                for index in range(5):
                    response = await client.post(
                        f"http://127.0.0.1:{ports[index % 2]}/ingest/event", json={}
                    )
                    assert response.status_code == 422
                response = await client.post(
                    f"http://127.0.0.1:{ports[1]}/ingest/position",
                    json={},
                    headers={"X-Forwarded-For": "8.8.8.8"},
                )
                assert response.status_code == 429
                assert 1 <= int(response.headers["retry-after"]) <= 60
                print(
                    f"Cross-process delivery: {len(timings)} updates; "
                    f"maximum {max(timings) * 1000:.1f} ms"
                )
            for _ in range(100):
                if redis_client.pubsub_numsub(realtime.channel("12301"))[0][1] == 0:
                    break
                await asyncio.sleep(0.02)
            else:
                raise AssertionError("Disconnected sockets leaked Redis subscriptions")

    try:
        for index in range(2):
            log = (tmp_path / f"worker-{index}.log").open("w+")
            logs.append(log)
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                listener.listen()
                ports.append(listener.getsockname()[1])
                processes.append(
                    subprocess.Popen(
                        [sys.executable, "-c", script, str(listener.fileno())],
                        pass_fds=(listener.fileno(),),
                        cwd=Path(__file__).resolve().parents[1],
                        env=env,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                    )
                )
        asyncio.run(scenario())
    except Exception:
        for log in logs:
            log.seek(0)
            print(log.read())
        raise
    finally:
        for process in processes:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for log in logs:
            log.close()
        with Session(db_engine) as session, session.begin():
            session.execute(delete(Event).where(Event.journey_id == UUID(initial["journey_id"])))
            session.execute(
                delete(LivePosition).where(LivePosition.journey_id == UUID(initial["journey_id"]))
            )
