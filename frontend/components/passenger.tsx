"use client";

import { useState } from "react";
import Link from "next/link";
import { age, date, statusAt, time, title, until } from "@/lib/format";
import { useClock, usePolling, useTrainStream } from "@/lib/live";
import type { Network } from "@/lib/types";
import {
  Badge,
  Empty,
  ErrorNotice,
  FeedStatus,
  Loading,
  ViewHeader,
} from "./common";
import { Explanation, JourneyTimeline } from "./journey";
import { RouteMap } from "./route-map";
import { Icon } from "./shell";

export function Passenger({ initialTrain }: { initialTrain: string }) {
  const network = usePolling<Network>("/network", 0);
  const [selected, setSelected] = useState(initialTrain);
  const [search, setSearch] = useState("");
  const feed = useTrainStream(selected);
  const now = useClock();
  const route = network.data?.routes.find((r) => r.train_number === selected);
  const data = feed.data;
  const position = data?.position;
  const status = statusAt(data?.status || "no_data", data?.as_of, now);
  const next = data?.stations[0];
  const progress =
    route && position
      ? Math.min(
          100,
          Math.max(0, (position.distance_km / route.total_distance_km) * 100),
        )
      : 0;
  function select(number: string) {
    setSelected(number);
    window.history.replaceState(null, "", `/?train=${number}`);
  }
  const matches = network.data?.routes.filter((r) =>
    `${r.train_number} ${r.train_name}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  return (
    <>
      <ViewHeader
        eyebrow="THE PASSENGER VIEW"
        title="A clearer picture of your journey."
        subtitle="Follow your train, compare arrival estimates, and see what’s changing."
        right={<FeedStatus feed={feed} now={now} />}
      />
      {network.error && (
        <ErrorNotice message={network.error} retry={network.retry} />
      )}
      {feed.error && <ErrorNotice message={feed.error} />}
      {status === "stale" && (
        <div className="notice warning" role="status">
          This train’s signal is stale. Estimates use the last observation,{" "}
          {age(data?.as_of, now)}.
        </div>
      )}
      <div className="passenger-grid">
        <aside className="journey-sidebar">
          <section className="panel train-picker">
            <p className="eyebrow">FIND YOUR TRAIN</p>
            <label htmlFor="train-search">Train name or number</label>
            <div className="search-field">
              <Icon name="train" />
              <input
                id="train-search"
                type="search"
                placeholder="e.g. 12301 or Rajdhani"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <div className="train-options" aria-label="Available trains">
              {matches?.map((r) => (
                <button
                  key={r.train_number}
                  className={`train-option ${selected === r.train_number ? "selected" : ""}`}
                  aria-pressed={selected === r.train_number}
                  onClick={() => select(r.train_number)}
                >
                  <span className="train-option-line">
                    <span className="train-number">{r.train_number}</span>
                    <span className="selection-mark">
                      {selected === r.train_number ? "✓" : "↗"}
                    </span>
                  </span>
                  <strong>{title(r.train_name)}</strong>
                  <span>
                    {r.stops[0].station_code} <span aria-hidden="true">→</span>{" "}
                    {r.stops.at(-1)?.station_code}
                  </span>
                </button>
              ))}
            </div>
            {matches?.length === 0 && (
              <p className="muted small">
                No matching train in this six-train demo.
              </p>
            )}
            {!network.data && !network.error && (
              <Loading label="Loading the network" />
            )}
          </section>
          <div className="data-note">
            <span className="eyebrow">A NOTE ON THE DATA</span>
            <p>Real historical routes. Simulated train movements.</p>
            <small>
              Estimates demonstrate the system and aren’t travel advice or a
              live railway service.
            </small>
          </div>
        </aside>
        <div className="journey-main">
          {!data && !feed.error && <Loading label="Connecting to your train" />}
          {route && (
            <section className="panel journey-overview">
              <div className="overview-top">
                <div>
                  <span className="train-number">
                    TRAIN {route.train_number}
                  </span>
                  <h2>{title(route.train_name)}</h2>
                </div>
                <Badge
                  delay={data?.current_delay_minutes ?? null}
                  status={status}
                />
              </div>
              <div className="endpoints">
                <div>
                  <span className="station-code">
                    {route.stops[0].station_code}
                  </span>
                  <span>
                    {title(
                      network.data!.stations.find(
                        (s) => s.code === route.stops[0].station_code,
                      )?.name || "Origin",
                    )}
                  </span>
                </div>
                <Icon name="arrow" size={28} />
                <div>
                  <span className="station-code">
                    {route.stops.at(-1)?.station_code}
                  </span>
                  <span>
                    {title(
                      network.data!.stations.find(
                        (s) => s.code === route.stops.at(-1)?.station_code,
                      )?.name || "Destination",
                    )}
                  </span>
                </div>
              </div>
              <div
                className="progress-track"
                role="progressbar"
                aria-label="Journey distance covered"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(progress)}
              >
                <span style={{ width: `${progress}%` }} />
              </div>
              <div className="progress-labels">
                <span>
                  {position
                    ? `${Math.round(position.distance_km)} of ${Math.round(route.total_distance_km)} km`
                    : "Awaiting first observation"}
                </span>
                <span>
                  {position
                    ? `${Math.round(progress)}% complete`
                    : "Not started"}
                </span>
              </div>
            </section>
          )}
          <div className="map-estimate-grid">
            <section className="panel map-panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">ON THE NETWORK</p>
                  <h2>Journey map</h2>
                </div>
                <span className="small muted">
                  {position
                    ? `${Math.round(position.current_speed_kmh)} km/h`
                    : "No position yet"}
                </span>
              </div>
              {network.data && route ? (
                <RouteMap
                  network={network.data}
                  routeNumber={selected}
                  trains={
                    position
                      ? [
                          {
                            number: selected,
                            name: route.train_name,
                            position,
                            status,
                          },
                        ]
                      : []
                  }
                />
              ) : (
                <Loading label="Loading route" />
              )}
            </section>
            <section className="panel next-arrival">
              <p className="eyebrow">
                {status === "completed" ? "JOURNEY COMPLETE" : "NEXT ARRIVAL"}
              </p>
              {next ? (
                <>
                  <Link
                    className="next-station-name"
                    href={`/station/${next.station_code}`}
                  >
                    {title(next.station_name)} <span>{next.station_code}</span>
                  </Link>
                  <div className="hero-time">
                    {time(next.eta)}
                    <span>IST</span>
                  </div>
                  <div className="arrival-date">
                    {date(next.eta)}{" "}
                    <span>
                      ·{" "}
                      {status === "stale"
                        ? "Last known estimate"
                        : until(next.eta, now)}
                    </span>
                  </div>
                  <div className="estimate-comparison">
                    <span className={`estimate-tag ${next.ml_eta ? "ml" : ""}`}>
                      {next.ml_eta ? "ML estimate" : "Carryover estimate"}
                    </span>
                    {next.ml_eta && (
                      <span className="muted">
                        Baseline <del>{time(next.baseline_eta)}</del>
                      </span>
                    )}
                  </div>
                  <p className="small muted">
                    {Math.round(next.distance_remaining_km)} km to this station
                  </p>
                  <Explanation eta={data!} />
                </>
              ) : (
                <Empty
                  title={
                    status === "completed"
                      ? "You’ve reached the destination"
                      : "Waiting for departure"
                  }
                  text={
                    status === "completed"
                      ? "No upcoming stations remain in this journey."
                      : "An arrival estimate will appear after the simulator sends its first observation."
                  }
                />
              )}
            </section>
          </div>
          {route && network.data && (
            <JourneyTimeline route={route} network={network.data} eta={data} />
          )}
        </div>
      </div>
    </>
  );
}
