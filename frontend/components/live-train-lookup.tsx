"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Empty, ErrorNotice, Loading, ViewHeader } from "./common";
import { useClock } from "@/lib/live";
import type { LiveStation, RailRadarResult } from "@/lib/railradar";

const formatter = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "numeric",
  hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});
function stamp(value: string | null) {
  return value && Number.isFinite(Date.parse(value)) ? formatter.format(new Date(value)) : "Not reported";
}
function station(value: LiveStation | null | undefined) {
  if (!value) return "Not reported";
  return [value.station_name, value.station_code].filter(Boolean).join(" · ") || "Not reported";
}
function label(value: string | null) {
  return value ? value.replaceAll(/[-_]/g, " ") : "Not reported";
}

export function LiveTrainLookup({ initialTrain, initialDate }: { initialTrain: string; initialDate: string }) {
  const [number, setNumber] = useState(initialTrain);
  const [journeyDate, setJourneyDate] = useState(initialDate);
  const [result, setResult] = useState<RailRadarResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [haltsOnly, setHaltsOnly] = useState(true);
  const active = useRef<AbortController | null>(null);
  const now = useClock();
  useEffect(() => () => active.current?.abort(), []);

  async function lookup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    const timeout = setTimeout(() => controller.abort(), 25000);
    setLoading(true);
    setError(null);
    setResult(null);
    const query = new URLSearchParams();
    if (journeyDate) query.set("date", journeyDate);
    const displayQuery = new URLSearchParams(query);
    displayQuery.set("train", number);
    window.history.replaceState(null, "", `/live?${displayQuery}`);
    try {
      const response = await fetch(`/api/live/trains/${number}?${query}`, {
        cache: "no-store", signal: controller.signal,
      });
      const body = await response.json();
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Enter a valid train number and journey start date.");
      if (body.source !== "railradar" || body.data?.train_number !== number || !Array.isArray(body.data.route)) {
        throw new Error("The live train response was invalid. Please try again.");
      }
      if (active.current === controller) setResult(body);
    } catch (failure) {
      if (active.current === controller) setError(
        controller.signal.aborted ? "The lookup timed out. Please try again." :
          failure instanceof Error ? failure.message : "Unable to load live train data.",
      );
    } finally {
      clearTimeout(timeout);
      if (active.current === controller) setLoading(false);
    }
  }

  const data = result?.data;
  const old = !!data?.updated_at && !!now && now - Date.parse(data.updated_at) > 600000;
  const freshness = result?.freshness === "recent" && old ? "stale" : result?.freshness;
  const stops = data?.route.filter((stop) => !haltsOnly || stop.is_halt !== false) || [];
  return <>
    <ViewHeader eyebrow="RAILRADAR · LIVE LOOKUP" title="Find your running train."
      subtitle="Look up any five-digit train number. Results depend on RailRadar’s coverage and latest reports." />
    <section className="panel live-search" aria-label="Live train search">
      <form onSubmit={lookup} className="live-search-form">
        <label>Train number
          <input inputMode="numeric" pattern="[0-9]{5}" minLength={5} maxLength={5} required
            placeholder="e.g. 12953" value={number} onChange={(event) => setNumber(event.target.value)} />
        </label>
        <label>Journey start date
          <input type="date" value={journeyDate} onChange={(event) => setJourneyDate(event.target.value)} />
        </label>
        <button className="live-search-button" type="submit" disabled={loading}>
          {loading ? "Looking up…" : "Look up train"}
        </button>
      </form>
      <p className="muted small">Leave the date blank for today in India. For an overnight train, select the date it left its origin.</p>
      <p className="muted small">Updates are requested when you submit. Results are shared for five minutes to conserve the free API quota.</p>
    </section>
    {loading && <Loading label="Looking up RailRadar status" />}
    {error && <ErrorNotice message={error} />}
    {!loading && !error && !result && <Empty title="Search beyond the demo network"
      text="Enter a train number above to request its running status. Opening this page does not use an API request." />}
    {result && data && <div className="live-results" aria-live="polite">
      {result.warning && <ErrorNotice message={`${result.warning} Showing the last saved response, not a fresh update.`} />}
      {freshness !== "recent" && <div className="notice warning" role="status">
        {freshness === "stale" ? "The provider report is stale. This may not be the train’s current position." :
          freshness === "not_live" ? "RailRadar marks this response as not live. Check the journey date and train status." :
            "The freshness of this provider report cannot be verified."}
      </div>}
      <section className="panel live-summary">
        <p className="train-number">{data.train_number} · RAILRADAR</p>
        <h2>{data.train_name || "Train name not reported"}</h2>
        <p>{station(data.train?.source)} → {station(data.train?.destination)}</p>
        <p className="muted small">Journey start: {data.journey_start_date || "Not reported"}</p>
        <dl className="live-metrics">
          <div><dt>Reported status</dt><dd>{label(data.status)}</dd></div>
          <div><dt>Reported delay</dt><dd>{data.delay_minutes === null ? "Not reported" : data.delay_minutes === 0 ? "On time" : `${Math.abs(data.delay_minutes)} min ${data.delay_minutes < 0 ? "early" : "late"}`}</dd></div>
          <div><dt>Reported location</dt><dd>{station(data.current_location)}</dd><dd className="muted small">{label(data.current_location?.status || null)}</dd></div>
          <div><dt>Next halt</dt><dd>{station(data.next_halt)}</dd></div>
        </dl>
        <div className="live-provenance">
          <p>Provider updated: <strong>{stamp(data.updated_at)}</strong> IST</p>
          <p>Fetched by this app: {stamp(result.fetched_at)} IST {result.cached ? "· Saved response" : "· New request"}</p>
          <p>Source: <a className="inline-link" href="https://railradar.in" target="_blank" rel="noreferrer">RailRadar</a> · Tracking mode: {label(data.tracking_mode)}</p>
          <p className="muted small">A reported station is not a verified GPS position. Arrival and departure reports may include estimates.</p>
        </div>
      </section>
      {data.exceptions.map((notice, index) => <div className="notice warning" key={index}>
        {notice.type || "Service notice"}: {notice.message || "Check the provider for details."}
      </div>)}
      <section className="panel live-route">
        <div className="panel-heading"><h2>Route and reported timings</h2>
          <label><input type="checkbox" checked={haltsOnly} onChange={(event) => setHaltsOnly(event.target.checked)} /> Halting stations only</label>
        </div>
        <p className="muted small live-table-note">All times IST, including the date. A dash means the provider did not supply that timing.</p>
        {stops.length ? <div className="live-table-scroll" tabIndex={0} role="region" aria-label="Reported route timings">
          <table className="live-table">
            <thead><tr><th scope="col">Station</th><th scope="col">Status</th><th scope="col">Scheduled arrival</th><th scope="col">Reported arrival</th><th scope="col">Scheduled departure</th><th scope="col">Reported departure</th><th scope="col">Platform</th></tr></thead>
            <tbody>{stops.map((stop, index) => <tr key={`${stop.sequence}-${index}`}>
              <th scope="row">{station(stop)}</th><td>{label(stop.status)}</td>
              {[stop.scheduled_arrival, stop.reported_arrival, stop.scheduled_departure, stop.reported_departure].map((value, col) => <td key={col}>{value ? stamp(value) : "—"}</td>)}
              <td>{stop.platform ?? "—"}</td>
            </tr>)}</tbody>
          </table>
        </div> : <Empty title="No route timings available" text="RailRadar did not provide stops matching this filter." />}
      </section>
    </div>}
  </>;
}
