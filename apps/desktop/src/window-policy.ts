// Where the app window is allowed to go.
//
// The window shows the backend's dashboard and nothing else. A link in a model's answer must
// open in the user's browser, not inside a window that holds the session token.

export type NavigationDecision = "allow" | "external" | "deny";

export function decideNavigation(target: string, backendOrigin: string): NavigationDecision {
  let url: URL;
  try {
    url = new URL(target);
  } catch {
    return "deny";
  }
  if (url.origin === backendOrigin) return "allow";
  if (url.protocol === "https:" || url.protocol === "http:" || url.protocol === "mailto:") return "external";
  return "deny"; // file:, javascript:, custom schemes
}
