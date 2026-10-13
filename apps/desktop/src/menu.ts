// The application menu.
//
// A plain function returning a template, with no Electron import at runtime, so the shape can
// be checked in a test. main.ts turns it into a real menu. The roles are Electron's own, which
// is what makes the keyboard shortcuts, the clipboard, the zoom keys and the macOS app menu
// behave the way the platform expects instead of being reimplemented badly.

import type { MenuItemConstructorOptions } from "electron";

export interface MenuHooks {
  /** Opens a link in the user's browser. The window never shows anything but the dashboard. */
  openExternal(url: string): void;
  docsUrl: string;
}

/** The menu every desktop app is expected to have: File, Edit, View, Window, and Help. */
export function menuTemplate(
  displayName: string,
  platform: NodeJS.Platform,
  hooks: MenuHooks,
): MenuItemConstructorOptions[] {
  const isMac = platform === "darwin";
  const template: MenuItemConstructorOptions[] = [];

  if (isMac) {
    // macOS puts the app's own menu first, and About/Quit live in it.
    template.push({
      label: displayName,
      submenu: [
        { role: "about" },
        { type: "separator" },
        { role: "services" },
        { type: "separator" },
        { role: "hide" },
        { role: "hideOthers" },
        { role: "unhide" },
        { type: "separator" },
        { role: "quit" },
      ],
    });
  }

  template.push(
    {
      label: "File",
      submenu: [isMac ? { role: "close" } : { role: "quit" }],
    },
    {
      label: "Edit",
      submenu: [
        { role: "undo" },
        { role: "redo" },
        { type: "separator" },
        { role: "cut" },
        { role: "copy" },
        { role: "paste" },
        { role: "selectAll" },
      ],
    },
    {
      label: "View",
      submenu: [
        { role: "reload" },
        { role: "forceReload" },
        { role: "toggleDevTools" },
        { type: "separator" },
        { role: "resetZoom" },
        { role: "zoomIn" },
        { role: "zoomOut" },
        { type: "separator" },
        { role: "togglefullscreen" },
      ],
    },
    {
      label: "Window",
      submenu: isMac
        ? [{ role: "minimize" }, { role: "zoom" }, { role: "front" }]
        : [{ role: "minimize" }, { role: "close" }],
    },
    {
      label: "Help",
      submenu: [{ label: `${displayName} documentation`, click: () => hooks.openExternal(hooks.docsUrl) }],
    },
  );

  return template;
}
