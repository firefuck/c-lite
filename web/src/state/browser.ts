// The Platform the dashboard runs on in a browser (and in the desktop app's window).

import { WebSocketTransport } from "@clite/shared";

import type { Platform } from "./dashboard.ts";

interface DesktopBridge {
  pathForFile?: (file: Blob) => Promise<string> | string;
}

declare global {
  interface Window {
    cliteDesktop?: DesktopBridge;
  }
}

export function browserPlatform(): Platform {
  return {
    address: {
      get hash() {
        return location.hash;
      },
      get search() {
        return location.search;
      },
      get pathname() {
        return location.pathname;
      },
      replace: (path) => history.replaceState(null, "", path),
    },
    storage: sessionStorage,
    socketUrl: (token) => {
      const scheme = location.protocol === "https:" ? "wss" : "ws";
      return `${scheme}://${location.host}/api/ws?token=${encodeURIComponent(token)}`;
    },
    openTransport: (url) => WebSocketTransport.connect(url),
    notify,
    pathForFile: async (file) => {
      const bridge = window.cliteDesktop;
      return bridge?.pathForFile ? String((await bridge.pathForFile(file)) || "") : "";
    },
    base64,
    later: (callback, ms) => {
      setTimeout(callback, ms);
    },
  };
}

/** Ask for permission to notify, once, while a user gesture is on the stack. */
export function askNotificationPermission(): void {
  if (typeof Notification === "undefined") return;
  if (Notification.permission === "default") Notification.requestPermission().catch(() => undefined);
}

/**
 * Tell the user something happened, if they are not looking. The point of a notification is
 * the window you are *not* watching: with the dashboard focused, the message is on screen.
 */
function notify(title: string, body: string, onClick: () => void): void {
  if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
  if (document.hasFocus()) return;
  try {
    const note = new Notification(title, { body, tag: "clite" });
    note.onclick = () => {
      window.focus();
      onClick();
    };
  } catch {
    // Some browsers refuse outside a service worker; a missing notification is not an error.
  }
}

async function base64(file: Blob): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let index = 0; index < bytes.length; index += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
  }
  return btoa(binary);
}
