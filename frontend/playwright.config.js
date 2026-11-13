import { defineConfig } from "@playwright/test";

const WEB = process.env.E2E_WEB_URL ?? "http://localhost:4173";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: { baseURL: WEB, trace: "retain-on-failure" },
  // The API (migrated Postgres + seeded content) is started by the caller / CI job.
  webServer: {
    command: "npm run build && npx vite preview --port 4173 --strictPort",
    url: WEB,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
