"use client";

import { useEffect, useState } from "react";
import { fetchData } from "@/lib/live";
import { date, time } from "@/lib/format";
import type { History } from "@/lib/types";
import { ErrorNotice, Loading } from "./common";

// Keyed by train and journey in the parent, so in-flight pages cannot cross journeys.
export function JourneyHistory({
  number,
  journey,
}: {
  number: string;
  journey: string;
}) {
  const [cursor, setCursor] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<{
    pages: History[];
    loading: boolean;
    error: string | null;
  }>({ pages: [], loading: true, error: null });
  useEffect(() => {
    const controller = new AbortController();
    let closed = false;
    const url = `/trains/${number}/history?journey_id=${journey}&limit=100${cursor ? `&after=${encodeURIComponent(cursor)}` : ""}`;
    const timeout = setTimeout(() => controller.abort(), 10000);
    void fetchData<History>(url, controller.signal)
      .then((page) => {
        if (!closed)
          setState((prev) => ({
            pages: cursor ? [...prev.pages, page] : [page],
            loading: false,
            error: null,
          }));
      })
      .catch(() => {
        if (!closed)
          setState((prev) => ({
            ...prev,
            loading: false,
            error: "Journey history could not be loaded.",
          }));
      })
      .finally(() => clearTimeout(timeout));
    return () => {
      closed = true;
      controller.abort();
      clearTimeout(timeout);
    };
  }, [number, journey, cursor, attempt]);
  const points = state.pages.flatMap((page) => page.positions);
  const next = state.pages.at(-1)?.next_after;
  return (
    <section className="panel history-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">OBSERVED, NOT PREDICTED</p>
          <h2>Recorded history</h2>
        </div>
        <span className="muted small">{points.length} observations loaded</span>
      </div>
      {state.error && (
        <ErrorNotice
          message={state.error}
          retry={() => setAttempt((n) => n + 1)}
        />
      )}
      {state.loading && !points.length && (
        <Loading label="Loading journey history" />
      )}
      <div className="history-scroll">
        <table className="history-table">
          <caption className="sr-only">
            Recorded positions for this journey
          </caption>
          <thead>
            <tr>
              <th>Observed (IST)</th>
              <th>Section</th>
              <th>Distance</th>
              <th>Delay</th>
            </tr>
          </thead>
          <tbody>
            {points.map((p) => (
              <tr key={p.id}>
                <td>
                  {date(p.timestamp)} {time(p.timestamp)}
                </td>
                <td>
                  {p.last_station} → {p.next_station || "End"}
                </td>
                <td>{p.distance_km.toFixed(1)} km</td>
                <td>{p.delay_minutes.toFixed(1)} min</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {next && (
        <button
          className="secondary-button"
          disabled={state.loading}
          onClick={() => {
            setState((s) => ({ ...s, loading: true }));
            if (cursor === next) setAttempt((n) => n + 1);
            else setCursor(next);
          }}
        >
          {state.loading ? "Loading…" : "Load next 100 observations"}
        </button>
      )}
      <p className="muted small">
        Oldest to newest · This journey only. Reopen the detail to refresh
        recorded history.
      </p>
    </section>
  );
}
