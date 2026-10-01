"use client";

import dynamic from "next/dynamic";
import { useMemo } from "react";
import type { LiveStation, RailRadarResult } from "@/lib/railradar";

export type LiveMapModel = {
  number: string;
  line: [number, number][];
  stations: { point: [number, number]; label: string }[];
  location: { point: [number, number]; label: string } | null;
};
export type LiveMapProps = { model: LiveMapModel; recent: boolean };
const Canvas = dynamic(() => import("./live-map-canvas"), {
  ssr: false,
  loading: () => <div className="map-loading" role="status">Loading RailRadar map…</div>,
});
function point(station: LiveStation | null | undefined): [number, number] | null {
  const { lat, lon } = station || {};
  return typeof lat === "number" && typeof lon === "number" &&
    Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180
    ? [lat, lon] : null;
}
function name(station: LiveStation) {
  return [station.station_name, station.station_code].filter(Boolean).join(" · ") || "Unnamed station";
}
function mapModel(data: RailRadarResult["data"]): LiveMapModel {
  const stations = data.route.flatMap((stop) => {
    const coordinates = point(stop);
    return coordinates ? [{ point: coordinates, label: name(stop) }] : [];
  });
  const line: [number, number][] = data.geometry?.type === "LineString"
    ? data.geometry.coordinates.map(([lon, lat]) => [lat, lon]) : [];
  const current = data.current_location;
  let location: LiveMapModel["location"] = null;
  const actual = point(current);
  if (current?.is_actual_position === true && actual) {
    location = { point: actual, label: "Provider-reported position" };
  } else if (current?.station_code) {
    const matches = data.route.filter((stop) => stop.station_code === current.station_code &&
      (current.sequence == null || stop.sequence === current.sequence));
    // Repeated stations require a matching sequence; never guess a route occurrence.
    const stop = matches.length === 1 ? matches[0] : null;
    const coordinates = point(stop);
    if (stop && coordinates) location = { point: coordinates, label: `Last reported station · ${name(stop)}` };
  }
  return { number: data.train_number, line, stations, location };
}

export function LiveRouteMap({ data, freshness }: {
  data: RailRadarResult["data"];
  freshness: RailRadarResult["freshness"];
}) {
  const model = useMemo(() => mapModel(data), [data]);
  const available = model.line.length > 1 || model.stations.length > 0 || !!model.location;
  return <section className="panel live-map-panel" aria-label="Provider route map">
    <div className="panel-heading"><h2>RailRadar route map</h2></div>
    {available ? <div className="route-map">
      <Canvas model={model} recent={freshness === "recent"} />
      <div className="map-caption">{model.line.length > 1
        ? "Route geometry supplied by RailRadar."
        : "Route geometry unavailable; showing reported stations or position only."}</div>
    </div> : <p className="live-map-note">Map unavailable: RailRadar did not supply usable route or station coordinates. Running status and timings are shown separately.</p>}
    <div className="live-map-note">
      <p>{model.location?.label || "No unambiguous reported location can be placed on this map."}</p>
      <p className="muted small">{freshness === "recent"
        ? "Marker uses the latest provider report shown above; it does not move between lookups."
        : "Report is stale, non-live or unverified. Any marker is historical context, not a current position."}
        {model.location?.label === "Provider-reported position" ? " Position accuracy is not independently verified." : " A station marker is not GPS tracking."}</p>
    </div>
  </section>;
}
