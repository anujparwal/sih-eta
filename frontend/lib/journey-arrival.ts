import type { RailRadarResult } from "./railradar";
export type LiveStop = RailRadarResult["data"]["route"][number];
export const stopId = (stop: LiveStop) => `${stop.sequence}:${stop.station_code || ""}`;
export const stopName = (stop: LiveStop) => [stop.station_name, stop.station_code].filter(Boolean).join(" · ") || "Unnamed stop";
const normalize = (value: string | null) => (value || "").toLowerCase().replaceAll(/[_ ]/g, "-");
const millis = (value: string | null) => value && Number.isFinite(Date.parse(value)) ? Date.parse(value) : null;
export function arrivalState(result: RailRadarResult, stop: LiveStop, freshness: RailRadarResult["freshness"], now: number) {
  const state = normalize(stop.status);
  const train = normalize(result.data.status);
  const reported = millis(stop.reported_arrival);
  const scheduled = millis(stop.scheduled_arrival);
  let message: string;
  let countdown: number | null = null;
  if ([state, train].some((value) => value === "cancelled" || value === "canceled")) message = "The provider marks this service or stop as cancelled. Do not rely on its arrival time.";
  else if (state === "skipped") message = "The provider marks this stop as skipped. Check alternative travel arrangements.";
  else if (state === "departed" || state === "passed") message = "The provider reports that the train has already passed this stop.";
  else if (state === "arrived" || state === "at-station") message = "The provider reports the train at this stop. Confirm its latest status before travelling.";
  else if (stop.is_halt !== true) message = "A passenger halt at this station is not confirmed by the provider.";
  else if (freshness !== "recent" || result.warning || result.data.is_live !== true) message = "A current arrival estimate cannot be confirmed from this report. Refresh to check for newer information.";
  else if (train !== "running" || state !== "upcoming") message = "Check the reported service status. A current arrival countdown is unavailable.";
  else if (reported === null) message = "No live arrival estimate was supplied. The timetable alone does not tell you when the train will arrive.";
  else if (!now) message = "Checking the arrival report time…";
  else if (reported <= now) message = "This arrival report is in the past. Refresh for an update; it does not confirm that the train has arrived.";
  else {
    countdown = Math.ceil((reported - now) / 60000);
    message = "Based on the provider’s reported arrival. This estimate may change.";
  }
  return {
    message, countdown,
    difference: reported !== null && scheduled !== null ? Math.round((reported - scheduled) / 60000) : null,
  };
}
export function journeyLink(result: RailRadarResult, requestedDate: string, selected: string) {
  const query = new URLSearchParams({ train: result.data.train_number, date: result.data.journey_start_date || requestedDate });
  if (selected) query.set("stop", selected);
  return `/?${query}`;
}
export function todayInIndia() {
  const parts = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
  const value = (type: string) => parts.find((part) => part.type === type)!.value;
  return `${value("year")}-${value("month")}-${value("day")}`;
}
