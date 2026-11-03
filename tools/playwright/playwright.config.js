import { defineConfig } from "@playwright/test";

const PORT = process.env.QA_PORT || "8126";
const isWindows = process.platform === "win32";
const python = process.env.QA_PYTHON || (isWindows ? "../../backend/venv/Scripts/python.exe" : "../../backend/venv/bin/python");

export default defineConfig({
  testDir: "./tests",
  workers: 1,
  timeout: 60000,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    channel: process.env.QA_BROWSER_CHANNEL || "msedge",
    serviceWorkers: "block",
  },
  webServer: {
    command: `"${python}" start_server.py`,
    url: `http://127.0.0.1:${PORT}/health`,
    timeout: 180000,
    reuseExistingServer: false,
  },
});
