import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";
import type { TrainETA } from "../lib/types";
import { time } from "../lib/format";

// Run immediately after the real six-train smoke, with no simulator still posting.
// Only OSM tiles are mocked: all API and WebSocket traffic is real.
test("real API, Redis and model drive all three browser views", async ({
  page,
  request,
}) => {
  const api = process.env.LIVE_API_URL || "http://127.0.0.1:8000";
  const networkResponse = await request.get("/api/network");
  expect(networkResponse.ok()).toBeTruthy();
  expect((await networkResponse.json()).stations).toHaveLength(63);
  expect((await request.get("/api/ingest/position")).status()).toBe(404);
  expect(
    (await request.post("/api/ingest/position", { data: {} })).status(),
  ).toBe(405);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.route("https://tile.openstreetmap.org/**", (route) =>
    route.fulfill({
      contentType: "image/png",
      body: Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6oX0AAAAASUVORK5CYII=",
        "base64",
      ),
    }),
  );
  await page.goto("/?train=12301");
  await expect(page.getByText("Live updates", { exact: true })).toBeVisible();
  const initialResponse = await request.get(`${api}/trains/12301/eta`);
  expect(initialResponse.ok()).toBeTruthy();
  const initial: TrainETA = await initialResponse.json();
  expect(initial.status).toBe("active");
  expect(initial.position).not.toBeNull();
  const held = {
    ...initial.position!,
    id: randomUUID(),
    timestamp: new Date().toISOString(),
    current_speed_kmh: 0,
  };
  held.delay_minutes +=
    (Date.parse(held.timestamp) - Date.parse(initial.position!.timestamp)) /
    60000;
  const posted = await request.post(`${api}/ingest/position`, { data: held });
  expect(posted.status(), await posted.text()).toBe(201);
  await expect
    .poll(async () =>
      Date.parse(
        (await page.locator(".feed-status time").getAttribute("datetime"))!,
      ),
    )
    .toBe(Date.parse(held.timestamp));
  const updated: TrainETA = await (
    await request.get(`${api}/trains/12301/eta`)
  ).json();
  await expect(page.locator(".hero-time")).toContainText(
    time(updated.stations[0].eta),
  );
  await expect(
    page.getByRole("region", { name: "Route map for train 12301" }),
  ).toBeVisible();
  await page.goto(`/station/${updated.stations[0].station_code}`);
  await expect(
    page.locator(".arrivals-table tbody tr").filter({ hasText: "12301" }),
  ).toContainText(time(updated.stations[0].eta));
  await page.goto("/control");
  await expect(page.locator(".fleet-table tbody tr")).toHaveCount(6);
  await page.getByRole("button", { name: "View train 12301" }).click();
  await expect(
    page.getByRole("dialog").getByRole("heading", { name: "Recorded history" }),
  ).toBeVisible();
  await expect(
    page.getByRole("dialog").locator(".history-table tbody tr"),
  ).not.toHaveCount(0);
  expect(errors).toEqual([]);
});
