export type LiveStation = {
  station_code: string | null;
  station_name: string | null;
};
export type RailRadarResult = {
  source: "railradar";
  fetched_at: string;
  cached: boolean;
  freshness: "recent" | "stale" | "unknown" | "not_live";
  warning: string | null;
  cache_seconds: number;
  data: {
    train_number: string;
    train_name: string | null;
    journey_start_date: string | null;
    updated_at: string | null;
    status: string | null;
    delay_minutes: number | null;
    is_live: boolean | null;
    tracking_mode: string | null;
    train: { source: LiveStation | null; destination: LiveStation | null } | null;
    current_location: (LiveStation & { status: string | null; is_actual_position: boolean | null }) | null;
    next_halt: LiveStation | null;
    route: (LiveStation & {
      sequence: number;
      is_halt: boolean | null;
      status: string | null;
      scheduled_arrival: string | null;
      scheduled_departure: string | null;
      reported_arrival: string | null;
      reported_departure: string | null;
      platform: string | number | null;
    })[];
    exceptions: { type: string | null; message: string | null }[];
  };
};
