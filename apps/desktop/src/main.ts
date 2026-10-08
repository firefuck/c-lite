// Electron main process.
//
// The wiring here is covered by test/smoke.test.ts: it launches this app with the mock
// provider, reads the answer out of the window, and checks that closing the app stops the
// backend. The logic it leans on lives outside (backend-process.ts, window-policy.ts) so it
// can be tested without Electron.
//
// Three parties: this process owns the backend's lifetime and the window; the renderer is the
// dashboard page served by the backend; the backend is the Python process. The renderer gets
// no Node access: it talks to the backend over the WebSocket like any browser would.

import { join } from "node:path";

import { BrowserWindow, app, dialog, shell } from "electron";

import { startBackend } from "./backend-process.ts";
import type { RunningBackend } from "./backend-process.ts";
import { decideNavigation } from "./window-policy.ts";

let backend: RunningBackend | null = null;
let window: BrowserWindow | null = null;

function createWindow(running: RunningBackend): BrowserWindow {
  const created = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 720,
    minHeight: 480,
    title: "C-lite",
    webPreferences: {
      preload: join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  const route = (target: string): boolean => {
    const decision = decideNavigation(target, running.origin);
    if (decision === "external") void shell.openExternal(target);
    return decision === "allow";
  };
  created.webContents.on("will-navigate", (event, target) => {
    // This also catches a file dropped on the page: Chromium would otherwise navigate to
    // `file://…` and replace the dashboard. Refusing it leaves the drop to the page, which
    // turns it into an attachment.
    if (!route(target)) event.preventDefault();
  });
  created.webContents.setWindowOpenHandler(({ url }) => {
    route(url);
    return { action: "deny" }; // never a second window inside the app
  });

  void created.loadURL(running.url);
  created.on("closed", () => {
    window = null;
  });
  return created;
}

async function launch(): Promise<void> {
  try {
    backend = await startBackend();
  } catch (error) {
    dialog.showErrorBox(
      "C-lite could not start",
      `${error instanceof Error ? error.message : String(error)}\n\nCheck that the \`clite\` command works in a terminal (try \`clite doctor\`).`,
    );
    app.quit();
    return;
  }
  backend.process.once("exit", () => {
    // The backend died under us: say so instead of leaving a dead window.
    if (window) dialog.showErrorBox("C-lite", "The backend stopped unexpectedly. The app will close.");
    app.quit();
  });
  window = createWindow(backend);
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (window) {
      if (window.isMinimized()) window.restore();
      window.focus();
    }
  });
  app.whenReady().then(launch);
  app.on("activate", () => {
    if (!window && backend) window = createWindow(backend);
  });
  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });
  app.on("before-quit", () => {
    const running = backend;
    backend = null;
    if (running) {
      running.process.removeAllListeners("exit");
      void running.stop();
    }
  });
}
