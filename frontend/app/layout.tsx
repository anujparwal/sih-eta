import type { Metadata } from "next";
import "leaflet/dist/leaflet.css";
import "./globals.css";
import { Shell } from "@/components/shell";

export const metadata: Metadata = {
  title: "RailScope · Dynamic Train ETA",
  description:
    "Passenger arrivals, station boards and fleet operations for six simulated trains on historical Indian routes.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
