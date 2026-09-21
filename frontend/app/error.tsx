"use client";
import Link from "next/link";
export default function Error({ retry }: { retry: () => void }) {
  return (
    <section className="panel empty-state" role="alert">
      <h1>This view could not be loaded</h1>
      <p>
        Your train data has not been changed. Retry this view or return to the
        passenger dashboard.
      </p>
      <button className="secondary-button" onClick={retry}>
        Try again
      </button>
      <Link className="inline-link" href="/">
        Passenger dashboard
      </Link>
    </section>
  );
}
