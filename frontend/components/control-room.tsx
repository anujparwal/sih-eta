"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { age, severity, signed, statusAt, title } from "@/lib/format";
import {
  useClock,
  useFleetStreams,
  usePolling,
  useTrainStream,
} from "@/lib/live";
import type { Fleet, Network, Status } from "@/lib/types";
import {
  Badge,
  Empty,
  ErrorNotice,
  FeedStatus,
  Loading,
  ViewHeader,
} from "./common";
import { ActiveEvents, Explanation, JourneyTimeline } from "./journey";
import { JourneyHistory } from "./history";
import { RouteMap } from "./route-map";
import { ViewSkeleton } from "./view-skeleton";

type Sort = "number" | "delay" | "trend";
function Detail({
  number,
  network,
  close,
}: {
  number: string;
  network: Network;
  close: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const feed = useTrainStream(number);
  const now = useClock();
  const route = network.routes.find((r) => r.train_number === number)!;
  useEffect(() => {
    const element = dialog.current;
    const opener = document.activeElement;
    element?.showModal();
    return () => {
      element?.close();
      // React removes the dialog before passive cleanup; native restoration can
      // no longer find its opener, so preserve keyboard focus explicitly.
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, []);
  return (
    <dialog
      ref={dialog}
      className="train-dialog"
      aria-labelledby="detail-title"
      onCancel={(e) => {
        e.preventDefault();
        close();
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div className="detail-inner">
        <header className="detail-header">
          <div>
            <span className="train-number">TRAIN {number}</span>
            <h2 id="detail-title">{title(route.train_name)}</h2>
          </div>
          <button
            aria-label="Close train detail"
            className="close-button"
            onClick={close}
          >
            ×
          </button>
        </header>
        <FeedStatus feed={feed} now={now} />
        {feed.error && <ErrorNotice message={feed.error} />}
        {feed.data ? (
          <JourneyTimeline route={route} network={network} eta={feed.data} />
        ) : feed.error ? (
          <Empty
            title="Arrival data unavailable"
            text="The feed is reconnecting. Journey estimates will appear when data is available."
          />
        ) : (
          <Loading label="Loading journey" />
        )}
        {feed.data && (
          <>
            <ActiveEvents eta={feed.data} />
            <section className="panel detail-explanation">
              <Explanation eta={feed.data} />
            </section>
            {feed.data.journey_id && (
              <JourneyHistory
                key={feed.data.journey_id}
                number={number}
                journey={feed.data.journey_id}
              />
            )}
          </>
        )}
      </div>
    </dialog>
  );
}
export function ControlRoom() {
  const network = usePolling<Network>("/network", 0);
  const fleet = usePolling<Fleet>("/control/fleet-status", 5000);
  const feeds = useFleetStreams(
    network.data?.routes.map((r) => r.train_number) || [],
  );
  const now = useClock();
  const [selected, setSelected] = useState<string | null>(null);
  const [sort, setSort] = useState<{ key: Sort; direction: number }>({
    key: "delay",
    direction: -1,
  });
  const [filter, setFilter] = useState("all");
  const select = useCallback((number: string) => setSelected(number), []);
  const rows = (fleet.data?.trains || []).map((train) => {
    const feed = feeds[train.train_number];
    const newer =
      feed?.data &&
      Date.parse(feed.data.generated_at) >=
        Date.parse(fleet.data!.generated_at);
    const position = newer ? feed.data!.position : train.latest_position;
    const status = statusAt(
      newer ? feed.data!.status : train.status,
      position?.timestamp,
      now,
    );
    return {
      ...train,
      position,
      status,
      trend:
        feed?.data?.position_id === position?.id &&
        feed?.data?.journey_id === position?.journey_id
          ? (feed?.trend ?? null)
          : null,
    };
  });
  const active = rows.filter((r) => r.status === "active");
  const count = (level: string) =>
    active.filter((r) => severity(r.position?.delay_minutes ?? null) === level)
      .length;
  const shown = rows
    .filter(
      (r) =>
        filter === "all" ||
        (filter === "stale"
          ? r.status === "stale"
          : r.status === "active" &&
            severity(r.position?.delay_minutes ?? null) === filter),
    )
    .sort((a, b) => {
      const left =
        sort.key === "number"
          ? a.train_number
          : sort.key === "delay"
            ? a.position?.delay_minutes
            : a.trend;
      const right =
        sort.key === "number"
          ? b.train_number
          : sort.key === "delay"
            ? b.position?.delay_minutes
            : b.trend;
      if (left == null) return right == null ? 0 : 1;
      if (right == null) return -1;
      return (
        (typeof left === "string"
          ? left.localeCompare(String(right))
          : left - Number(right)) * sort.direction
      );
    });
  function changeSort(key: Sort) {
    setSort((s) => ({
      key,
      direction: s.key === key ? -s.direction : key === "number" ? 1 : -1,
    }));
  }
  const signals = Object.values(feeds).filter(
    (f) => f.connection === "live",
  ).length;
  const predictionErrors = Object.entries(feeds)
    .filter(([, feed]) => feed.error)
    .map(([number]) => number);
  const stats = [
    {
      label: "Active trains",
      value: active.length,
      detail: `${rows.length || 6} in the demo network`,
      color: "teal",
    },
    {
      label: "On time",
      value: count("good"),
      detail: "No observed delay",
      color: "good",
    },
    {
      label: "Minor delays",
      value: count("warn"),
      detail: "Under 15 minutes",
      color: "warn",
    },
    {
      label: "Major delays",
      value: count("bad"),
      detail: "15 minutes or more",
      color: "bad",
    },
  ];
  if (
    (!fleet.data && !fleet.error && !network.error) ||
    (!network.data && !network.error && !fleet.error)
  )
    return <ViewSkeleton kind="control" />;
  return (
    <>
      <ViewHeader
        eyebrow="THE OPERATIONS VIEW"
        title="The whole network, in focus."
        subtitle="Follow fleet conditions and open any train for the complete journey."
        right={
          <div className="feed-status">
            <span className={`status-dot ${signals ? "online" : ""}`} />
            {signals}/6 live streams{" "}
            <span className="muted">· {age(fleet.received, now)}</span>
          </div>
        }
      />
      {network.error && (
        <ErrorNotice message={network.error} retry={network.retry} />
      )}
      {fleet.error && <ErrorNotice message={fleet.error} retry={fleet.retry} />}
      {!!predictionErrors.length && (
        <ErrorNotice
          message={`Prediction updates unavailable for ${predictionErrors.join(", ")}. Reconnecting automatically; observed positions remain visible where available.`}
        />
      )}
      <div className="stats-grid">
        {stats.map((stat) => (
          <section className={`stat-card ${stat.color}`} key={stat.label}>
            <span>{stat.label}</span>
            <strong>
              {fleet.data ? String(stat.value).padStart(2, "0") : "—"}
            </strong>
            <small>{stat.detail}</small>
          </section>
        ))}
      </div>
      <div className="control-map-grid">
        <section className="panel map-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">NETWORK OVERVIEW</p>
              <h2>Fleet positions</h2>
            </div>
            <span className="muted small">Select a marker to inspect</span>
          </div>
          {network.data ? (
            <RouteMap
              network={network.data}
              trains={rows.flatMap((r) =>
                r.position
                  ? [
                      {
                        number: r.train_number,
                        name: r.train_name,
                        position: r.position,
                        status: r.status,
                      },
                    ]
                  : [],
              )}
              onSelect={select}
            />
          ) : network.error ? (
            <Empty
              title="Map unavailable"
              text="The network could not be loaded. Use Try again above to reconnect."
            />
          ) : (
            <Loading label="Loading fleet map" />
          )}
        </section>
        <section className="network-health">
          <p className="eyebrow">SIGNAL & COVERAGE</p>
          <h2>
            Know what’s <br />
            behind the view.
          </h2>
          <dl>
            <div>
              <dt>Fresh observations</dt>
              <dd>{fleet.data ? `${active.length} / ${rows.length}` : "—"}</dd>
            </div>
            <div>
              <dt>Stale signals</dt>
              <dd>
                {fleet.data
                  ? rows.filter((r) => r.status === "stale").length
                  : "—"}
              </dd>
            </div>
            <div>
              <dt>Completed journeys</dt>
              <dd>
                {fleet.data
                  ? rows.filter((r) => r.status === "completed").length
                  : "—"}
              </dd>
            </div>
            <div>
              <dt>Awaiting telemetry</dt>
              <dd>
                {fleet.data
                  ? rows.filter((r) => r.status === "no_data").length
                  : "—"}
              </dd>
            </div>
          </dl>
          <p>
            Fleet counts describe observed delays. ML trends compare successive
            predictions for the same next station and journey.
          </p>
          <div className="map-legend">
            <span>
              <i className="good" /> On time
            </span>
            <span>
              <i className="warn" /> Minor
            </span>
            <span>
              <i className="bad" /> Major
            </span>
            <span>
              <i className="neutral" /> Inactive / stale
            </span>
          </div>
        </section>
      </div>
      <section className="panel fleet-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">SIX TRAINS, ONE VIEW</p>
            <h2>Fleet activity</h2>
          </div>
          <span className="muted small">Observed state refreshes every 5s</span>
        </div>
        <div className="filter-tabs" aria-label="Filter fleet">
          {[
            ["all", "All trains"],
            ["good", "On time"],
            ["warn", "Minor delays"],
            ["bad", "Major delays"],
            ["stale", "Stale"],
          ].map(([key, label]) => (
            <button
              key={key}
              aria-pressed={filter === key}
              className={filter === key ? "selected" : ""}
              onClick={() => setFilter(key)}
            >
              {label}
            </button>
          ))}
        </div>
        {!fleet.data && !fleet.error && <Loading label="Loading fleet" />}
        {fleet.data && !shown.length && (
          <Empty
            title="No trains in this group"
            text="Try another filter to see the rest of the network."
          />
        )}
        {!!shown.length && (
          <div className="table-scroll">
            <table className="fleet-table">
              <caption className="sr-only">Six-train fleet activity</caption>
              <thead>
                <tr>
                  {[
                    ["number", "Train / Service"],
                    ["delay", "Current delay"],
                  ].map(([key, label]) => (
                    <th
                      key={key}
                      aria-sort={
                        sort.key === key
                          ? sort.direction === 1
                            ? "ascending"
                            : "descending"
                          : "none"
                      }
                    >
                      <button onClick={() => changeSort(key as Sort)}>
                        {label} <span aria-hidden="true">↕</span>
                      </button>
                    </th>
                  ))}
                  <th>Current section</th>
                  <th
                    aria-sort={
                      sort.key === "trend"
                        ? sort.direction === 1
                          ? "ascending"
                          : "descending"
                        : "none"
                    }
                  >
                    <button onClick={() => changeSort("trend")}>
                      ML delay trend <span aria-hidden="true">↕</span>
                    </button>
                  </th>
                  <th>Observed</th>
                  <th>
                    <span className="sr-only">Details</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.train_number}>
                    <td>
                      <span className="train-number">{r.train_number}</span>
                      <strong>{title(r.train_name)}</strong>
                    </td>
                    <td data-label="Current delay">
                      <Badge
                        delay={r.position?.delay_minutes ?? null}
                        status={r.status as Status}
                      />
                    </td>
                    <td data-label="Current section">
                      <span className="section-code">
                        {r.position
                          ? `${r.position.last_station} → ${r.position.next_station || "End"}`
                          : `${r.origin} → ${r.destination}`}
                      </span>
                      {!r.position && (
                        <span className="cell-sub muted">
                          Scheduled route only
                        </span>
                      )}
                    </td>
                    <td data-label="ML delay trend">
                      {r.trend !== null && r.status === "active" ? (
                        <span
                          className={`trend ${r.trend > 0 ? "text-amber" : "text-teal"}`}
                        >
                          {r.trend > 0 ? "↗" : r.trend < 0 ? "↘" : "→"}{" "}
                          {signed(r.trend)} min
                        </span>
                      ) : (
                        <span className="muted small">Awaiting comparison</span>
                      )}
                    </td>
                    <td className="small muted" data-label="Observed">
                      {age(r.position?.timestamp, now)}
                    </td>
                    <td>
                      <button
                        className="inspect-button"
                        aria-label={`View train ${r.train_number}`}
                        onClick={() => select(r.train_number)}
                      >
                        View <span aria-hidden="true">↗</span>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {selected && network.data && (
        <Detail
          key={selected}
          number={selected}
          network={network.data}
          close={() => setSelected(null)}
        />
      )}
    </>
  );
}
