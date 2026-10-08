// Installer configuration for the desktop shell.
//
// The product name and the version are NOT written here: electron-builder reads `productName`
// from this file and `version` from package.json, and apps/desktop/test/packaging.test.ts
// checks both against the Python package (`clite.core.brand.DISPLAY_NAME` and
// `clite.__version__`). A release that disagrees with the wheel is a release that installs a
// different version than it says.
//
// The backend is NOT bundled. See docs/spesifikasi/desktop.md, "Membawa backend", for why.

/** @type {import("electron-builder").Configuration} */
module.exports = {
  appId: "dev.clite.desktop",
  productName: "C-lite",
  copyright: "C-lite contributors",
  directories: { output: "release", buildResources: "assets" },
  // Only what the app needs at runtime: the two bundles build.mjs writes.
  files: ["dist/main.cjs", "dist/preload.cjs", "package.json"],
  extraMetadata: { main: "dist/main.cjs" },
  // Unsigned builds are the default on purpose: without a certificate in CI the artifacts are
  // produced anyway and the release notes say they are unsigned.
  mac: {
    target: [{ target: "dmg", arch: ["x64", "arm64"] }],
    category: "public.app-category.developer-tools",
    icon: "assets/icon.png",
    identity: null,
  },
  win: {
    target: [{ target: "nsis", arch: ["x64"] }],
    icon: "assets/icon.png",
  },
  linux: {
    target: [{ target: "AppImage", arch: ["x64"] }],
    category: "Development",
    icon: "assets/icon.png",
    synopsis: "Desktop shell for C-lite",
    // The workspace package name is `@clite/desktop`, and `@` and `/` cannot appear in an
    // executable's path. The binary is just `c-lite`.
    executableName: "c-lite",
    // The window class the desktop environment matches against the .desktop entry, so the
    // running window is linked to the installed app instead of showing up as unknown.
    desktop: { entry: { Name: "C-lite", StartupWMClass: "c-lite" } },
  },
  nsis: {
    oneClick: false,
    perMachine: false,
    allowToChangeInstallationDirectory: true,
  },
  // `clite release` publishes the GitHub Release; the installers are attached to it.
  publish: [{ provider: "github", releaseType: "release" }],
};
