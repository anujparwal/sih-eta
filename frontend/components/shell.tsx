"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export function Icon({
  name,
  size = 20,
}: {
  name: "train" | "station" | "control" | "arrow" | "pin" | "signal";
  size?: number;
}) {
  const paths = {
    train: (
      <>
        <rect x="5" y="3" width="14" height="15" rx="4" />
        <path d="M5 10h14M9 18l-3 3m9-3 3 3M9 6h6" />
        <path d="M8 14h.01M16 14h.01" />
      </>
    ),
    station: (
      <>
        <path d="M3 21h18M4 21V8l8-5 8 5v13M8 21v-7h8v7M9 9h6" />
      </>
    ),
    control: (
      <>
        <rect x="3" y="3" width="7" height="7" rx="1" />
        <rect x="14" y="3" width="7" height="7" rx="1" />
        <rect x="3" y="14" width="7" height="7" rx="1" />
        <rect x="14" y="14" width="7" height="7" rx="1" />
      </>
    ),
    arrow: (
      <>
        <path d="M4 12h16m-6-6 6 6-6 6" />
      </>
    ),
    pin: (
      <>
        <path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 1 1 14 0Z" />
        <circle cx="12" cy="10" r="2" />
      </>
    ),
    signal: (
      <>
        <path d="M4 19v-4m5 4V11m5 8V7m5 12V3" />
      </>
    ),
  };
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {paths[name]}
    </svg>
  );
}
export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <aside className="sidebar">
        <Link href="/" className="brand" aria-label="RailScope home">
          <span className="brand-mark">
            <Icon name="train" size={25} />
          </span>
          <span>
            RailScope<small>ARRIVALS, EXPLAINED.</small>
          </span>
        </Link>
        <p className="nav-caption">YOUR NETWORK</p>
        <nav aria-label="Main navigation">
          {[
            { href: "/", text: "Passenger", icon: "train" as const },
            {
              href: "/station/NDLS",
              text: "Station board",
              icon: "station" as const,
            },
            {
              href: "/control",
              text: "Control room",
              icon: "control" as const,
            },
          ].map((item) => {
            const active =
              item.href === "/"
                ? pathname === "/"
                : pathname.startsWith(
                    item.href.split("/").slice(0, 2).join("/"),
                  );
            return (
              <Link
                key={item.href}
                href={item.href}
                className={active ? "nav-link active" : "nav-link"}
                aria-current={active ? "page" : undefined}
              >
                <Icon name={item.icon} />
                {item.text}
                {active && <span className="nav-dot" />}
              </Link>
            );
          })}
        </nav>
        <div className="sidebar-bottom">
          <span className="eyebrow">SIH 2026 · DEMONSTRATION</span>
          <p>
            Six trains.
            <br />
            One connected view.
          </p>
          <span className="sidebar-rule" />
          <small>Synthetic telemetry on archived Indian railway routes.</small>
        </div>
      </aside>
      <div className="workspace">
        <div className="topbar">
          <span>
            INDIAN RAIL NETWORK <span className="muted">/</span>{" "}
            <strong>
              {pathname.startsWith("/control")
                ? "Operations"
                : pathname.startsWith("/station")
                  ? "Station arrivals"
                  : "Journey planner"}
            </strong>
          </span>
          <span className="demo-tag">
            <span /> SIMULATED DATA
          </span>
        </div>
        <main id="main">{children}</main>
        <footer className="site-footer">
          <span>Built for a clearer journey.</span>
          <span>Historical schedules · Schematic routes · All times IST</span>
        </footer>
      </div>
    </div>
  );
}
