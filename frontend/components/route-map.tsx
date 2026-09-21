"use client";

import dynamic from "next/dynamic";
import type { Network, Position, Status } from "@/lib/types";

export type MapTrain = {
  number: string;
  name: string;
  position: Position;
  status: Status;
};
export type RouteMapProps = {
  network: Network;
  trains: MapTrain[];
  routeNumber?: string;
  onSelect?: (number: string) => void;
};
const MapCanvas = dynamic(() => import("./map-canvas"), {
  ssr: false,
  loading: () => (
    <div className="map-loading" role="status">
      Loading route map…
    </div>
  ),
});
export function RouteMap(props: RouteMapProps) {
  return (
    <div className="route-map">
      <MapCanvas {...props} />
      <div className="map-caption">
        <span className="route-key" /> Schematic station connectors · Not
        surveyed tracks
      </div>
    </div>
  );
}
