import Link from "next/link";
export default function NotFound() {
  return (
    <div className="empty-state">
      <h1>That route isn’t on this network.</h1>
      <p>Choose one of the six demo trains to continue.</p>
      <Link className="secondary-button" href="/">
        Back to passenger view
      </Link>
    </div>
  );
}
