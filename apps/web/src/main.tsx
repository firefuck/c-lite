// The dashboard: React components over the JSON-RPC protocol, built by Vite into
// src/clite/server/static/ so the Python package ships it ready to serve.

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App.tsx";
import "./style.css";
import { browserPlatform } from "./state/browser.ts";
import { Dashboard, errorText } from "./state/dashboard.ts";
import { DashboardContext } from "./state/useDashboard.ts";

const dashboard = new Dashboard(browserPlatform());
const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <DashboardContext.Provider value={dashboard}>
        <App />
      </DashboardContext.Provider>
    </StrictMode>,
  );
}
dashboard.start().catch((error: unknown) => dashboard.notice(errorText(error), "error"));
