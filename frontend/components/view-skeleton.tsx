import { Loading } from "./common";

export function ViewSkeleton({
  kind,
}: {
  kind: "passenger" | "station" | "control";
}) {
  const name =
    kind === "passenger"
      ? "your journey"
      : kind === "station"
        ? "arrivals"
        : "the fleet";
  return (
    <section
      className={`view-skeleton ${kind}`}
      aria-busy="true"
      aria-label={`Loading ${name}`}
    >
      <h1 className="sr-only">Loading {name}</h1>
      <div className="skeleton skeleton-heading" aria-hidden="true" />
      <div className="skeleton skeleton-subheading" aria-hidden="true" />
      {kind === "control" && (
        <div className="stats-grid" aria-hidden="true">
          {[0, 1, 2, 3].map((n) => (
            <div className="panel skeleton-stat" key={n}>
              <span className="skeleton" />
              <span className="skeleton short" />
            </div>
          ))}
        </div>
      )}
      <div className="skeleton-layout">
        {kind === "passenger" && (
          <div className="panel skeleton-picker" aria-hidden="true">
            {[0, 1, 2, 3].map((n) => (
              <span className="skeleton" key={n} />
            ))}
          </div>
        )}
        <div className="panel skeleton-content">
          <Loading label={`Loading ${name}`} />
          <div className="skeleton skeleton-map" aria-hidden="true" />
          {[0, 1, 2].map((n) => (
            <div className="skeleton skeleton-row" aria-hidden="true" key={n} />
          ))}
        </div>
      </div>
    </section>
  );
}
