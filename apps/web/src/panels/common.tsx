// What every management panel shares: loading its data over RPC, rows, and error reporting.

import type { ReactNode } from "react";
import { useCallback, useEffect, useRef, useState } from "react";

import { errorText } from "../state/dashboard.ts";
import { useDashboard } from "../state/useDashboard.ts";

export interface Loaded<T> {
  data: T | null;
  error: string;
  /** Load again. Resolves once the new data is on screen. */
  reload: () => Promise<void>;
  /** Bumped on every load, so rows can be keyed by it and rebuilt from the server's answer. */
  version: number;
}

/**
 * Load a panel's data, and again whenever `reload` is called or `deps` change. A load that
 * finishes after a newer one started is dropped, so a slow answer never overwrites a fresh one.
 */
export function useLoad<T>(load: () => Promise<T>, deps: unknown[] = []): Loaded<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);
  const latest = useRef(0);
  const loader = useRef(load);
  loader.current = load;

  const reload = useCallback(async () => {
    const ticket = ++latest.current;
    try {
      const result = await loader.current();
      if (ticket !== latest.current) return;
      setData(result);
      setError("");
      setVersion((value) => value + 1);
    } catch (problem) {
      if (ticket === latest.current) setError(errorText(problem));
    }
  }, []);

  // biome-ignore lint/correctness/useExhaustiveDependencies: the caller lists what its load reads; `reload` itself never changes.
  useEffect(() => void reload(), deps);
  return { data, error, reload, version };
}

/** Run an action from a button; a failure is reported in the chat transcript, as before. */
export function useAction(): (action: () => Promise<unknown>) => void {
  const dashboard = useDashboard();
  return (action) => {
    action().catch((error: unknown) => dashboard.notice(errorText(error), "error"));
  };
}

export function PanelError({ error }: { error: string }) {
  return error ? <p className="message error">{error}</p> : null;
}

export function Row({
  name,
  desc,
  children,
  className = "row",
  ...data
}: {
  name: ReactNode;
  desc: ReactNode;
  children?: ReactNode;
  className?: string;
} & Record<`data-${string}`, string>) {
  return (
    <div className={className} {...data}>
      <div className="name">{name}</div>
      <div className="desc">{desc}</div>
      {children}
    </div>
  );
}

export function Actions({ children }: { children: ReactNode }) {
  return <div className="actions">{children}</div>;
}

export function plural(count: number, word: string, many = `${word}s`): string {
  return `${count} ${count === 1 ? word : many}`;
}
