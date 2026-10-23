import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  outputDir: "../.tmp/frontend/playwright-results",
  fullyParallel: true,
  use: {
    baseURL: "http://127.0.0.1:3030",
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure",
  },
  webServer: {
    command: "node tests/server.mjs",
    env: { PORT: "3030", HOSTNAME: "127.0.0.1" },
    url: "http://127.0.0.1:3030",
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
