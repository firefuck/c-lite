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

import { app, BrowserWindow, dialog, Menu, shell } from "electron";
import type { RunningBackend } from "./backend-process.ts";
import { listProfiles, startBackend } from "./backend-process.ts";
import { DISPLAY_NAME } from "./brand.ts";
import { menuTemplate } from "./menu.ts";
import { decideNavigation } from "./window-policy.ts";

const DOCS_URL = "https://github.com/dragovics/clite#readme";

let backend: RunningBackend | null = null;
let window: BrowserWindow | null = null;
let profile = "";

/** The standard application menu. Built once, before the first window. */
function installMenu(): void {
  Menu.setApplicationMenu(
    Menu.buildFromTemplate(
      menuTemplate(DISPLAY_NAME, process.platform, {
        openExternal: (url) => void shell.openExternal(url),
        docsUrl: DOCS_URL,
      }),
    ),
  );
}

function createWindow(running: RunningBackend): BrowserWindow {
  const created = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 720,
    minHeight: 480,
    title: profile ? `${DISPLAY_NAME} — ${profile}` : DISPLAY_NAME,
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

/** `--profile NAME` on the command line, if it was given. */
function requestedProfile(): string | null {
  const joined = process.argv.find((arg) => arg.startsWith("--profile="));
  if (joined) return joined.slice("--profile=".length);
  const index = process.argv.indexOf("--profile");
  const next = index === -1 ? undefined : process.argv[index + 1];
  return next ? next : null;
}

/** Either a profile to run on (or null for the default), or the user backed out. */
type ProfileChoice = { cancelled: boolean; profile: string | null };

/**
 * Which profile to run on.
 *
 * One backend serves one profile, so this is a decision made once, before the backend exists.
 * `--profile` settles it; with more than one profile on the machine the user is asked, because
 * silently opening somebody else's conversations would be worse than a dialog. Nothing to
 * choose (or no CLI to ask) means the default profile.
 */
async function chooseProfile(): Promise<ProfileChoice> {
  const asked = requestedProfile();
  if (asked) return { cancelled: false, profile: asked };
  let names: string[];
  try {
    names = await listProfiles();
  } catch {
    return { cancelled: false, profile: null }; // no CLI yet: startBackend will say so properly
  }
  if (names.length < 2) return { cancelled: false, profile: null };
  const { response } = await dialog.showMessageBox({
    type: "question",
    title: DISPLAY_NAME,
    message: "Which profile should this window open?",
    detail: "Each profile has its own config, keys, memory and sessions.",
    buttons: [...names, "Cancel"],
    defaultId: 0,
    cancelId: names.length,
  });
  if (response === names.length) return { cancelled: true, profile: null };
  return { cancelled: false, profile: names[response] ?? null };
}

async function launch(): Promise<void> {
  const choice = await chooseProfile();
  if (choice.cancelled) {
    app.quit();
    return;
  }
  profile = choice.profile ?? "";
  try {
    backend = await startBackend({ profile: choice.profile });
  } catch (error) {
    dialog.showErrorBox(
      `${DISPLAY_NAME} could not start`,
      `${error instanceof Error ? error.message : String(error)}\n\nCheck that the \`clite\` command works in a terminal (try \`clite doctor\`).`,
    );
    app.quit();
    return;
  }
  backend.process.once("exit", () => {
    // The backend died under us: say so instead of leaving a dead window.
    if (window) {
      dialog.showErrorBox(DISPLAY_NAME, "The backend stopped unexpectedly. The app will close.");
    }
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
  app.whenReady().then(() => {
    installMenu();
    return launch();
  });
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
