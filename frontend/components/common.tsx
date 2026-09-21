import Link from "next/link";
import { age, delayText, severity } from "@/lib/format";
import type { Status } from "@/lib/types";
import type { Feed } from "@/lib/live";

export function Badge({
  delay,
  status = "active",
}: {
  delay: number | null;
  status?: Status;
}) {
  const label =
    status === "stale"
      ? "Stale signal"
      : status === "completed"
        ? "Completed"
        : status === "no_data"
          ? "Not started"
          : delayText(delay);
  return (
    <span
      className={`badge ${status !== "active" ? "neutral" : severity(delay)}`}
    >
      <span />
      {label}
    </span>
  );
}
export function FeedStatus({ feed, now }: { feed: Feed; now: number }) {
  return (
    <div className="feed-status">
      <span
        className={`status-dot ${feed.connection === "live" ? "online" : ""}`}
      />
      <span>
        {feed.connection === "live"
          ? "Live updates"
          : feed.connection === "polling"
            ? "Polling · reconnecting"
            : feed.connection === "offline"
              ? "Connection interrupted"
              : "Connecting"}
      </span>
      <span className="muted">
        ·{" "}
        <time dateTime={feed.data?.as_of || undefined}>
          {age(feed.data?.as_of, now)}
        </time>
      </span>
    </div>
  );
}
export function ErrorNotice({
  message,
  retry,
}: {
  message: string;
  retry?: () => void;
}) {
  return (
    <div className="notice error" role="alert">
      <span>{message}</span>
      {retry && (
        <button className="text-button" onClick={retry}>
          Try again
        </button>
      )}
    </div>
  );
}
export function Empty({ title, text }: { title: string; text: string }) {
  return (
    <div className="empty-state">
      <span className="empty-symbol" aria-hidden="true">
        ◌
      </span>
      <h3>{title}</h3>
      <p>{text}</p>
    </div>
  );
}
export function Loading({ label = "Loading train data" }: { label?: string }) {
  return (
    <div className="loading-state" role="status">
      <span className="skeleton" />
      <span className="skeleton short" />
      <p>{label}…</p>
    </div>
  );
}
export function ViewHeader({
  eyebrow,
  title,
  subtitle,
  right,
}: {
  eyebrow: string;
  title: string;
  subtitle: string;
  right?: React.ReactNode;
}) {
  return (
    <header className="view-header">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="subheading">{subtitle}</p>
      </div>
      {right}
    </header>
  );
}
export function TrainLink({
  number,
  children,
}: {
  number: string;
  children: React.ReactNode;
}) {
  return (
    <Link className="inline-link" href={`/?train=${number}`}>
      {children}
    </Link>
  );
}
