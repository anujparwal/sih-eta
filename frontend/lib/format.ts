import type { Status } from "./types";

export function title(value: string) {
  return value
    .toLowerCase()
    .replace(/(^|[\s_])\w/g, (word) => word.toUpperCase())
    .replaceAll("_", " ");
}
const clockFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Kolkata",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});
const dateFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Kolkata",
  day: "2-digit",
  month: "short",
});
export function time(value: string | number | null) {
  return value ? clockFormat.format(new Date(value)) : "—";
}
export function date(value: string | number | null) {
  return value ? dateFormat.format(new Date(value)) : "—";
}
export function delayText(value: number | null) {
  if (value === null) return "No observation";
  if (value <= 0) return "On time";
  return value < 1 ? "<1 min late" : `${Math.round(value)} min late`;
}
export function severity(value: number | null) {
  return value === null
    ? "neutral"
    : value <= 0
      ? "good"
      : value < 15
        ? "warn"
        : "bad";
}
export function statusAt(
  status: Status,
  asOf: string | null | undefined,
  now: number,
): Status {
  if (status === "active" && asOf && now && now - Date.parse(asOf) > 30000)
    return "stale";
  return status;
}
export function age(value: string | number | null | undefined, now: number) {
  if (!value || !now) return "Waiting for data";
  const seconds = Math.max(
    0,
    Math.floor((now - new Date(value).getTime()) / 1000),
  );
  return seconds < 60
    ? `${seconds}s ago`
    : seconds < 3600
      ? `${Math.floor(seconds / 60)}m ago`
      : `${Math.floor(seconds / 3600)}h ago`;
}
export function until(value: string | null, now: number) {
  if (!value || !now) return "—";
  const minutes = Math.ceil((Date.parse(value) - now) / 60000);
  return minutes > 0 ? `${minutes} min` : "Estimate passed";
}
export function signed(value: number) {
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}`;
}
