// Scheduled jobs, memory and logs: the panels that look at what the agent did or will do.

import type { CronJob } from "@clite/shared";
import { useState } from "react";

import { useDashboard } from "../state/useDashboard.ts";
import { Actions, PanelError, Row, useAction, useLoad } from "./common.tsx";

export function CronPanel() {
  const dashboard = useDashboard();
  const run = useAction();
  const { data, error, reload } = useLoad(() => dashboard.request("cron.list", {}));

  const act = (job: CronJob, action: "pause" | "resume" | "run" | "remove") =>
    run(async () => {
      await dashboard.request("cron.action", { job_id: job.id, action });
      await reload();
    });
  const create = () =>
    run(() =>
      dashboard.askCron(async (values) => {
        await dashboard.request("cron.create", values);
        await reload();
      }),
    );
  const output = (job: CronJob) =>
    run(async () => {
      const { content, truncated, path } = await dashboard.request("cron.output", { job_id: job.id });
      await dashboard.showOutput(
        `Last output · ${job.name || job.id}`,
        content ? content + (truncated ? "\n… (truncated)" : "") : "",
        path,
      );
    });

  const jobs = data?.jobs ?? [];
  return (
    <>
      <h2>Scheduled jobs</h2>
      <div className="filters">
        <button type="button" id="cron-new" onClick={create}>
          + New job
        </button>
      </div>
      <PanelError error={error} />
      {!data ? null : jobs.length ? (
        jobs.map((job) => (
          <Row
            key={job.id}
            name={job.name || job.prompt.slice(0, 60)}
            desc={`${job.schedule_display} · ${job.enabled ? "active" : "paused"} · last: ${job.last_status || "never run"}`}
          >
            <Actions>
              <button type="button" data-action="toggle" onClick={() => act(job, job.enabled ? "pause" : "resume")}>
                {job.enabled ? "Pause" : "Resume"}
              </button>
              <button type="button" data-action="run" onClick={() => act(job, "run")}>
                Run now
              </button>
              <button type="button" data-action="output" onClick={() => output(job)}>
                Last output
              </button>
              <button type="button" data-action="remove" className="danger" onClick={() => act(job, "remove")}>
                Remove
              </button>
            </Actions>
          </Row>
        ))
      ) : (
        <p className="empty">
          No jobs. Ask the agent to schedule one, e.g. “every morning at 9, summarise my open pull requests”.
        </p>
      )}
    </>
  );
}

type MemoryTarget = "memory" | "user";

export function MemoryPanel() {
  const dashboard = useDashboard();
  const run = useAction();
  const { data, error, reload } = useLoad(() => dashboard.request("memory.get", {}));

  const act = async (params: {
    action: "add" | "replace" | "remove";
    target: MemoryTarget;
    content?: string;
    old_text?: string;
  }) => {
    const result = await dashboard.request("memory.set", params);
    if (!result.success) dashboard.notice(result.message, "error");
    await reload();
  };
  const edit = (target: MemoryTarget, entry: string) =>
    run(async () => {
      const content = await dashboard.askText("Edit memory entry", "Entry", entry);
      if (content === null || content === entry) return;
      await act({ action: "replace", target, old_text: entry, content });
    });
  const add = (target: MemoryTarget) =>
    run(async () => {
      const content = await dashboard.askText("Add a memory entry", "Entry", "");
      if (content === null || !content.trim()) return;
      await act({ action: "add", target, content });
    });

  const section = (title: string, target: MemoryTarget, entries: string[]) => (
    <>
      <h3>{title}</h3>
      <div className="filters">
        <button type="button" data-action={`add-${target}`} onClick={() => add(target)}>
          + Add
        </button>
      </div>
      {entries.length ? (
        entries.map((entry, index) => (
          <div className="row" data-target={target} key={`${index}:${entry}`}>
            <div className="desc">{entry}</div>
            <Actions>
              <button type="button" data-action="edit" onClick={() => edit(target, entry)}>
                Edit
              </button>
              <button
                type="button"
                data-action="remove"
                className="danger"
                onClick={() => run(() => act({ action: "remove", target, old_text: entry }))}
              >
                Remove
              </button>
            </Actions>
          </div>
        ))
      ) : (
        <p className="empty">Empty.</p>
      )}
    </>
  );

  return (
    <>
      <h2>Memory</h2>
      <PanelError error={error} />
      {data ? (
        <>
          {section("Agent notes (MEMORY.md)", "memory", data.memory)}
          {section("User profile (USER.md)", "user", data.user)}
        </>
      ) : null}
    </>
  );
}

export function LogsPanel() {
  const dashboard = useDashboard();
  const [source, setSource] = useState<"agent" | "errors">("agent");
  const [level, setLevel] = useState<"all" | "info" | "warning" | "error">("all");
  const { data, error, reload } = useLoad(
    () => dashboard.request("logs.tail", { source, level, lines: 300 }),
    [source, level],
  );
  const text = !data
    ? ""
    : data.lines.length
      ? data.lines.join("\n") + (data.truncated ? "\n… (older lines omitted)" : "")
      : "(nothing logged yet)";
  return (
    <>
      <h2>Logs</h2>
      <div className="filters">
        <select id="logs-source" value={source} onChange={(event) => setSource(event.target.value as typeof source)}>
          <option value="agent">agent.log</option>
          <option value="errors">errors.log</option>
        </select>
        <select id="logs-level" value={level} onChange={(event) => setLevel(event.target.value as typeof level)}>
          {(["all", "info", "warning", "error"] as const).map((value) => (
            <option key={value} value={value}>
              {value === "all" ? "all levels" : value}
            </option>
          ))}
        </select>
        <button type="button" id="logs-refresh" onClick={() => void reload()}>
          Refresh
        </button>
      </div>
      <PanelError error={error} />
      <pre id="logs-body" data-path={data?.path ?? ""}>
        {text}
      </pre>
    </>
  );
}
