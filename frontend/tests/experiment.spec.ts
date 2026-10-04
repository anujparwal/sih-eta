import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";
import type { Experiment } from "../lib/experiment";

function output(congested = false): Experiment {
  const reference = { method: "xgboost" as const, predicted_delay_minutes: 10, reason: "model_ready" as const, explanation: null };
  return {
    source: "hypothetical_synthetic", inputs: { current_delay_minutes: 15, distance_km: 20, elapsed_minutes: 15, event_severity: 3, nearby_trains: congested ? 3 : 0 },
    baseline_delay_minutes: 15, reference,
    scenario: congested ? { method: "current_delay_carryover", predicted_delay_minutes: 15, reason: "outside_training_domain", explanation: null } : {
      method: "xgboost", predicted_delay_minutes: 20, reason: "model_ready", explanation: {
        base_value_minutes: 2, raw_residual_minutes: 5, current_delay_minutes: 15, clipping_adjustment_minutes: 0, predicted_delay_minutes: 20,
        contributions: [{ feature: "active_event_max_severity", value: 3, contribution_minutes: 3 }],
      },
    },
    assumption: "Fixed Thursday 12:00 IST.", limitation: "Synthetic model sensitivity, not a real ETA.",
    evidence: { model_version: "test-only-model", model_sha256: "a".repeat(64), baseline_mae_minutes: 33.940723, model_mae_minutes: 5.759419, baseline_rmse_minutes: 45.097967, model_rmse_minutes: 8.013165, training_journeys: 66, validation_journeys: 18, test_journeys: 24, test_rows: 26146 },
  };
}

test("lab runs on demand, exports evidence, clears edited results and demonstrates fallback", async ({ page }) => {
  const calls: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/demo/scenario?**", async (route) => {
    calls.push(route.request().url());
    await route.fulfill({ json: output(new URL(route.request().url()).searchParams.get("nearby_trains") === "3") });
  });
  await page.goto("/lab");
  await expect(page.getByText("HYPOTHETICAL INPUTS", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "What changes the forecast?" })).toBeVisible();
  expect(calls).toHaveLength(0);
  await page.getByRole("button", { name: "Severe disruption", exact: true }).click();
  await page.getByRole("button", { name: "Run experiment", exact: true }).click();
  await expect(page.getByText("Selected scenario: XGBoost model prediction.")).toBeVisible();
  expect(new URL(calls[0]).searchParams.get("event_severity")).toBe("3");
  await expect(page.getByText("+10.00 min", { exact: true })).toBeVisible();
  await expect(page.getByText("5.759 min", { exact: true })).toBeVisible();
  await expect(page.getByText(/Real railway accuracy is not yet measured/)).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download experiment evidence (JSON)" }).click();
  const download = await downloadPromise;
  const exported = JSON.parse(await readFile((await download.path())!, "utf8"));
  expect(exported.source).toBe("hypothetical_synthetic");
  expect(exported.problem_statement).toBe("SIH26028");
  expect(exported.inputs.event_severity).toBe(3);
  expect(exported.evidence.model_version).toBe("test-only-model");
  await page.getByLabel("Current delay (min)").fill("21");
  await expect(page.getByRole("button", { name: "Download experiment evidence (JSON)" })).toHaveCount(0);
  await expect(page.getByText("Selected scenario: XGBoost model prediction.")).toHaveCount(0);
  await page.getByRole("button", { name: "Unseen congestion", exact: true }).click();
  await page.getByRole("button", { name: "Run experiment", exact: true }).click();
  await expect(page.getByText(/Baseline fallback: these inputs exceed/)).toBeVisible();
  await expect(page.getByText("+10.00 min", { exact: true })).toHaveCount(0);
  await expect(page.getByText("3. Explain the model output", { exact: true })).toHaveCount(0);
  expect(calls).toHaveLength(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  expect(errors).toEqual([]);
});

test("lab shows unavailable evidence when the model is disabled", async ({ page }) => {
  const result = output(true);
  result.evidence = null;
  result.reference = result.scenario = { method: "current_delay_carryover", predicted_delay_minutes: 15, reason: "model_unavailable", explanation: null };
  await page.route("**/api/demo/scenario?**", (route) => route.fulfill({ json: result }));
  await page.goto("/lab");
  await page.getByRole("button", { name: "Run experiment", exact: true }).click();
  await expect(page.getByText("Baseline fallback: the model is unavailable.")).toBeVisible();
  await expect(page.getByText(/Evidence is unavailable if the model cannot be loaded/)).toBeVisible();
  await expect(page.getByText("5.759 min", { exact: true })).toHaveCount(0);
});

test("lab handles API failure and recovery without publishing stale results", async ({ page }) => {
  let fail = true;
  await page.route("**/api/demo/scenario?**", (route) => fail ? route.fulfill({ status: 503 }) : route.fulfill({ json: output() }));
  await page.goto("/lab");
  await page.getByRole("button", { name: "Run experiment", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Experiment unavailable");
  await expect(page.getByRole("button", { name: "Download experiment evidence (JSON)" })).toHaveCount(0);
  fail = false;
  await page.getByRole("button", { name: "Run experiment", exact: true }).click();
  await expect(page.getByText("Selected scenario: XGBoost model prediction.")).toBeVisible();
});
