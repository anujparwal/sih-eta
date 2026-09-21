export type Status = "active" | "stale" | "completed" | "no_data";
export type Position = {
  id: string;
  journey_id: string;
  journey_started_at: string | null;
  train_number: string;
  timestamp: string;
  lat: number;
  lon: number;
  distance_km: number;
  delay_minutes: number;
  current_speed_kmh: number;
  last_station: string;
  next_station: string | null;
};
export type Station = {
  code: string;
  name: string;
  zone: string | null;
  lat: number;
  lon: number;
};
export type Stop = {
  sequence: number;
  station_code: string;
  distance_km: number;
  arrival_seconds: number | null;
  departure_seconds: number | null;
};
export type Route = {
  train_number: string;
  train_name: string;
  total_distance_km: number;
  stops: Stop[];
};
export type Network = {
  dataset_version: string;
  schedule_timezone: string;
  geometry_kind: string;
  sources: Record<string, { url: string; sha256: string }>;
  stations: Station[];
  routes: Route[];
};
export type Contribution = {
  feature: string;
  value: number | null;
  contribution_minutes: number;
};
export type Explanation = {
  base_value_minutes: number;
  contributions: Contribution[];
  raw_residual_minutes: number;
  current_delay_minutes: number;
  clipping_adjustment_minutes: number;
  predicted_delay_minutes: number;
};
export type StationETA = {
  station_code: string;
  station_name: string;
  sequence: number;
  distance_remaining_km: number;
  scheduled_arrival: string;
  baseline_eta: string;
  eta: string;
  ml_eta: string | null;
  eta_baseline_minutes: number | null;
  eta_ml_minutes: number | null;
  prediction_method: string;
  model_version: string | null;
  predicted_delay_minutes: number | null;
  explanation: Explanation | null;
};
export type Incident = {
  id: string;
  journey_id: string;
  timestamp: string;
  event_type: string;
  severity: number;
  description: string;
  duration_seconds: number;
};
export type TrainETA = {
  train_number: string;
  generated_at: string;
  status: Status;
  journey_id: string | null;
  position_id: string | null;
  as_of: string | null;
  journey_started_at: string | null;
  current_delay_minutes: number | null;
  stations: StationETA[];
  position: Position | null;
  active_events: Incident[];
  ml_status: string;
};
export type TrainSummary = {
  train_number: string;
  train_name: string;
  origin: string;
  destination: string;
  status: Status;
  latest_position: Position | null;
};
export type Fleet = {
  generated_at: string;
  trains: TrainSummary[];
  total_trains: number;
  active_trains: number;
  stale_trains: number;
  completed_trains: number;
  no_data_trains: number;
};
export type Arrival = StationETA & {
  train_number: string;
  train_name: string;
  journey_id: string;
  as_of: string;
  status: Status;
};
export type Arrivals = {
  generated_at: string;
  station_code: string;
  arrivals: Arrival[];
};
export type History = {
  train_number: string;
  journey_id: string | null;
  positions: Position[];
  next_after: string | null;
};
