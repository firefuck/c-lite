// Preload script: the only bridge between the page and the desktop shell.
//
// NOT VERIFIED in the environment this scaffold was built in (see main.ts).
//
// It exposes facts, not capabilities. The page learns that it runs inside the desktop app and
// on which OS; it gets no file system, no shell and no IPC channel. Add a method here only
// for something the page truly cannot do through the backend's protocol.

import { contextBridge } from "electron";

contextBridge.exposeInMainWorld("cliteDesktop", {
  isDesktop: true,
  platform: process.platform,
});
