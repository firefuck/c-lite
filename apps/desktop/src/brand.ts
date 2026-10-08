// The product name, spelled once for the whole desktop app.
//
// It has to agree with the Python side (`clite.core.brand.DISPLAY_NAME`) and with
// electron-builder's `productName`; apps/desktop/test/packaging.test.ts fails if any of the
// three drifts, because an installer that calls itself something else is a bug the user sees
// before the app even starts.

export const DISPLAY_NAME = "C-lite";
