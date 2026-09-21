import { expect, test } from "@playwright/test";
import { arrivals, iso, mockDemo, NOW, snapshot } from "./fixtures";

// These regressions exercise the failure states found in the Phase 7 review.
for (const path of ["/", "/station/NDLS", "/control"]) {
  test(`network failure on ${path} ends loading and offers recovery`, async ({
    page,
  }) => {
    await mockDemo(page);
    await page.route("**/api/network", (route) =>
      route.fulfill({ status: 503, json: { detail: "unavailable" } }),
    );
    await page.goto(path);
    await expect(page.getByRole("main").getByRole("alert")).toBeVisible();
    await expect(
      page.locator(".map-loading,.map-panel .loading-state"),
    ).toHaveCount(0);
    await page.unroute("**/api/network");
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
  });
  test(`initial ${path} loads skeletons without inventing operational state`, async ({
    page,
  }) => {
    await mockDemo(page);
    await page.route("**/api/**", () => {});
    await page.routeWebSocket(/\/ws\/trains\//, () => {});
    await page.goto(path);
    await expect(page.locator(".view-skeleton")).toBeVisible();
    await expect(
      page.getByText("Waiting for departure", { exact: true }),
    ).toHaveCount(0);
    await expect(
      page.locator(".view-skeleton .skeleton").first(),
    ).toBeVisible();
  });
}

test("unknown train URL stops loading and lets the passenger pick a seeded train", async ({
  page,
}) => {
  await mockDemo(page);
  await page.route("**/api/trains/99999/eta", (r) =>
    r.fulfill({ status: 404, json: { detail: "unknown" } }),
  );
  await page.routeWebSocket(/\/ws\/trains\/99999/, () => {});
  await page.goto("/?train=99999");
  await expect(
    page.getByRole("heading", { name: "Train not found" }),
  ).toBeVisible();
  await expect(page.locator(".loading-state,.map-loading")).toHaveCount(0);
  await page.getByRole("button", { name: /12301/ }).click();
  await expect(page.locator(".hero-time")).toBeVisible();
});

test("ETA failure is not described as a train waiting to depart", async ({
  page,
}) => {
  await mockDemo(page);
  await page.route("**/api/trains/12301/eta", (r) =>
    r.fulfill({ status: 503, json: { detail: "unavailable" } }),
  );
  await page.routeWebSocket(/\/ws\/trains\/12301/, () => {});
  await page.goto("/");
  await expect(page.getByRole("main").getByRole("alert")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Arrival data unavailable" }),
  ).toBeVisible();
  await expect(
    page.getByText("Waiting for departure", { exact: true }),
  ).toHaveCount(0);
});

test("control exposes individual prediction failures even when fleet positions work", async ({
  page,
}) => {
  await mockDemo(page);
  await page.route("**/api/trains/12301/eta", (r) =>
    r.fulfill({ status: 503, json: { detail: "unavailable" } }),
  );
  await page.routeWebSocket(/\/ws\/trains\/12301/, () => {});
  await page.goto("/control");
  await expect(page.locator(".fleet-table tbody tr")).toHaveCount(6);
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "12301",
  );
  await page.unroute("**/api/trains/12301/eta");
  await page.clock.fastForward(11000);
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
});

test("delay labels and colors agree at zero and the 15-minute boundary", async ({
  page,
}) => {
  const sockets = await mockDemo(page);
  await page.goto("/control");
  await expect(page.locator(".fleet-table tbody tr")).toHaveCount(6);
  const row = page
    .locator(".fleet-table tbody tr")
    .filter({ hasText: "12301" });
  for (const [revision, delay, color, label] of [
    [1, 0, "good", "On time"],
    [2, 14.99, "warn", "14.9 min late"],
    [3, 15, "bad", "15 min late"],
  ] as const) {
    const eta = snapshot("12301", revision);
    eta.position!.delay_minutes = delay;
    eta.current_delay_minutes = delay;
    sockets
      .get("12301")!
      .at(-1)!
      .send(JSON.stringify({ type: "eta_update", data: eta }));
    await expect(row.locator(".badge")).toHaveClass(`badge ${color}`);
    await expect(row.locator(".badge")).toHaveText(label);
  }
});

test("a server that opens then rejects WebSockets never claims live updates", async ({
  page,
}) => {
  await mockDemo(page);
  let connections = 0;
  await page.routeWebSocket(/\/ws\/trains\/12301/, (socket) => {
    connections++;
    socket.send(
      JSON.stringify({
        type: "error",
        code: 503,
        detail: "Realtime store unavailable",
      }),
    );
    socket.close({ code: 1011 });
  });
  await page.goto("/");
  await expect(page.locator(".hero-time")).toBeVisible();
  await page.clock.runFor(7500);
  expect(connections).toBeLessThanOrEqual(4);
  await expect(page.getByText("Live updates", { exact: true })).toHaveCount(0);
});

test("map markers survive clock renders and telemetry updates", async ({
  page,
}) => {
  const sockets = await mockDemo(page);
  await page.goto("/control");
  const marker = page.getByRole("button", { name: /12301 Kolkata/ });
  await expect(marker).toBeVisible();
  const original = await marker.elementHandle();
  await page.clock.fastForward(2000);
  expect(await original!.evaluate((e) => e.isConnected)).toBe(true);
  sockets
    .get("12301")!
    .at(-1)!
    .send(JSON.stringify({ type: "eta_update", data: snapshot("12301", 1) }));
  await expect(
    page.locator(".fleet-table tbody tr").filter({ hasText: "12301" }),
  ).toContainText("+1.0 min");
  expect(await original!.evaluate((e) => e.isConnected)).toBe(true);
});

test("all main flows remain console-error free through client navigation", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  await mockDemo(page);
  await page.goto("/");
  await page.getByLabel("Train name or number").fill("12621");
  await page.getByRole("button", { name: /12621/ }).click();
  await page.locator(".next-station-name").click();
  await expect(page).toHaveURL(/station\/BZA/);
  await expect(page.locator(".arrivals-table tbody tr")).toHaveCount(
    arrivals("BZA").arrivals.length,
  );
  await page.getByRole("link", { name: "Control room", exact: true }).click();
  await page.getByRole("button", { name: "View train 12621" }).click();
  await expect(
    page.getByRole("dialog").locator(".history-table tbody tr"),
  ).toHaveCount(1);
  await page.getByRole("button", { name: "Close train detail" }).click();
  expect(errors).toEqual([]);
});

test("fleet failure shows unavailable counts and recovers on retry", async ({
  page,
}) => {
  await mockDemo(page);
  await page.route("**/api/control/fleet-status", (r) =>
    r.fulfill({ status: 503, json: { detail: "unavailable" } }),
  );
  await page.goto("/control");
  await expect(page.getByRole("main").getByRole("alert")).toBeVisible();
  await expect(page.locator(".stat-card strong")).toHaveText([
    "—",
    "—",
    "—",
    "—",
  ]);
  await expect(page.locator(".network-health dd")).toHaveText([
    "—",
    "—",
    "—",
    "—",
  ]);
  await page.unroute("**/api/control/fleet-status");
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.locator(".fleet-table tbody tr")).toHaveCount(6);
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
});

test("station retains stale arrivals during an outage and recovers", async ({
  page,
}) => {
  await mockDemo(page);
  await page.goto("/station/NDLS");
  await expect(page.locator(".arrivals-table tbody tr")).toHaveCount(3);
  await page.route("**/api/stations/NDLS/arrivals", (r) =>
    r.fulfill({ status: 503, json: { detail: "unavailable" } }),
  );
  await page.clock.fastForward(11000);
  await expect(page.getByRole("main").getByRole("alert")).toBeVisible();
  await page.clock.fastForward(21000);
  await expect(page.locator(".arrivals-table .badge.neutral")).toHaveCount(3);
  await expect(page.locator(".arrivals-table tbody tr")).toHaveCount(3);
  await page.unroute("**/api/stations/NDLS/arrivals");
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
});

test("journey history API error is visible and retry restores observations", async ({
  page,
}) => {
  await mockDemo(page);
  await page.route("**/api/trains/12301/history?*", (r) =>
    r.fulfill({ status: 503, json: { detail: "unavailable" } }),
  );
  await page.goto("/control");
  await page.getByRole("button", { name: "View train 12301" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("alert")).toContainText(
    "Journey history could not be loaded",
  );
  await page.unroute("**/api/trains/12301/history?*");
  await dialog.getByRole("button", { name: "Try again" }).click();
  await expect(dialog.locator(".history-table tbody tr")).toHaveCount(1);
  await expect(dialog.getByRole("alert")).toHaveCount(0);
});

test("total feed outage preserves the last snapshot, marks stale, then reconnects", async ({
  page,
}) => {
  const sockets = await mockDemo(page);
  await page.goto("/");
  await expect(page.getByText("Live updates", { exact: true })).toBeVisible();
  await page.route("**/api/trains/12301/eta", (r) =>
    r.fulfill({ status: 503, json: { detail: "unavailable" } }),
  );
  await page.routeWebSocket(/\/ws\/trains\/12301/, (socket) => socket.close());
  sockets.get("12301")!.at(-1)!.close();
  await page.clock.fastForward(11000);
  await expect(page.getByRole("main").getByRole("alert")).toBeVisible();
  await page.clock.fastForward(21000);
  await expect(
    page.getByText("Stale signal", { exact: true }).first(),
  ).toBeVisible();
  await expect(page.locator(".hero-time")).toBeVisible();
  await page.unroute("**/api/trains/12301/eta");
  await page.routeWebSocket(/\/ws\/trains\/12301/, (socket) => {
    const data = snapshot("12301", 8);
    data.generated_at = iso(NOW + 40000);
    socket.send(JSON.stringify({ type: "eta_update", data }));
  });
  await page.clock.runFor(11000);
  await expect(page.getByText("Live updates", { exact: true })).toBeVisible();
  await expect(page.getByText("Stale signal", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
});

for (const width of [320, 650, 768, 1024]) {
  test(`all views and the detail dialog fit a ${width}px screen`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await mockDemo(page);
    for (const path of ["/", "/station/NDLS", "/control"]) {
      await page.goto(path);
      await expect(page.locator(".view-skeleton")).toHaveCount(0);
      await expect(
        page.locator(".hero-time,.arrivals-table,.fleet-table"),
      ).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
      ).toBe(true);
    }
    await page.getByRole("button", { name: "View train 12301" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.locator(".history-table tbody tr")).toHaveCount(1);
    const bounds = await dialog.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
    expect(bounds!.height).toBeLessThanOrEqual(900);
    await page.getByRole("button", { name: "Close train detail" }).click();
    await expect(dialog).toHaveCount(0);
  });
}

test("narrow detail stays inside the page when scrollbars consume width", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 900 });
  await mockDemo(page);
  await page.goto("/control");
  // Reserve classic scrollbar space, as in the desktop app's embedded browser.
  await page.addStyleTag({ content: "html { scrollbar-gutter: stable; }" });
  await page.getByRole("button", { name: "View train 12301" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.locator(".history-table tbody tr")).toHaveCount(1);
  const bounds = await dialog.boundingBox();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(
    await page.evaluate(() => document.documentElement.clientWidth),
  );
});
