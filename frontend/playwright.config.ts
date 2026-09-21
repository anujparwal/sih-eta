import { defineConfig, devices } from "@playwright/test";
const live = process.env.LIVE_UI === "1";
export default defineConfig({
  testDir: "./tests",
  testMatch: live ? "live.spec.ts" : "ui.spec.ts",
  fullyParallel: !live,
  workers: live ? 1 : 2,
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  timeout: 30000,
  use: {
    baseURL:
      process.env.UI_BASE_URL ||
      (live ? "http://127.0.0.1:3000" : "http://127.0.0.1:3100"),
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: live
    ? [
        {
          name: "live-chromium",
          use: {
            ...devices["Desktop Chrome"],
            viewport: { width: 1440, height: 1000 },
          },
        },
      ]
    : [
        {
          name: "desktop",
          use: {
            ...devices["Desktop Chrome"],
            viewport: { width: 1440, height: 1000 },
          },
        },
        {
          name: "mobile",
          use: { ...devices["iPhone 13"], defaultBrowserType: "chromium" },
        },
      ],
  webServer: live
    ? undefined
    : {
        command: "node scripts/start-test-server.mjs",
        url: "http://127.0.0.1:3100",
        reuseExistingServer: !process.env.CI,
        timeout: 60000,
      },
});
