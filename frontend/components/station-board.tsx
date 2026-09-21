"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { age, date, statusAt, time, title } from "@/lib/format";
import { useClock, usePolling } from "@/lib/live";
import type { Arrivals, Network } from "@/lib/types";
import { Badge, Empty, ErrorNotice, Loading, ViewHeader } from "./common";
import { Icon } from "./shell";
import { ViewSkeleton } from "./view-skeleton";

export function StationBoard({ code }: { code: string }) {
  const router = useRouter();
  const network = usePolling<Network>("/network", 0);
  const board = usePolling<Arrivals>(`/stations/${code}/arrivals`, 10000);
  const now = useClock();
  const station = network.data?.stations.find((s) => s.code === code);
  if (!board.data && !board.error && !network.error)
    return <ViewSkeleton kind="station" />;
  return (
    <>
      <ViewHeader
        eyebrow="THE STATION VIEW"
        title="Every arrival. At a glance."
        subtitle="A shared view of approaching trains, refreshed every 10 seconds."
        right={
          <div className="station-select">
            <label htmlFor="station-select">Display station</label>
            <select
              id="station-select"
              value={code}
              onChange={(e) => router.push(`/station/${e.target.value}`)}
            >
              {!station && <option value={code}>{code}</option>}
              {network.data?.stations.map((s) => (
                <option key={s.code} value={s.code}>
                  {s.code} · {title(s.name)}
                </option>
              ))}
            </select>
          </div>
        }
      />
      {network.error && (
        <ErrorNotice message={network.error} retry={network.retry} />
      )}
      {board.error && <ErrorNotice message={board.error} retry={board.retry} />}
      <section className="departure-board">
        <header className="board-header">
          <div className="board-station">
            <span className="board-icon">
              <Icon name="station" size={32} />
            </span>
            <div>
              <p>ARRIVALS / आगमन</p>
              <h2>
                {station ? title(station.name) : code} <span>{code}</span>
              </h2>
            </div>
          </div>
          <div className="board-clock">
            <strong>{time(now)}</strong>
            <span>{date(now)} · IST</span>
          </div>
        </header>
        <div className="board-meta">
          <span>
            <span
              className={`status-dot ${board.data && !board.error ? "online" : ""}`}
            />
            {board.error ? "Connection interrupted" : "Automatic refresh"}
          </span>
          <span aria-live="polite">
            Last updated {age(board.received, now)}
          </span>
        </div>
        {!board.data && !board.error && <Loading label="Loading arrivals" />}
        {board.data && board.data.arrivals.length === 0 && (
          <Empty
            title="No active arrivals"
            text="No train with fresh telemetry is currently approaching this station. Completed journeys and stale signals are excluded."
          />
        )}
        {!!board.data?.arrivals.length && (
          <div className="table-scroll">
            <table className="arrivals-table">
              <caption className="sr-only">
                Upcoming arrivals at {station?.name || code}, all times in IST
              </caption>
              <thead>
                <tr>
                  <th scope="col">Train / Service</th>
                  <th scope="col">Scheduled</th>
                  <th scope="col">Expected</th>
                  <th scope="col">Platform</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {board.data.arrivals.map((arrival) => {
                  const status = statusAt(arrival.status, arrival.as_of, now);
                  const delay = Math.max(
                    0,
                    (Date.parse(arrival.eta) -
                      Date.parse(arrival.scheduled_arrival)) /
                      60000,
                  );
                  return (
                    <tr key={`${arrival.train_number}-${arrival.journey_id}`}>
                      <td>
                        <Link href={`/?train=${arrival.train_number}`}>
                          <span className="train-number">
                            {arrival.train_number}
                          </span>
                          <strong>{title(arrival.train_name)}</strong>
                        </Link>
                      </td>
                      <td>
                        <strong className="board-time">
                          {time(arrival.scheduled_arrival)}
                        </strong>
                        <span className="cell-sub">
                          {date(arrival.scheduled_arrival)}
                        </span>
                      </td>
                      <td>
                        <strong className="board-time expected">
                          {time(arrival.eta)}
                        </strong>
                        <span className="cell-sub">
                          {date(arrival.eta)} ·{" "}
                          {arrival.ml_eta ? "ML estimate" : "Carryover"}
                        </span>
                        {arrival.ml_eta && (
                          <span className="cell-sub">
                            Baseline <del>{time(arrival.baseline_eta)}</del>
                          </span>
                        )}
                      </td>
                      <td>
                        <span
                          className="platform"
                          aria-label="Platform unavailable"
                        >
                          —
                        </span>
                      </td>
                      <td>
                        <Badge delay={delay} status={status} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <footer className="board-footer">
          <span>Platform assignments are not provided.</span>
          <span>SYNTHETIC TELEMETRY · NOT A LIVE RAILWAY BOARD</span>
        </footer>
      </section>
      <div className="board-notes">
        <div>
          <h3>One time zone. No guesswork.</h3>
          <p>
            All times are in Indian Standard Time. Dates stay visible for
            overnight journeys.
          </p>
        </div>
        <div>
          <h3>An honest comparison.</h3>
          <p>
            ML is available for a train’s next station. Later stops use the
            current-delay carryover estimate.
          </p>
        </div>
        <div>
          <h3>Freshness comes first.</h3>
          <p>
            Signals older than 30 seconds are marked stale and removed on the
            next successful refresh.
          </p>
        </div>
      </div>
    </>
  );
}
