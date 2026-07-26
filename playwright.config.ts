import { defineConfig, devices } from "@playwright/test";

const apiUrl = "http://127.0.0.1:8100";
const webUrl = "http://127.0.0.1:3100";
const pythonCommand = process.env.E2E_PYTHON ?? "api/.venv/bin/python";
const reuseExistingServer = !process.env.CI;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: webUrl,
    locale: "zh-CN",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: [
        "APP_ENV=test",
        "EXPOSE_DEBUG_TOKENS=true",
        "AUTH_RATE_LIMIT_PER_MINUTE=1000",
        "RATE_LIMIT_PER_MINUTE=1000",
        "ADMIN_EMAILS=source-admin@offerpilot.test",
        `CORS_ORIGINS=${webUrl}`,
        `APP_URL=${webUrl}`,
        "PYTHONPATH=api",
        pythonCommand,
        "-m uvicorn app.main:app --host 127.0.0.1 --port 8100",
      ].join(" "),
      url: `${apiUrl}/health`,
      reuseExistingServer,
      timeout: 120_000,
    },
    {
      command: `NEXT_PUBLIC_API_URL=${apiUrl} pnpm exec next dev --hostname 127.0.0.1 --port 3100`,
      url: webUrl,
      reuseExistingServer,
      timeout: 120_000,
    },
  ],
});
