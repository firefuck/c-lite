// Pure completion helpers for slash commands in the Ink TUI.
//
// Drawn strictly from the live `commands.catalog` (JSON-RPC); no hardcoded command lists.
// Testable with `node --test` without a terminal or React environment.

import type { CommandEntry } from "@clite/shared";

/**
 * Filter and sort slash command candidates matching the given input prefix.
 *
 * Rules:
 * - Only inputs starting with "/" produce slash command candidates.
 * - Deduplicated by canonical command name.
 * - Sorted deterministically: exact name-prefix matches first (alphabetical),
 *   then alias-prefix matches (alphabetical).
 */
export function getSlashCandidates(catalog: CommandEntry[], input: string): CommandEntry[] {
  if (!input.startsWith("/")) {
    return [];
  }

  // If there's a space, check if the command has subcommands to complete
  const parts = input.slice(1).split(/\s+/);
  const commandWord = (parts[0] ?? "").toLowerCase();

  // Once a subcommand is followed by arguments, never replace the user's arguments.
  if (parts.length > 2) return [];

  if (parts.length > 1) {
    const argWord = (parts[1] ?? "").toLowerCase();
    const parentCmd = catalog.find(
      (c) => c.name.toLowerCase() === commandWord || c.aliases.some((a) => a.toLowerCase() === commandWord),
    );
    if (parentCmd?.subcommands && parentCmd.subcommands.length > 0) {
      const matchingSubs = parentCmd.subcommands
        .filter((sub) => sub.toLowerCase().startsWith(argWord))
        .sort((a, b) => a.localeCompare(b));

      return matchingSubs.map((sub) => ({
        name: `${parentCmd.name} ${sub}`,
        description: `Subcommand of /${parentCmd.name}`,
        category: parentCmd.category,
        aliases: [],
        args_hint: "",
        subcommands: [],
        kind: parentCmd.kind,
      }));
    }
    return [];
  }

  const seen = new Set<string>();
  const nameMatches: CommandEntry[] = [];
  const aliasMatches: CommandEntry[] = [];

  for (const cmd of catalog) {
    if (seen.has(cmd.name)) continue;

    const nameMatch = cmd.name.toLowerCase().startsWith(commandWord);
    const aliasMatch = !nameMatch && cmd.aliases.some((a) => a.toLowerCase().startsWith(commandWord));

    if (nameMatch) {
      seen.add(cmd.name);
      nameMatches.push(cmd);
    } else if (aliasMatch) {
      seen.add(cmd.name);
      aliasMatches.push(cmd);
    }
  }

  nameMatches.sort((a, b) => a.name.localeCompare(b.name));
  aliasMatches.sort((a, b) => a.name.localeCompare(b.name));

  return [...nameMatches, ...aliasMatches];
}

/** Complete the input with the selected candidate. */
export function applySlashCompletion(candidate: CommandEntry): string {
  return `/${candidate.name} `;
}

export interface TabCompletionResult {
  text: string;
  menuOpen: boolean;
  candidates: CommandEntry[];
}

/**
 * Handle Tab key press on input:
 * - If exactly one candidate matches: completes the text and closes the menu.
 * - If multiple candidates match: leaves text as-is and opens the menu.
 * - If no candidates match: leaves text as-is and closes the menu.
 */
export function handleTabCompletion(input: string, catalog: CommandEntry[]): TabCompletionResult {
  const candidates = getSlashCandidates(catalog, input);
  if (candidates.length === 1) {
    return {
      text: applySlashCompletion(candidates[0]!),
      menuOpen: false,
      candidates,
    };
  }
  if (candidates.length > 1) {
    return {
      text: input,
      menuOpen: true,
      candidates,
    };
  }
  return {
    text: input,
    menuOpen: false,
    candidates: [],
  };
}
