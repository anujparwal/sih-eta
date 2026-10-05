import Link from "next/link";
export default function NotFound() {
  return (
    <div className="empty-state">
      <h1>This page could not be found.</h1>
      <p>Return to train lookup to plan your journey.</p>
      <Link className="secondary-button" href="/">
        Find a train
      </Link>
    </div>
  );
}
