import { expect, test } from "@playwright/test";
import { arrivals, iso, mockDemo, NOW, snapshot } from "./fixtures";

for (const path of ["/", "/station/NDLS", "/control"]) {
  test(`renders ${path} without page errors or page overflow`, async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await mockDemo(page);
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(
      page.getByText("SIMULATED DATA", { exact: true }),
    ).toBeVisible();
    await expect(page.getByText(/Loading train data/)).toHaveCount(0);
    await expect
      .poll(() =>
        page
          .locator(
            ".train-option,.arrivals-table tbody tr,.fleet-table tbody tr",
          )
          .count(),
      )
      .toBeGreaterThan(0);
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth <=
          document.documentElement.clientWidth,
      ),
    ).toBe(true);
    expect(errors).toEqual([]);
  });
}

test("passenger selects trains and updates estimates and map over WebSocket", async ({
  page,
}) => {
  const sockets = await mockDemo(page);
  await page.goto("/");
  await expect(page.locator(".hero-time")).toContainText("00:17");
  await expect(page.locator(".next-stop .badge")).toContainText("2 min late");
  await expect(
    page.getByRole("region", { name: "Route map for train 12301" }),
  ).toBeVisible();
  const marker = page.getByRole("button", { name: /12301 Kolkata/i });
  const before = await marker.getAttribute("style");
  sockets
    .get("12301")!
    .at(-1)!
    .send(JSON.stringify({ type: "eta_update", data: snapshot("12301", 1) }));
  await expect(page.locator(".hero-time")).toContainText("00:18");
  await expect.poll(() => marker.getAttribute("style")).not.toBe(before);
  await page.getByText("How this estimate is calculated").click();
  await expect(page.getByText("Model starting value")).toBeVisible();
  await page.getByLabel("Train name or number").fill("12621");
  await page.getByRole("button", { name: /12621/ }).click();
  await expect(page.locator(".journey-overview h2")).toHaveText(
    "Tamil Nadu Exp",
  );
  await expect(
    page.getByRole("region", { name: "Route map for train 12621" }),
  ).toBeVisible();
  await expect(page).toHaveURL(/train=12621/);
});

test("socket reconnects and late REST snapshots cannot replace newer predictions", async ({
  page,
}) => {
  const sockets = await mockDemo(page);
  await page.goto("/");
  await expect(page.locator(".hero-time")).toContainText("00:17");
  sockets
    .get("12301")!
    .at(-1)!
    .send(JSON.stringify({ type: "eta_update", data: snapshot("12301", 2) }));
  await expect(page.locator(".hero-time")).toContainText("00:19");
  await sockets.get("12301")!.at(-1)!.close();
  await page.clock.fastForward(11000);
  await expect.poll(() => sockets.get("12301")!.length).toBeGreaterThan(1);
  await expect(page.locator(".hero-time")).toContainText("00:19");
});

test("stale and missing telemetry never look like fresh predictions", async ({
  page,
}) => {
  const sockets = await mockDemo(page);
  await page.goto("/");
  await expect(page.locator(".hero-time")).toBeVisible();
  await page.clock.fastForward(31000);
  await expect(
    page.getByRole("status").filter({ hasText: "signal is stale" }),
  ).toBeVisible();
  const noData = {
    ...snapshot("12301"),
    generated_at: iso(NOW + 40000),
    status: "no_data",
    position: null,
    position_id: null,
    journey_id: null,
    as_of: null,
    stations: [],
    current_delay_minutes: null,
    active_events: [],
    ml_status: "no_next_station",
  };
  sockets
    .get("12301")!
    .at(-1)!
    .send(JSON.stringify({ type: "eta_update", data: noData }));
  await expect(
    page.getByRole("heading", { name: "Waiting for departure" }),
  ).toBeVisible();
  await expect(page.locator(".hero-time")).toHaveCount(0);
  await expect(page.getByRole("progressbar")).toHaveAttribute(
    "aria-valuenow",
    "0",
  );
});

test("model fallback preserves baseline without an ML badge", async ({
  page,
}) => {
  const sockets = await mockDemo(page);
  await page.goto("/");
  await expect(page.locator(".hero-time")).toBeVisible();
  const eta = snapshot("12301", 1);
  eta.ml_status = "unavailable";
  eta.stations[0] = {
    ...eta.stations[0],
    ml_eta: null,
    eta_ml_minutes: null,
    explanation: null,
    prediction_method: "current_delay_carryover",
    model_version: null,
    predicted_delay_minutes: null,
    eta: eta.stations[0].baseline_eta,
  };
  sockets
    .get("12301")!
    .at(-1)!
    .send(JSON.stringify({ type: "eta_update", data: eta }));
  await expect(
    page
      .locator(".next-arrival")
      .getByText("Carryover estimate", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".next-arrival del")).toHaveCount(0);
});

test("station switches, displays overnight dates, and refreshes automatically", async ({
  page,
}) => {
  await mockDemo(page);
  await page.goto("/station/NDLS");
  await expect(page.getByLabel("Display station")).toHaveValue("NDLS");
  await page.getByLabel("Display station").selectOption("DKAE");
  await expect(page).toHaveURL(/station\/DKAE/);
  await expect(page.locator(".arrivals-table tbody tr")).toHaveCount(1);
  await expect(page.locator(".arrivals-table")).toContainText("21 Sep");
  await expect(page.getByLabel("Platform unavailable")).toBeVisible();
  await page.route("**/api/stations/DKAE/arrivals", (route) =>
    route.fulfill({ json: { ...arrivals("DKAE"), arrivals: [] } }),
  );
  await page.clock.fastForward(11000);
  await expect(
    page.getByRole("heading", { name: "No active arrivals" }),
  ).toBeVisible();
});

test("station recovers after a request timeout", async ({ page }) => {
  await mockDemo(page);
  let fail = true;
  await page.route("**/api/stations/NDLS/arrivals", async (route) => {
    if (fail)
      return; // Leave this request pending until the client aborts it.
    else await route.fulfill({ json: arrivals("NDLS") });
  });
  const networkLoaded = page.waitForResponse("**/api/network");
  await page.goto("/station/NDLS");
  await (await networkLoaded).finished();
  await expect(
    page.locator(".view-skeleton").getByRole("status"),
  ).toBeVisible();
  // Run timers in order so only the deliberately stalled arrivals request times out.
  await page.clock.runFor(11000);
  await expect(page.getByRole("main").getByRole("alert")).toBeVisible();
  fail = false;
  await page.clock.fastForward(11000);
  await expect(page.locator(".arrivals-table tbody tr")).toHaveCount(3);
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
});

test("control sorts, filters, compares predictions, and opens journey history and events", async ({
  page,
}) => {
  const sockets = await mockDemo(page);
  await page.goto("/control");
  await expect(page.locator(".fleet-table tbody tr")).toHaveCount(6);
  await expect(page.locator(".fleet-table tbody tr").first()).toContainText(
    "12622",
  );
  await page.getByRole("button", { name: "Current delay" }).click();
  await expect(page.locator(".fleet-table tbody tr").first()).toContainText(
    "12301",
  );
  sockets
    .get("12301")!
    .at(-1)!
    .send(JSON.stringify({ type: "eta_update", data: snapshot("12301", 1) }));
  await expect(
    page.locator(".fleet-table tbody tr").filter({ hasText: "12301" }),
  ).toContainText("+1.0 min");
  await page.getByRole("button", { name: "Major delays", exact: true }).click();
  await expect(page.locator(".fleet-table tbody tr")).toHaveCount(2);
  await page.getByRole("button", { name: "All trains" }).click();
  await expect(page.locator(".fleet-table tbody tr")).toHaveCount(6);
  await page.getByRole("button", { name: "View train 12301" }).click();
  const detail = page.getByRole("dialog");
  await expect(detail).toBeVisible();
  await expect(detail.getByText("Synthetic weather test event")).toBeVisible();
  await expect(
    detail.getByRole("heading", { name: "Recorded history" }),
  ).toBeVisible();
  await expect(detail.locator(".history-table tbody tr")).toHaveCount(1);
  await page.keyboard.press("Escape");
  await expect(detail).toHaveCount(0);
});

test("API errors are visible and retry recovers the network", async ({
  page,
}) => {
  await mockDemo(page);
  await page.route("**/api/network", (route) =>
    route.fulfill({ status: 503, json: { detail: "unavailable" } }),
  );
  await page.goto("/");
  await expect(page.getByRole("main").getByRole("alert")).toBeVisible();
  await page.unroute("**/api/network");
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("button", { name: /12301/ })).toBeVisible();
});

test("journey history pagination retries without losing or duplicating earlier observations", async ({
  page,
}) => {
  await mockDemo(page);
  let secondPageAttempts = 0;
  await page.route("**/api/trains/12301/history?**", (route) => {
    const url = new URL(route.request().url());
    expect(url.searchParams.get("journey_id")).toBe("journey-12301");
    if (url.searchParams.has("after") && secondPageAttempts++ === 0)
      return route.fulfill({ status: 503, json: { detail: "unavailable" } });
    return route.fulfill({
      json: {
        train_number: "12301",
        journey_id: "journey-12301",
        positions: [
          snapshot("12301", url.searchParams.has("after") ? 1 : 0).position,
        ],
        next_after: url.searchParams.has("after") ? null : "page-one-cursor",
      },
    });
  });
  await page.goto("/control");
  await page.getByRole("button", { name: "View train 12301" }).click();
  const detail = page.getByRole("dialog");
  await expect(detail.locator(".history-table tbody tr")).toHaveCount(1);
  await detail
    .getByRole("button", { name: "Load next 100 observations" })
    .click();
  await expect(detail.getByRole("alert")).toContainText(
    "Journey history could not be loaded",
  );
  await detail
    .getByRole("button", { name: "Load next 100 observations" })
    .click();
  await expect(detail.locator(".history-table tbody tr")).toHaveCount(2);
  await expect(detail.getByRole("alert")).toHaveCount(0);
  await expect(
    detail.getByRole("button", { name: "Load next 100 observations" }),
  ).toHaveCount(0);
});

test("fleet comparisons reset on a new journey and missing telemetry has neutral counts", async ({
  page,
}) => {
  const sockets = await mockDemo(page);
  await page.goto("/control");
  await expect(page.locator(".fleet-table tbody tr")).toHaveCount(6);
  const row = page
    .locator(".fleet-table tbody tr")
    .filter({ hasText: "12301" });
  sockets
    .get("12301")!
    .at(-1)!
    .send(JSON.stringify({ type: "eta_update", data: snapshot("12301", 1) }));
  await expect(row).toContainText("+1.0 min");
  const changed = snapshot("12301", 2);
  changed.journey_id = "new-journey";
  changed.position!.journey_id = "new-journey";
  sockets
    .get("12301")!
    .at(-1)!
    .send(JSON.stringify({ type: "eta_update", data: changed }));
  await expect(row).toContainText("Awaiting comparison");
  await page.clock.fastForward(41000);
  await expect(
    page
      .locator(".stat-card")
      .filter({ hasText: "Active trains" })
      .locator("strong"),
  ).toHaveText("00");
});

test("passenger search recovers from no matches and preserves keyboard selection on reload", async ({
  page,
}) => {
  await mockDemo(page);
  await page.goto("/");
  const search = page.getByLabel("Train name or number");
  await search.fill("not a seeded service");
  await expect(
    page.getByText("No matching train in this six-train demo."),
  ).toBeVisible();
  await expect(page.locator(".train-option")).toHaveCount(0);
  await search.fill("aug kr");
  const train = page
    .locator(".train-options")
    .getByRole("button", { name: /12953/ });
  await train.press("Enter");
  await expect(train).toHaveAttribute("aria-pressed", "true");
  await expect(page).toHaveURL(/train=12953/);
  await page.reload();
  await expect(
    page.locator(".train-options").getByRole("button", { name: /12953/ }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.getByRole("region", { name: "Route map for train 12953" }),
  ).toBeVisible();
  await expect(page.locator(".journey-overview h2")).toHaveText(
    "Aug Kr Raj Exp",
  );
});

test("unknown station displays a recoverable error and accepts a valid station", async ({
  page,
}) => {
  await mockDemo(page);
  await page.route("**/api/stations/FAKE/arrivals", (route) =>
    route.fulfill({ status: 404, json: { detail: "Not found" } }),
  );
  await page.goto("/station/FAKE");
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "Not found",
  );
  await expect(page.locator(".view-skeleton")).toHaveCount(0);
  await page.getByLabel("Display station").selectOption("NDLS");
  await expect(page).toHaveURL(/station\/NDLS/);
  await expect(page.locator(".arrivals-table tbody tr")).toHaveCount(3);
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
});

test("control detail supports keyboard opening, Escape, and focus restoration", async ({
  page,
}) => {
  await mockDemo(page);
  await page.goto("/control");
  const opener = page.getByRole("button", { name: "View train 12301" });
  await opener.press("Enter");
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Close train detail" }),
  ).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(opener).toBeFocused();
});
