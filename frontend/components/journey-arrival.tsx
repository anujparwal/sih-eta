"use client";

import { useState } from "react";
import type { RailRadarResult } from "@/lib/railradar";
import { arrivalState, journeyLink, stopId, stopName } from "@/lib/journey-arrival";

const formatter = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "numeric",
  hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});
function stamp(value: string | null) {
  return value && Number.isFinite(Date.parse(value)) ? formatter.format(new Date(value)) : "Not reported";
}
export function JourneyArrival({ result, requestedDate, selected, onSelect, freshness, now }: {
  result: RailRadarResult; requestedDate: string; selected: string;
  onSelect: (value: string) => void; freshness: RailRadarResult["freshness"]; now: number;
}) {
  const [share, setShare] = useState<{ url: string; message: string } | null>(null);
  const stops = result.data.route.filter((stop) => stop.is_halt !== false);
  const matches = stops.filter((stop) => stopId(stop) === selected);
  const stop = matches.length === 1 ? matches[0] : null;
  const status = stop ? arrivalState(result, stop, freshness, now) : null;
  const path = journeyLink(result, requestedDate, selected);
  async function copyLink() {
    const url = new URL(path, window.location.origin).href;
    try {
      await navigator.clipboard.writeText(url);
      setShare({ url, message: "Journey link copied. Open it and submit the lookup to get an updated report." });
    } catch {
      setShare({ url, message: "Copy the link below. Open it and submit the lookup to get an updated report." });
    }
  }
  return <section className="panel arrival-planner" aria-label="Your destination arrival">
    <div className="arrival-heading"><div><p className="eyebrow">YOUR JOURNEY</p><h2>When will it reach your station?</h2></div>
      <span className="arrival-source">RailRadar report</span></div>
    <label className="destination-select">Your destination station
      <select value={selected} onChange={(event) => { setShare(null); onSelect(event.target.value); }} disabled={!stops.length}>
        <option value="">Choose a station</option>
        {selected && !stop && <option value={selected}>Saved stop unavailable — choose again</option>}
        {stops.map((entry, index) => <option key={index} value={stopId(entry)}>{stopName(entry)} · stop {entry.sequence}{entry.is_halt === null ? " · halt unconfirmed" : ""}</option>)}
      </select>
    </label>
    {!stops.length && <p className="muted">The provider did not supply passenger stops for this journey.</p>}
    {selected && !stop && <p className="notice warning" role="status">The saved station could not be matched unambiguously to this route. Choose your destination again.</p>}
    {!selected && !!stops.length && <p className="muted">Select where you are travelling to. This uses the report already loaded and makes no extra lookup.</p>}
    {stop && status && <div className="arrival-detail">
      <h3>{stopName(stop)}</h3>
      <div className="arrival-times">
        <div><span>Reported arrival · IST</span><strong>{stamp(stop.reported_arrival)}</strong><small>Provider timing; may be an estimate</small></div>
        <div><span>Scheduled arrival · IST</span><strong>{stamp(stop.scheduled_arrival)}</strong><small>Timetable, not a live prediction</small></div>
        <div><span>Reported platform</span><strong>{stop.platform ?? "Not reported"}</strong><small>Confirm on station displays</small></div>
      </div>
      <div className="arrival-message" role="status">
        {status.countdown !== null && <strong className="arrival-countdown">About {status.countdown < 60 ? `${status.countdown} min` : `${Math.floor(status.countdown / 60)} hr ${status.countdown % 60} min`} remaining</strong>}
        <p>{status.message}</p>
        {freshness !== "recent" && <p>Report freshness: {freshness === "not_live" ? "not live" : freshness}. The times above may no longer apply.</p>}
      </div>
      {status.difference !== null && <p className="muted small">Reported arrival is {status.difference === 0 ? "the same as the timetable" : `${Math.abs(status.difference)} min ${status.difference > 0 ? "later" : "earlier"} than the timetable`}. This is not a measured arrival.</p>}
      <p className="muted small">Provider updated: {stamp(result.data.updated_at)} IST. Check service notices before travelling.</p>
      <button className="secondary-button" type="button" onClick={copyLink}>Copy journey link</button>
      {share && share.url.endsWith(path) && <div className="journey-share"><p role="status">{share.message}</p><input aria-label="Journey link" readOnly value={share.url} onFocus={(event) => event.target.select()} /></div>}
    </div>}
  </section>;
}
