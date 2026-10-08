// Preload script: the only bridge between the page and the desktop shell.
//
// It exposes facts, not capabilities. The page learns that it runs inside the desktop app and
// on which OS; it gets no file system, no shell and no IPC channel. Add a method here only
// for something the page truly cannot do through the backend's protocol.

import { contextBridge, webUtils } from "electron";

contextBridge.exposeInMainWorld("cliteDesktop", {
  isDesktop: true,
  platform: process.platform,
  // A file dropped on the page arrives as a File object, and a browser cannot know where it
  // lives on disk. The shell can. This is the one thing the page cannot ask the backend for,
  // and it hands back a path, not a file: nothing is read or copied here.
  pathForFile: (file: File): string => {
    try {
      return webUtils.getPathForFile(file);
    } catch {
      return ""; // not a file from the file system (a paste, say): the page uploads it instead
    }
  },
});
