// The React side of the controller: one Dashboard for the page, read through a snapshot.

import { createContext, useContext, useSyncExternalStore } from "react";

import type { Dashboard, DashboardState } from "./dashboard.ts";

export const DashboardContext = createContext<Dashboard | null>(null);

export function useDashboard(): Dashboard {
  const dashboard = useContext(DashboardContext);
  if (!dashboard) throw new Error("useDashboard needs a DashboardContext provider");
  return dashboard;
}

export function useDashboardState(): DashboardState {
  const dashboard = useDashboard();
  return useSyncExternalStore(dashboard.subscribe, dashboard.getState);
}
