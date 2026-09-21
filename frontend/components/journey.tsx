"use client";

import Link from "next/link";
import { date, signed, statusAt, time, title } from "@/lib/format";
import type { Network, Route, TrainETA } from "@/lib/types";
import { useClock } from "@/lib/live";
import { Badge, Empty } from "./common";

const featureLabels: Record<string, string> = {
  minutes_since_last_station: "Time since last station",
  distance_remaining_next_station_km: "Distance to next station",
  current_delay_minutes: "Current delay",
  historical_day_of_week: "Day of the week",
  historical_hour_of_day: "Time of day",
  active_event_count: "Active disruptions",
  active_event_severity_sum: "Combined event severity",
  active_event_max_severity: "Highest event severity",
  congestion_index: "Nearby trains",
};
export function Explanation({ eta }: { eta: TrainETA }) {
  const explanation = eta.stations[0]?.explanation;
  if (!explanation)
    return (
      <p className="muted small">
        {eta.ml_status === "no_next_station"
          ? "No next-station prediction for this journey."
          : "Carryover estimate · The model is unavailable for this observation."}
      </p>
    );
  const drivers = [...explanation.contributions]
    .sort(
      (a, b) =>
        Math.abs(b.contribution_minutes) - Math.abs(a.contribution_minutes),
    )
    .slice(0, 3);
  return (
    <div className="explanation">
      <p className="eyebrow">BEHIND THE ESTIMATE</p>
      {drivers.map((driver) => (
        <div className="driver" key={driver.feature}>
          <span>{featureLabels[driver.feature] || driver.feature}</span>
          <strong
            className={
              driver.contribution_minutes > 0 ? "text-amber" : "text-teal"
            }
          >
            {signed(driver.contribution_minutes)} min
          </strong>
        </div>
      ))}
      <details>
        <summary>How this estimate is calculated</summary>
        <p>
          SHAP explains the model, not the cause of a real railway delay. Values
          below add to the predicted delay.
        </p>
        <dl>
          <div>
            <dt>Observed delay</dt>
            <dd>{explanation.current_delay_minutes.toFixed(2)} min</dd>
          </div>
          <div>
            <dt>Model starting value</dt>
            <dd>{signed(explanation.base_value_minutes)} min</dd>
          </div>
          {explanation.contributions.map((c) => (
            <div key={c.feature}>
              <dt>{featureLabels[c.feature] || c.feature}</dt>
              <dd>{signed(c.contribution_minutes)} min</dd>
            </div>
          ))}
          <div>
            <dt>Arrival-time adjustment</dt>
            <dd>{signed(explanation.clipping_adjustment_minutes)} min</dd>
          </div>
          <div>
            <dt>Predicted delay</dt>
            <dd>{explanation.predicted_delay_minutes.toFixed(2)} min</dd>
          </div>
        </dl>
        <p>
          Trained and evaluated on synthetic journeys only. ML applies to the
          next station; later stops use carryover estimates.
        </p>
      </details>
    </div>
  );
}
export function JourneyTimeline({
  route,
  network,
  eta,
}: {
  route: Route;
  network: Network;
  eta: TrainETA | null;
}) {
  const now = useClock();
  const current = route.stops.find(
    (s) => s.station_code === eta?.position?.last_station,
  )?.sequence;
  const stations = new Map(network.stations.map((s) => [s.code, s]));
  return (
    <section className="panel timeline-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">FROM ORIGIN TO DESTINATION</p>
          <h2>Journey timeline</h2>
        </div>
        <span className="muted small">{route.stops.length} stops · IST</span>
      </div>
      {!eta?.position && (
        <p className="notice">
          Waiting for this train’s first observation. The route below is the
          archived schedule, not a live arrival forecast.
        </p>
      )}
      <ol className="timeline">
        {route.stops.map((stop) => {
          const forecast = eta?.stations.find(
            (s) => s.station_code === stop.station_code,
          );
          const reached = current !== undefined && stop.sequence <= current;
          const next = eta?.position?.next_station === stop.station_code;
          return (
            <li
              key={stop.station_code}
              className={`${reached ? "reached" : ""} ${next ? "next-stop" : ""}`}
            >
              <span className="timeline-node" />
              <div className="stop-label">
                <span className="station-code">{stop.station_code}</span>
                <Link href={`/station/${stop.station_code}`}>
                  {title(
                    stations.get(stop.station_code)?.name || stop.station_code,
                  )}
                </Link>
                <span className="muted small">
                  {Math.round(stop.distance_km)} km from origin
                  {next ? " · NEXT STOP" : reached ? " · Reached" : ""}
                </span>
              </div>
              <div className="stop-time">
                {forecast ? (
                  <>
                    <div className="time-pair">
                      {forecast.ml_eta && (
                        <del aria-label="Baseline arrival">
                          {time(forecast.baseline_eta)}
                        </del>
                      )}
                      <strong>{time(forecast.eta)}</strong>
                      <span
                        className={`estimate-tag ${forecast.ml_eta ? "ml" : ""}`}
                      >
                        {forecast.ml_eta ? "ML" : "Carryover"}
                      </span>
                    </div>
                    <span className="muted small">
                      {date(forecast.eta)} · scheduled{" "}
                      {time(forecast.scheduled_arrival)},{" "}
                      {date(forecast.scheduled_arrival)}
                    </span>
                    <div>
                      <Badge
                        delay={Math.max(
                          0,
                          (Date.parse(forecast.eta) -
                            Date.parse(forecast.scheduled_arrival)) /
                            60000,
                        )}
                        status={statusAt(eta!.status, eta!.as_of, now)}
                      />
                    </div>
                  </>
                ) : (
                  <span className="muted small">
                    {reached
                      ? "Arrival time not recorded here"
                      : "Awaiting observation"}
                  </span>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
export function ActiveEvents({ eta }: { eta: TrainETA }) {
  return (
    <section className="panel event-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">JOURNEY CONDITIONS</p>
          <h2>
            Active events{" "}
            <span className="count">{eta.active_events.length}</span>
          </h2>
        </div>
      </div>
      {!eta.active_events.length ? (
        <Empty
          title="No active events"
          text="No disruption was active at the latest observation."
        />
      ) : (
        <ul className="event-list">
          {eta.active_events.map((event) => (
            <li key={event.id}>
              <div>
                <strong>{title(event.event_type)}</strong>
                <span className={`severity-tag severity-${event.severity}`}>
                  Severity {event.severity}/3
                </span>
              </div>
              <p>{event.description}</p>
              <span className="muted small">
                {time(event.timestamp)} IST ·{" "}
                {Math.round(event.duration_seconds / 60)} min duration
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="muted small">
        As of {time(eta.as_of)} IST · Events are synthetic and scoped to this
        journey.
      </p>
    </section>
  );
}
