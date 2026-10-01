import { expect, test } from "@playwright/test";
import type { RailRadarResult } from "../lib/railradar";

test.beforeEach(async ({ page }) => {
  await page.clock.install({ time: new Date() });
});

function report(): RailRadarResult {
  return {
    source: "railradar", fetched_at: new Date().toISOString(), cached: false,
    freshness: "recent", warning: null, cache_seconds: 300,
    data: {
      train_number: "22222", train_name: "Provider test express",
      journey_start_date: "2026-09-21", updated_at: new Date().toISOString(),
      status: "running", delay_minutes: null, is_live: true, tracking_mode: "real-time",
      train: { source: { station_code: "AAA", station_name: "Origin" }, destination: { station_code: "BBB", station_name: "Destination" } },
      current_location: { station_code: "AAA", station_name: "Origin", status: "departed", is_actual_position: null },
      next_halt: { station_code: "BBB", station_name: "Destination" },
      route: [{
        sequence: 1, station_code: "AAA", station_name: "Origin", is_halt: true, status: "departed",
        scheduled_arrival: null, scheduled_departure: "2026-09-21T23:45:00+05:30",
        reported_arrival: null, reported_departure: "2026-09-22T00:10:00+05:30", platform: null,
      }, {
        sequence: 2, station_code: "PASS", station_name: "Passing station", is_halt: false, status: "upcoming",
        scheduled_arrival: null, scheduled_departure: null, reported_arrival: null, reported_departure: null, platform: "2",
      }], exceptions: [],
    },
  };
}

test("live lookup is on demand, accepts a train outside the demo and shows provider provenance", async ({ page }) => {
  const calls: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/live/trains/**", async (route) => {
    calls.push(route.request().url());
    await route.fulfill({ json: report() });
  });
  await page.goto("/live?train=22222&date=2026-09-21");
  await expect(page.getByRole("heading", { name: "Find your running train." })).toBeVisible();
  await expect(page.getByText("RAILRADAR DATA", { exact: true })).toBeVisible();
  await expect(page.getByText("SIMULATED DATA", { exact: true })).toHaveCount(0);
  expect(calls).toHaveLength(0);
  await page.getByRole("button", { name: "Look up train" }).click();
  await expect(page.getByRole("heading", { name: "Provider test express" })).toBeVisible();
  expect(calls).toHaveLength(1);
  expect(new URL(calls[0]).searchParams.get("date")).toBe("2026-09-21");
  await expect(page.locator(".live-metrics").getByText("Not reported", { exact: true })).toBeVisible();
  await expect(page.getByText(/Provider updated:/)).toBeVisible();
  await expect(page.getByText("22 Sept 2026, 00:10", { exact: true })).toBeVisible();
  await expect(page.getByText("Passing station · PASS", { exact: true })).toHaveCount(0);
  await page.getByLabel("Halting stations only").uncheck();
  await expect(page.getByText("Passing station · PASS", { exact: true })).toBeVisible();
  await page.clock.fastForward(310000);
  expect(calls).toHaveLength(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  expect(errors).toEqual([]);
});

for (const [code, message] of [
  [404, "No RailRadar data for this train and journey start date."],
  [429, "Local RailRadar request budget reached. Cached data only."],
  [503, "RailRadar rejected the server API key or plan access."],
] as const) {
  test(`provider ${code} is visible without automatic retries`, async ({ page }) => {
    let calls = 0;
    await page.route("**/api/live/trains/**", async (route) => {
      calls++;
      await route.fulfill({ status: code, json: { detail: message } });
    });
    await page.goto("/live");
    await page.getByLabel("Train number", { exact: true }).fill("22222");
    await page.getByRole("button", { name: "Look up train" }).click();
    await expect(page.getByRole("main").getByRole("alert")).toHaveText(message);
    await page.clock.fastForward(120000);
    expect(calls).toBe(1);
  });
}

test("old or non-live reports cannot look fresh, and changing trains clears the previous result", async ({ page }) => {
  const old = report();
  old.cached = true;
  old.freshness = "stale";
  old.data.updated_at = "2020-01-01T00:00:00Z";
  old.warning = "RailRadar is temporarily unavailable.";
  await page.route("**/api/live/trains/22222?*", (route) => route.fulfill({ json: old }));
  await page.route("**/api/live/trains/99999?*", (route) => route.fulfill({ status: 404, json: { detail: "No data for this train." } }));
  await page.goto("/live?train=22222");
  await page.getByRole("button", { name: "Look up train" }).click();
  await expect(page.getByText(/provider report is stale/)).toBeVisible();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("not a fresh update");
  await page.getByLabel("Train number", { exact: true }).fill("99999");
  await page.getByRole("button", { name: "Look up train" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("No data for this train");
  await expect(page.getByRole("heading", { name: "Provider test express" })).toHaveCount(0);
});

test("a report ages into stale while the page is open", async ({ page }) => {
  await page.route("**/api/live/trains/**", (route) => route.fulfill({ json: report() }));
  await page.goto("/live?train=22222");
  await page.getByRole("button", { name: "Look up train" }).click();
  await expect(page.getByRole("heading", { name: "Provider test express" })).toBeVisible();
  await page.clock.fastForward(660000);
  await expect(page.getByText(/provider report is stale/)).toBeVisible();
});

test("non-live and missing freshness are explicit", async ({ page }) => {
  const data = report();
  data.data.is_live = false;
  data.freshness = "not_live";
  await page.route("**/api/live/trains/**", (route) => route.fulfill({ json: data }));
  await page.goto("/live?train=22222");
  await page.getByRole("button", { name: "Look up train" }).click();
  await expect(page.getByText(/marks this response as not live/)).toBeVisible();
  data.data.is_live = null;
  data.data.updated_at = null;
  data.freshness = "unknown";
  await page.getByRole("button", { name: "Look up train" }).click();
  await expect(page.getByText(/freshness of this provider report cannot be verified/)).toBeVisible();
});
