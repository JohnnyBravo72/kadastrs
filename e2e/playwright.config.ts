// End-to-end test of the results view (PLAN.md §8.2), run in the official
// Playwright container against the api-e2e service (synthetic seed DB):
//   docker compose --profile e2e run --rm e2e      (docs/runbook.md)
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests",
  timeout: 90_000,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://api-e2e:8000",
    viewport: { width: 1366, height: 768 },
    acceptDownloads: true,
    locale: "lv-LV",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
