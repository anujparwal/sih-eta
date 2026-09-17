"""Exercise HTTP and real WebSocket transport against a running six-train demo."""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from websockets.asyncio.client import connect


async def verify(api_url: str) -> None:
    async with httpx.AsyncClient(base_url=api_url, timeout=10) as client:
        response = await client.get("/trains?active_only=true")
        response.raise_for_status()
        trains = response.json()["trains"]
        assert len(trains) == 6, "Run immediately after the two-minute simulator smoke check"
        for train in trains:
            number = train["train_number"]
            response = await client.get(f"/trains/{number}/eta")
            response.raise_for_status()
            eta = response.json()
            assert eta["status"] == "active" and eta["timing_basis"] == "provided"
            assert eta["features"] is not None and eta["stations"]
            assert eta["baseline_method"] == "current_delay_carryover"
            for station in eta["stations"]:
                assert station["eta"] == station["baseline_eta"]
                delta = (
                    datetime.fromisoformat(station["baseline_eta"])
                    - datetime.fromisoformat(station["scheduled_arrival"])
                ).total_seconds() / 60
                assert abs(delta - eta["current_delay_minutes"]) < 1e-6
            response = await client.get(f"/trains/{number}/history?limit=1000")
            response.raise_for_status()
            assert len(response.json()["positions"]) >= 20
            code = eta["stations"][0]["station_code"]
            response = await client.get(f"/stations/{code}/arrivals")
            response.raise_for_status()
            match = next(a for a in response.json()["arrivals"] if a["train_number"] == number)
            assert match["baseline_eta"] == eta["stations"][0]["baseline_eta"]
            socket_url = api_url.replace("http://", "ws://", 1).replace("https://", "wss://", 1)
            # Reconnect twice: both connections must receive the current snapshot immediately.
            for _ in range(2):
                async with connect(f"{socket_url}/ws/trains/{number}", open_timeout=5) as socket:
                    message = json.loads(await asyncio.wait_for(socket.recv(), timeout=5))
                    assert message["type"] == "eta_update"
                    assert message["data"]["position_id"] == eta["position_id"]
                    assert message["data"]["stations"] == eta["stations"]
        # Hold one train at its last position, then verify a committed HTTP sample
        # reaches an already-open real socket without reconnecting.
        held = dict(trains[0]["latest_position"])
        number = held["train_number"]
        async with connect(f"{socket_url}/ws/trains/{number}", open_timeout=5) as socket:
            await asyncio.wait_for(socket.recv(), timeout=5)
            observed_at = datetime.now(UTC)
            elapsed = (observed_at - datetime.fromisoformat(held["timestamp"])).total_seconds()
            held.update(
                id=str(uuid4()),
                timestamp=observed_at.isoformat(),
                delay_minutes=held["delay_minutes"] + elapsed / 60,
                current_speed_kmh=0,
            )
            response = await client.post("/ingest/position", json=held)
            response.raise_for_status()
            update = json.loads(await asyncio.wait_for(socket.recv(), timeout=5))
            assert update["data"]["position_id"] == held["id"]
            assert abs(update["data"]["current_delay_minutes"] - held["delay_minutes"]) < 1e-6
        response = await client.get("/control/fleet-status")
        response.raise_for_status()
        assert response.json()["active_trains"] == 6
        print(
            json.dumps(
                {
                    "active_trains": 6,
                    "baseline_comparisons": "passed",
                    "station_boards": "passed",
                    "websocket_connections": 13,
                    "http_to_websocket_update": "passed",
                }
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://backend:8000")
    args = parser.parse_args()
    asyncio.run(verify(args.api_url.rstrip("/")))


if __name__ == "__main__":
    main()
