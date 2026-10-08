// Pure helper functions for the session and model pickers in the Ink TUI.
//
// These transform raw RPC data from `session.list` and `model.list` into readable
// list items and handle user selection via `session.create(resume=id)` and `model.set`.
// Testable with `node --test` without React or terminal I/O.

import type {
  ModelEntry,
  ModelSetResult,
  StoredSession,
} from "../../../apps/shared/src/contracts.generated.ts";

export interface GatewayClientLike {
  request(method: string, params: Record<string, unknown>): Promise<unknown>;
}

/** Format a human-readable relative or date string for last activity. */
export function formatActivityTime(timestamp: number | null): string {
  if (!timestamp) return "never";
  const now = Date.now();
  // If timestamp is in seconds, convert to ms
  const ms = timestamp < 1e11 ? timestamp * 1000 : timestamp;
  const diffSec = Math.floor((now - ms) / 1000);

  if (diffSec < 60) return "just now";
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  return `${Math.floor(diffSec / 86400)}d ago`;
}

/** Render a single stored session line showing title, model, and last activity. */
export function formatSessionItem(session: StoredSession, isSelected: boolean = false): string {
  const prefix = isSelected ? "❯ " : "  ";
  const title = session.title ? session.title : `Session ${session.id.slice(0, 8)}`;
  const activity = formatActivityTime(session.last_activity_at);
  const model = session.model || "default";
  return `${prefix}${title} • ${model} • ${activity}`;
}

/** Render a single model entry line with optional context length and current marker. */
export function formatModelItem(
  model: ModelEntry,
  currentModel: string = "",
  isSelected: boolean = false
): string {
  const prefix = isSelected ? "❯ " : "  ";
  const currentTag = model.id === currentModel ? " (current)" : "";
  const ctx = model.context_length ? ` [${Math.round(model.context_length / 1024)}k]` : "";
  return `${prefix}${model.id}${ctx}${currentTag}`;
}

/**
 * Handle session selection: resume session by creating a new session with resume ID.
 */
export async function resumeSession(
  client: GatewayClientLike,
  session: StoredSession
): Promise<{ session_id: string }> {
  const result = (await client.request("session.create", {
    resume: session.id,
  })) as { session_id: string };
  return result;
}

/**
 * Handle model selection: switch model for the active session.
 */
export async function switchModel(
  client: GatewayClientLike,
  sessionId: string,
  model: ModelEntry
): Promise<ModelSetResult> {
  const result = (await client.request("model.set", {
    session_id: sessionId,
    model: model.id,
  })) as ModelSetResult;
  return result;
}
