"use client";

import * as L from "leaflet";
import { useEffect, useRef, useState } from "react";
import { delayText, severity, title } from "@/lib/format";
import type { RouteMapProps } from "./route-map";

const colors = {
  good: "#147a64",
  warn: "#b97717",
  bad: "#bd4545",
  neutral: "#64748b",
};
export default function MapCanvas({
  network,
  trains,
  routeNumber,
  onSelect,
}: RouteMapProps) {
  const element = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const marks = useRef<L.LayerGroup | null>(null);
  const [tilesFailed, setTilesFailed] = useState(false);
  const markers = useRef(
    new Map<string, { marker: L.Marker; color: string; label: string }>(),
  );
  const select = useRef(onSelect);
  useEffect(() => {
    if (!element.current) return;
    const currentMarkers = markers.current;
    const instance = L.map(element.current, {
      scrollWheelZoom: false,
      attributionControl: true,
    });
    map.current = instance;
    const tiles = L.tileLayer(
      "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
      {
        maxZoom: 18,
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
      },
    ).addTo(instance);
    tiles.on("tileerror", () => setTilesFailed(true));
    const stations = new Map(network.stations.map((s) => [s.code, s]));
    const routes = routeNumber
      ? network.routes.filter((r) => r.train_number === routeNumber)
      : network.routes;
    const coordinates: L.LatLngTuple[] = [];
    for (const route of routes) {
      const points: L.LatLngTuple[] = route.stops.flatMap((s) => {
        const station = stations.get(s.station_code);
        return station ? [[station.lat, station.lon] as L.LatLngTuple] : [];
      });
      coordinates.push(...points);
      L.polyline(points, {
        color: routeNumber ? "#167d70" : "#8ca9ae",
        weight: routeNumber ? 3 : 2,
        opacity: 0.8,
        dashArray: "6 5",
      }).addTo(instance);
      if (routeNumber)
        for (const stop of route.stops) {
          const station = stations.get(stop.station_code);
          if (!station) continue;
          const label = document.createElement("span");
          label.textContent = `${station.code} · ${title(station.name)}`;
          L.circleMarker([station.lat, station.lon], {
            radius: 4,
            color: "#167d70",
            weight: 2,
            fillColor: "#fff",
            fillOpacity: 1,
          })
            .bindTooltip(label)
            .addTo(instance);
        }
    }
    if (coordinates.length)
      instance.fitBounds(L.latLngBounds(coordinates), {
        padding: [30, 30],
        maxZoom: 9,
      });
    else instance.setView([23, 79], 5);
    marks.current = L.layerGroup().addTo(instance);
    const observer = new ResizeObserver(() => instance.invalidateSize());
    observer.observe(element.current);
    return () => {
      observer.disconnect();
      currentMarkers.clear();
      instance.remove();
      map.current = null;
      marks.current = null;
    };
  }, [network, routeNumber]);
  useEffect(() => {
    if (!marks.current) return;
    select.current = onSelect;
    const currentNumbers = new Set(trains.map((train) => train.number));
    for (const [number, entry] of markers.current) {
      if (!currentNumbers.has(number)) {
        marks.current.removeLayer(entry.marker);
        markers.current.delete(number);
      }
    }
    for (const train of trains) {
      const color =
        colors[
          train.status === "active"
            ? severity(train.position.delay_minutes)
            : "neutral"
        ];
      const label = `${train.number} ${title(train.name)} · ${train.status === "active" ? delayText(train.position.delay_minutes) : train.status}`;
      const icon = L.divIcon({
        className: "train-map-marker",
        html: `<span style="background:${color}"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><rect x="5" y="3" width="14" height="15" rx="3"/><path d="M5 10h14M8 21l2-3m6 3-2-3M8 14h2m4 0h2"/></svg></span>`,
        iconSize: [34, 34],
        iconAnchor: [17, 17],
      });
      let entry = markers.current.get(train.number);
      if (!entry) {
        const marker = L.marker([train.position.lat, train.position.lon], {
          icon,
          title: label,
          alt: label,
          keyboard: true,
        });
        marker.bindTooltip(document.createElement("span"), {
          direction: "top",
          offset: [0, -17],
        });
        marker.on("click", () => select.current?.(train.number));
        marker.addTo(marks.current);
        entry = { marker, color, label: "" };
        markers.current.set(train.number, entry);
      }
      const location = entry.marker.getLatLng();
      if (
        location.lat !== train.position.lat ||
        location.lng !== train.position.lon
      )
        entry.marker.setLatLng([train.position.lat, train.position.lon]);
      if (entry.color !== color) {
        // Update the existing marker to preserve keyboard focus and open tooltips.
        const dot = entry.marker.getElement()?.querySelector("span");
        if (dot) dot.style.background = color;
        entry.color = color;
      }
      if (entry.label !== label) {
        const tooltip = document.createElement("span");
        tooltip.textContent = label;
        entry.marker.setTooltipContent(tooltip);
        const element = entry.marker.getElement();
        if (element) element.title = label;
        entry.label = label;
      }
    }
  }, [trains, onSelect, network, routeNumber]);
  return (
    <>
      <div
        ref={element}
        className="map-canvas"
        role="region"
        aria-label={
          routeNumber ? `Route map for train ${routeNumber}` : "Fleet route map"
        }
      />
      {tilesFailed && (
        <div className="tile-notice">
          Base map unavailable. Route and position markers remain visible.
        </div>
      )}
    </>
  );
}
