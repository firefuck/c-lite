---
name: node-inspect-debugger
description: "Debug Node.js via --inspect + Chrome DevTools Protocol CLI."
version: 1.0.0
author: C-lite
license: MIT
platforms: [linux, macos, windows]
metadata:
  clite:
    attributed_from: NousResearch/hermes-agent@1298c8e74b (MIT)
    tags: [debugging, nodejs, node-inspect, cdp, breakpoints, tui]
    related_skills: [systematic-debugging, python-debugpy]
---

# Node.js Inspect Debugger

## Overview

When `console.log` isn't enough, drive Node's built-in V8 inspector programmatically from the terminal. You get real breakpoints, step in/over/out, call-stack walking, local/closure scope dumps, and arbitrary expression evaluation in the paused frame.

Two tools, pick one:

- **`node inspect`** — built-in, zero install, CLI REPL. Best for quick poking.
- **`ndb` / CDP via `chrome-remote-interface`** — scriptable from Node/Python; best when you want to automate many breakpoints, collect state across runs, or debug non-interactively from an agent loop.

**Prefer `node inspect` first.** It's always available and the REPL is fast.

## When to Use

- A Node test fails and you need to see intermediate state
- the C-lite TUI (`apps/tui`) crashes or behaves wrong and you want to inspect React/Ink state pre-render
- You need to inspect a value in a closure that `console.log` can't reach without patching
- Perf: attach to a running process to capture a CPU profile or heap snapshot

**Don't use for:** things `console.log` solves in under a minute. Breakpoint-driven debugging is heavier; use it when the payoff is real.

## Quick Reference: `node inspect` REPL

Launch paused on first line:

```bash
node inspect path/to/script.js
# or with tsx
node --inspect-brk $(which tsx) path/to/script.ts
```

The `debug>` prompt accepts:

| Command | Action |
|---|---|
| `c` or `cont` | continue |
| `n` or `next` | step over |
| `s` or `step` | step into |
| `o` or `out` | step out |
| `pause` | pause running code |
| `sb('file.js', 42)` | set breakpoint at file.js line 42 |
| `sb(42)` | set breakpoint at line 42 of current file |
| `sb('functionName')` | break when function is called |
| `cb('file.js', 42)` | clear breakpoint |
| `breakpoints` | list all breakpoints |
| `bt` | backtrace (call stack) |
| `list(5)` | show 5 lines of source around current position |
| `watch('expr')` | evaluate expr on every pause |
| `watchers` | show watched expressions |
| `repl` | drop into REPL in current scope (Ctrl+C to exit REPL) |
| `exec expr` | evaluate expression once |
| `restart` | restart script |
| `kill` | kill the script |
| `.exit` | quit debugger |

**In the `repl` sub-mode:** type any JS expression, including access to locals/closure variables. `Ctrl+C` exits back to `debug>`.

## Attaching to a Running Process

When the process is already running (e.g. a long-lived dev server or the TUI gateway):

```bash
# 1. Send SIGUSR1 to enable the inspector on an existing process
kill -SIGUSR1 <pid>
# Node prints: Debugger listening on ws://127.0.0.1:9229/<uuid>

# 2. Attach the debugger CLI
node inspect -p <pid>
# or by URL
node inspect ws://127.0.0.1:9229/<uuid>
```

To start a process with the inspector from the beginning:

```bash
node --inspect script.js           # listen on 127.0.0.1:9229, keep running
node --inspect-brk script.js       # listen AND pause on first line
node --inspect=0.0.0.0:9230 script.js   # custom host:port
```

For TypeScript via tsx:

```bash
node --inspect-brk --import tsx script.ts
# or older tsx
node --inspect-brk -r tsx/cjs script.ts
```

## Programmatic CDP (scripting from terminal)

When you want to automate — set many breakpoints, capture scope state, script a repro — use `chrome-remote-interface`:

```bash
npm i -g chrome-remote-interface        # or project-local
# Start your target:
node --inspect-brk=9229 target.js &
```

Driver script (save as `~/.clite/cache/scratch/cdp-debug.js`):

```javascript
const CDP = require('chrome-remote-interface');

(async () => {
  const client = await CDP({ port: 9229 });
  const { Debugger, Runtime } = client;

  Debugger.paused(async ({ callFrames, reason }) => {
    const top = callFrames[0];
    console.log(`PAUSED: ${reason} @ ${top.url}:${top.location.lineNumber + 1}`);

    // Walk scopes for locals
    for (const scope of top.scopeChain) {
      if (scope.type === 'local' || scope.type === 'closure') {
        const { result } = await Runtime.getProperties({
          objectId: scope.object.objectId,
          ownProperties: true,
        });
        for (const p of result) {
          console.log(`  ${scope.type}.${p.name} =`, p.value?.value ?? p.value?.description);
        }
      }
    }

    // Evaluate an expression in the paused frame
    const { result } = await Debugger.evaluateOnCallFrame({
      callFrameId: top.callFrameId,
      expression: 'typeof state !== "undefined" ? JSON.stringify(state) : "n/a"',
    });
    console.log('state =', result.value ?? result.description);

    await Debugger.resume();
  });

  await Runtime.enable();
  await Debugger.enable();

  // Set a breakpoint by URL regex + line
  await Debugger.setBreakpointByUrl({
    urlRegex: '.*app\\.tsx$',
    lineNumber: 119,       // 0-indexed
    columnNumber: 0,
  });

  await Runtime.runIfWaitingForDebugger();
})();
```

Run it:

```bash
node ~/.clite/cache/scratch/cdp-debug.js
```

C-lite-specific note: `chrome-remote-interface` is NOT in `apps/tui/package.json`. Install it to a throwaway location if you don't want to dirty the project:

```bash
mkdir -p ~/.clite/cache/scratch/cdp-tools && cd ~/.clite/cache/scratch/cdp-tools && npm i chrome-remote-interface
NODE_PATH=~/.clite/cache/scratch/cdp-tools/node_modules node ~/.clite/cache/scratch/cdp-debug.js
```

## Debugging the C-lite TUI

The TUI is Ink + React in TypeScript, bundled by esbuild into one file, `clite-tui.mjs`.
`clite tui` runs that bundle with Node, and the bundle starts the Python backend
(`python -m clite.rpc.entry`) as its child. Two common scenarios:

### Debugging from the source

Node cannot load the `.tsx` components directly, so debug the bundle that `npm run build`
writes to `apps/tui/dist/` (`npm run dev` builds it and runs it):

```bash
cd <clite-repo>/apps/tui
node build.mjs
node --inspect-brk dist/clite-tui.mjs
# In another terminal:
node inspect -p <node pid>
```

Then inside `debug>`, break on the bundled code (esbuild keeps one function per source
function and comments each module with its source path):

```
sb('dist/clite-tui.mjs', 34900)   # or search the bundle for the suspect function
cont
```

When it pauses, `repl` → inspect `props`, state refs, `useInput` handler values, etc.

### Debugging a running `clite tui`

```bash
# 1. Launch the TUI
clite tui &
TUI_PID=$(pgrep -f 'clite-tui.mjs' | head -1)

# 2. Enable inspector on that Node PID
kill -SIGUSR1 "$TUI_PID"

# 3. Find the WS URL
curl -s http://127.0.0.1:9229/json/list | jq -r '.[0].webSocketDebuggerUrl'

# 4. Attach
node inspect ws://127.0.0.1:9229/<uuid>
```

Interacting with the TUI (typing in its window) continues to advance execution; your debugger can pause it on a breakpoint at any `sb(...)`.

### Debugging the backend

The backend the TUI starts is Python, not Node: use the `python-debugpy` skill for it. Only
the Node side (Ink UI, the protocol client in `packages/shared`, and the tests under
`apps/tui/test/`) uses this skill.

## Running Tests Under the Debugger

C-lite's TypeScript tests use Node's own runner, `node --test`:

```bash
cd <clite-repo>/apps/tui
# Run a single test file paused on entry
node --inspect-brk --test --test-concurrency=1 test/render.test.ts
```

In another terminal: `node inspect -p <pid>`, then `sb('src/render.ts', 42)`, `cont`.

`--test-concurrency=1` keeps a single test process, so there is only one target to attach
to. For a project on Vitest, the equivalent is `--no-file-parallelism`; on Jest, `--runInBand`.

## Heap Snapshots & CPU Profiles (Non-interactive)

From the CDP driver above, swap Debugger for `HeapProfiler` / `Profiler`:

```javascript
// CPU profile for 5 seconds
await client.Profiler.enable();
await client.Profiler.start();
await new Promise(r => setTimeout(r, 5000));
const { profile } = await client.Profiler.stop();
require('fs').writeFileSync('~/.clite/cache/scratch/cpu.cpuprofile', JSON.stringify(profile));
// Open ~/.clite/cache/scratch/cpu.cpuprofile in Chrome DevTools → Performance tab
```

```javascript
// Heap snapshot
await client.HeapProfiler.enable();
const chunks = [];
client.HeapProfiler.addHeapSnapshotChunk(({ chunk }) => chunks.push(chunk));
await client.HeapProfiler.takeHeapSnapshot({ reportProgress: false });
require('fs').writeFileSync('~/.clite/cache/scratch/heap.heapsnapshot', chunks.join(''));
```

## Common Pitfalls

1. **Wrong line numbers in TS source.** Breakpoints hit the emitted JS, not the `.ts`. Either (a) break in the built `dist/*.js`, or (b) enable sourcemaps (`node --enable-source-maps`) and use `sb('src/app.tsx', N)` — but only with CDP clients that follow sourcemaps. `node inspect` CLI does not.

2. **`--inspect` vs `--inspect-brk`.** `--inspect` starts the inspector but doesn't pause; your script races past your first breakpoint if you attach too late. Use `--inspect-brk` when you need to set breakpoints before any code runs.

3. **Port collisions.** Default is `9229`. If multiple Node processes are inspecting, pass `--inspect=0` (random port) and read the actual URL from `/json/list`:
   ```bash
   curl -s http://127.0.0.1:9229/json/list   # lists all inspectable targets on the host
   ```

4. **Child processes.** `--inspect` on a parent does NOT inspect its children. Use `NODE_OPTIONS='--inspect-brk' node parent.js` to propagate to every child; be aware they all need unique ports (Node auto-increments when `NODE_OPTIONS='--inspect'` is inherited).

5. **Background kills.** If you `Ctrl+C` out of `node inspect` while the target is paused, the target stays paused. Either `cont` first, or `kill` the target explicitly.

6. **Running `node inspect` through an agent terminal.** It's a PTY-friendly REPL. In C-lite, launch it with `terminal(pty=true)` or `background=true` + `process(action='submit', data='...')`. Non-PTY foreground mode will work for one-shot commands but not for interactive stepping.

7. **Security.** `--inspect=0.0.0.0:9229` exposes arbitrary code execution. Always bind to `127.0.0.1` (the default) unless you have an isolated network.

## Verification Checklist

After setting up a debug session, verify:

- [ ] `curl -s http://127.0.0.1:9229/json/list` returns exactly the target you expect
- [ ] First breakpoint actually hits (if it doesn't, you likely missed `--inspect-brk` or attached after execution completed)
- [ ] Source listing at pause shows the right file (mismatch = sourcemap issue, see pitfall 1)
- [ ] `exec process.pid` in `repl` returns the PID you meant to attach to

## One-Shot Recipes

**"Why is this variable undefined at line X?"**
```bash
node --inspect-brk script.js &
node inspect -p $!
# debug>
sb('script.js', X)
cont
# paused. Now:
repl
> myVariable
> Object.keys(this)
```

**"What's the call path into this function?"**
```
debug> sb('suspectFn')
debug> cont
# paused on entry
debug> bt
```

**"This async chain hangs — where?"**
```
# Start with --inspect (no -brk), let it run to the hang, then:
debug> pause
debug> bt
# Now you see the stuck frame
```
