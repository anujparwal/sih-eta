"use client";

import * as L from "leaflet";
import { useEffect, useRef, useState } from "react";
import type { LiveMapProps } from "./live-route-map";

function tooltip(text: string) {
  const node = document.createElement("span");
  node.textContent = text;
  return node;
}
export default function LiveMapCanvas({ model, recent }: LiveMapProps) {
  const element = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const marker = useRef<L.Marker | null>(null);
  const bounds = useRef<L.LatLngBounds | null>(null);
  const [tilesFailed, setTilesFailed] = useState(false);
  useEffect(() => {
    if (!element.current) return;
    const instance = L.map(element.current, { scrollWheelZoom: false });
    map.current = instance;
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
    }).on("tileerror", () => setTilesFailed(true)).addTo(instance);
    const points: L.LatLngTuple[] = [...model.line, ...model.stations.map((s) => s.point)];
    if (model.line.length > 1) L.polyline(model.line, { color: "#167d70", weight: 3 }).addTo(instance);
    for (const station of model.stations) {
      L.circleMarker(station.point, { radius: 3, weight: 1, color: "#167d70", fillColor: "#fff", fillOpacity: 1 })
        .bindTooltip(tooltip(station.label)).addTo(instance);
    }
    if (model.location) {
      points.push(model.location.point);
      marker.current = L.marker(model.location.point, {
        title: model.location.label, alt: model.location.label,
        icon: L.divIcon({ className: "live-location-marker", html: "<span></span>", iconSize: [30, 30], iconAnchor: [15, 15] }),
      }).bindTooltip(tooltip(model.location.label), { direction: "top", offset: [0, -15] }).addTo(instance);
    }
    bounds.current = L.latLngBounds(points);
    instance.fitBounds(bounds.current, { padding: [25, 25], maxZoom: 10 });
    const observer = new ResizeObserver(() => instance.invalidateSize());
    observer.observe(element.current);
    return () => {
      observer.disconnect();
      instance.remove();
      map.current = null;
      marker.current = null;
      bounds.current = null;
    };
  }, [model]);
  useEffect(() => {
    const node = marker.current?.getElement();
    if (node) node.dataset.freshness = recent ? "recent" : "unverified";
  }, [model, recent]);
  return <>
    <div className="live-map-controls">
      <button type="button" onClick={() => bounds.current && map.current?.fitBounds(bounds.current, { padding: [25, 25], maxZoom: 10 })}>Fit route</button>
      {model.location && <button type="button" onClick={() => model.location && map.current?.setView(model.location.point, 12)}>Show reported location</button>}
    </div>
    <div ref={element} className="map-canvas" role="region" aria-label={`RailRadar map for train ${model.number}`} />
    {tilesFailed && <div className="tile-notice">Base map unavailable. Provider route and markers remain visible.</div>}
  </>;
}
