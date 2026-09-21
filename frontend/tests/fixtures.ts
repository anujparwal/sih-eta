import type { Page, WebSocketRoute } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { Arrivals, Fleet, Network, TrainETA } from "../lib/types";

export const network: Network = JSON.parse(
  readFileSync(resolve(process.cwd(), "../data/rail_network.json"), "utf8"),
);
export const NOW = new Date("2026-09-20T18:25:00Z").getTime();
export const iso = (milliseconds: number) =>
  new Date(milliseconds).toISOString();
export function snapshot(number: string, revision = 0): TrainETA {
  const route = network.routes.find((r) => r.train_number === number)!;
  const index = network.routes.indexOf(route);
  const delay = [0, 3, 25, 9, 17, 0][index];
  const asOf = iso(NOW + revision * 5000);
  const origin = network.stations.find(
    (s) => s.code === route.stops[0].station_code,
  )!;
  return {
    train_number: number,
    generated_at: asOf,
    status: "active",
    journey_id: `journey-${number}`,
    position_id: `${number}-${revision}`,
    as_of: asOf,
    journey_started_at: iso(NOW - 300000),
    current_delay_minutes: delay,
    ml_status: "ready",
    position: {
      id: `${number}-${revision}`,
      journey_id: `journey-${number}`,
      journey_started_at: iso(NOW - 300000),
      train_number: number,
      timestamp: asOf,
      lat: origin.lat + revision * 0.1,
      lon: origin.lon + revision * 0.1,
      distance_km: 2 + revision,
      delay_minutes: delay,
      current_speed_kmh: 60,
      last_station: origin.code,
      next_station: route.stops[1].station_code,
    },
    active_events:
      index === 0
        ? [
            {
              id: "event-test",
              journey_id: `journey-${number}`,
              timestamp: asOf,
              event_type: "weather",
              severity: 2,
              description: "Synthetic weather test event",
              duration_seconds: 120,
            },
          ]
        : [],
    stations: route.stops.slice(1).map((s, i) => {
      const scheduled =
        NOW + (s.arrival_seconds! - route.stops[0].departure_seconds!) * 1000;
      const baseline = scheduled + delay * 60000;
      const predicted = delay + 2 + revision;
      const ml = i === 0 ? scheduled + predicted * 60000 : null;
      return {
        station_code: s.station_code,
        station_name: network.stations.find((st) => st.code === s.station_code)!
          .name,
        sequence: s.sequence,
        distance_remaining_km: s.distance_km - 2,
        scheduled_arrival: iso(scheduled),
        baseline_eta: iso(baseline),
        eta: iso(ml || baseline),
        ml_eta: ml ? iso(ml) : null,
        eta_baseline_minutes: (baseline - NOW) / 60000,
        eta_ml_minutes: ml ? (ml - NOW) / 60000 : null,
        prediction_method: ml
          ? "xgboost_next_station"
          : "current_delay_carryover",
        model_version: ml ? "synthetic-next-station-v1" : null,
        predicted_delay_minutes: ml ? predicted : null,
        explanation: ml
          ? {
              base_value_minutes: 1,
              contributions: [
                {
                  feature: "distance_remaining_next_station_km",
                  value: 5,
                  contribution_minutes: 1 + revision,
                },
              ],
              raw_residual_minutes: 2 + revision,
              current_delay_minutes: delay,
              clipping_adjustment_minutes: 0,
              predicted_delay_minutes: predicted,
            }
          : null,
      };
    }),
  };
}
export function arrivals(code: string): Arrivals {
  return {
    station_code: code,
    generated_at: iso(NOW),
    arrivals: network.routes.flatMap((r) => {
      const eta = snapshot(r.train_number);
      const station = eta.stations.find((s) => s.station_code === code);
      return station
        ? [
            {
              ...station,
              train_number: r.train_number,
              train_name: r.train_name,
              journey_id: eta.journey_id!,
              as_of: eta.as_of!,
              status: eta.status,
            },
          ]
        : [];
    }),
  };
}
export function fleet(): Fleet {
  return {
    generated_at: iso(NOW),
    total_trains: 6,
    active_trains: 6,
    stale_trains: 0,
    completed_trains: 0,
    no_data_trains: 0,
    trains: network.routes.map((r) => ({
      train_number: r.train_number,
      train_name: r.train_name,
      origin: r.stops[0].station_code,
      destination: r.stops.at(-1)!.station_code,
      status: "active",
      latest_position: snapshot(r.train_number).position,
    })),
  };
}
export async function mockDemo(page: Page) {
  await page.clock.install({ time: NOW });
  // CI does not exercise the public OSM tile service or depend on its availability.
  await page.route("https://tile.openstreetmap.org/**", (route) =>
    route.fulfill({
      contentType: "image/png",
      body: Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6oX0AAAAASUVORK5CYII=",
        "base64",
      ),
    }),
  );
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const number = path.match(/trains\/(\d{5})/)?.[1];
    let body: unknown;
    if (path === "/api/network") body = network;
    else if (path === "/api/control/fleet-status") body = fleet();
    else if (number && path.endsWith("/eta")) body = snapshot(number);
    else if (number && path.endsWith("/history"))
      body = {
        train_number: number,
        journey_id: `journey-${number}`,
        positions: [snapshot(number).position],
        next_after: null,
      };
    else if (path.includes("/stations/")) body = arrivals(path.split("/")[3]);
    else
      return route.fulfill({
        status: 404,
        json: { detail: "Unknown test resource" },
      });
    await route.fulfill({ json: body });
  });
  const sockets = new Map<string, WebSocketRoute[]>();
  await page.routeWebSocket(/\/ws\/trains\/\d{5}/, (socket) => {
    const number = socket.url().split("/").at(-1)!;
    sockets.set(number, [...(sockets.get(number) || []), socket]);
    socket.send(JSON.stringify({ type: "eta_update", data: snapshot(number) }));
  });
  return sockets;
}
