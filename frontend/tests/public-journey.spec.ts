import { expect, test, type Page } from "@playwright/test";
import type { RailRadarResult } from "../lib/railradar";

const instant = "2026-10-05T18:45:00Z"; // Already 6 October in India.
function report(): RailRadarResult {
  return {
    source: "railradar", fetched_at: instant, cached: false, freshness: "recent",
    warning: null, cache_seconds: 300,
    data: {
      train_number: "22222", train_name: "Passenger test express", journey_start_date: "2026-10-06",
      updated_at: instant, status: "running", delay_minutes: 15, is_live: true,
      tracking_mode: "real-time", train: null, current_location: null, next_halt: null,
      exceptions: [], route: [
        { sequence: 1, station_code: "AAA", station_name: "Origin", is_halt: true, status: "departed", scheduled_arrival: null, reported_arrival: null, scheduled_departure: null, reported_departure: null, platform: null },
        { sequence: 2, station_code: "BBB", station_name: "Destination", is_halt: true, status: "upcoming", scheduled_arrival: "2026-10-06T00:30:00+05:30", reported_arrival: "2026-10-06T00:45:00+05:30", scheduled_departure: null, reported_departure: null, platform: "4" },
        { sequence: 3.5, station_code: "BBB", station_name: "Destination return", is_halt: true, status: "upcoming", scheduled_arrival: "2026-10-06T01:30:00+05:30", reported_arrival: "2026-10-06T01:45:00+05:30", scheduled_departure: null, reported_departure: null, platform: "2" },
      ],
    },
  };
}
async function openReport(page: Page, data: RailRadarResult, suffix = "&stop=2%3ABBB") {
  const calls: string[] = [];
  await page.route("**/api/live/trains/**", async (route) => {
    calls.push(route.request().url()); await route.fulfill({ json: data });
  });
  await page.goto(`/?train=22222&date=2026-10-06${suffix}`);
  expect(calls).toHaveLength(0);
  await page.getByRole("button", { name: "Look up train" }).click();
  await expect(page.getByRole("heading", { name: data.data.train_name! })).toBeVisible();
  await page.clock.fastForward(1000);
  return calls;
}
test.beforeEach(async ({ page }) => {
  await page.clock.install({ time: new Date(instant) });
  await page.clock.pauseAt(new Date(instant));
});

test("public home starts with real lookup and keeps demos separate", async ({ page }) => {
  let calls = 0;
  await page.route("**/api/**", async (route) => { calls++; await route.fulfill({ json: {} }); });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Find your running train." })).toBeVisible();
  await expect(page.getByText("RAILRADAR DATA", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Passenger demo", exact: true })).toBeHidden();
  await page.locator("summary").click();
  await expect(page.getByRole("link", { name: "Passenger demo", exact: true })).toHaveAttribute("href", "/demo");
  await expect(page.getByRole("link", { name: "ETA experiment lab" })).toBeVisible();
  expect(calls).toBe(0);
});

test("destination, repeated stops and shared origin date stay exact without extra requests", async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(navigator, "clipboard", { value: { writeText: async () => {} } }));
  const calls = await openReport(page, report(), "");
  await page.getByLabel("Your destination station").selectOption("2:BBB");
  const card = page.getByRole("region", { name: "Your destination arrival" });
  await expect(card.getByText("About 30 min remaining")).toBeVisible();
  await expect(card.getByText("06 Oct 2026, 00:45", { exact: true })).toBeVisible();
  await expect(card.getByText(/15 min later/)).toBeVisible();
  await page.getByLabel("Your destination station").selectOption("3.5:BBB");
  await expect(card.getByText("About 1 hr 30 min remaining")).toBeVisible();
  await card.getByRole("button", { name: "Copy journey link" }).click();
  await expect(card.getByText(/Journey link copied/)).toBeVisible();
  const shared = new URL(await card.getByLabel("Journey link").inputValue());
  expect(shared.pathname).toBe("/");
  expect(shared.searchParams.get("date")).toBe("2026-10-06");
  expect(shared.searchParams.get("stop")).toBe("3.5:BBB");
  expect(calls).toHaveLength(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.goto(shared.href);
  await expect(page.getByLabel("Journey start date")).toHaveValue("2026-10-06");
  expect(calls).toHaveLength(1);
  await page.getByRole("button", { name: "Look up train" }).click();
  await expect(page.getByLabel("Your destination station")).toHaveValue("3.5:BBB");
});

test("blank dates pin India today and clipboard failure offers a copyable URL", async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(navigator, "clipboard", { value: { writeText: async () => { throw new Error("unavailable"); } } }));
  const calls: string[] = [];
  await page.route("**/api/live/trains/**", async (route) => { calls.push(route.request().url()); await route.fulfill({ json: report() }); });
  await page.goto("/?train=22222");
  await page.getByRole("button", { name: "Look up train" }).click();
  await page.getByLabel("Your destination station").selectOption("2:BBB");
  expect(new URL(calls[0]).searchParams.get("date")).toBe("2026-10-06");
  await expect(page.getByLabel("Journey start date")).toHaveValue("2026-10-06");
  await page.getByRole("button", { name: "Copy journey link" }).click();
  await expect(page.getByText(/Copy the link below/)).toBeVisible();
  await expect(page.getByLabel("Journey link")).toHaveValue(/date=2026-10-06/);
  await page.getByLabel("Train number", { exact: true }).fill("99999");
  await expect(page.getByRole("region", { name: "Your destination arrival" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Passenger test express" })).toHaveCount(0);
});

const cases: { name: string; change: (r: RailRadarResult) => void; text: RegExp }[] = [
  { name: "stale", change: r => { r.freshness = "stale"; }, text: /current arrival estimate cannot be confirmed/ },
  { name: "not live", change: r => { r.data.is_live = false; }, text: /current arrival estimate cannot be confirmed/ },
  { name: "fallback warning", change: r => { r.warning = "Provider unavailable"; }, text: /current arrival estimate cannot be confirmed/ },
  { name: "unknown freshness", change: r => { r.freshness = "unknown"; }, text: /current arrival estimate cannot be confirmed/ },
  { name: "cancelled train", change: r => { r.data.status = "cancelled"; }, text: /marks this service or stop as cancelled/ },
  { name: "skipped stop", change: r => { r.data.route[1].status = "skipped"; }, text: /marks this stop as skipped/ },
  { name: "passed stop", change: r => { r.data.route[1].status = "departed"; }, text: /already passed this stop/ },
  { name: "arrived stop", change: r => { r.data.route[1].status = "arrived"; }, text: /reports the train at this stop/ },
  { name: "unconfirmed halt", change: r => { r.data.route[1].is_halt = null; }, text: /passenger halt at this station is not confirmed/ },
  { name: "unknown stop status", change: r => { r.data.route[1].status = null; }, text: /countdown is unavailable/ },
  { name: "no arrival report", change: r => { r.data.route[1].reported_arrival = null; }, text: /No live arrival estimate was supplied/ },
  { name: "past estimate", change: r => { r.data.route[1].reported_arrival = "2026-10-05T18:40:00Z"; }, text: /arrival report is in the past/ },
];
for (const item of cases) test(`${item.name} cannot show a passenger countdown`, async ({ page }) => {
  const data = report(); item.change(data);
  await openReport(page, data);
  const card = page.getByRole("region", { name: "Your destination arrival" });
  await expect(card.getByText(item.text)).toBeVisible();
  await expect(card.locator(".arrival-countdown")).toHaveCount(0);
});

test("a loaded report ages out without polling the provider", async ({ page }) => {
  const calls = await openReport(page, report());
  await expect(page.locator(".arrival-countdown")).toBeVisible();
  await page.clock.fastForward(601000);
  await expect(page.locator(".arrival-countdown")).toHaveCount(0);
  await expect(page.getByText(/current arrival estimate cannot be confirmed/)).toBeVisible();
  expect(calls).toHaveLength(1);
});

test("unmatched shared stop never falls back silently to another station", async ({ page }) => {
  await openReport(page, report(), "&stop=99%3ABBB");
  await expect(page.getByText(/saved station could not be matched/)).toBeVisible();
  await expect(page.locator(".arrival-times")).toHaveCount(0);
  await page.getByLabel("Your destination station").selectOption("2:BBB");
  await expect(page.locator(".arrival-countdown")).toBeVisible();
});

test("editing during a request discards the old journey response", async ({ page }) => {
  let release!: () => void;
  let received!: () => void;
  const requested = new Promise<void>(resolve => { received = resolve; });
  const response = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/live/trains/**", async route => {
    received(); await response; await route.fulfill({ json: report() }).catch(() => {});
  });
  await page.goto("/?train=22222&date=2026-10-06&stop=2%3ABBB");
  await page.getByRole("button", { name: "Look up train" }).click();
  await requested;
  await page.getByLabel("Journey start date").fill("2026-10-05");
  release();
  await page.clock.fastForward(26000);
  await expect(page.getByRole("button", { name: "Look up train" })).toBeEnabled();
  await expect(page.getByRole("heading", { name: "Passenger test express" })).toHaveCount(0);
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
});
