---
name: python-debugpy
description: "Debug Python with pdb, post-mortem inspection and debugpy remote attach. Use when a traceback does not explain a wrong value, or a long-running process misbehaves."
version: 1.0.0
author: C-lite
license: MIT
metadata:
  clite:
    category: software-development
    tags: [debugging, python, pdb, debugpy, post-mortem]
    requires_toolsets: [terminal]
    attribution: "Adapted from the python-debugpy skill in Nous Research's hermes-agent (skills/software-development/python-debugpy, MIT, Copyright (c) 2025 Nous Research)."
---

# Python debugging

Three tools, picked by situation. Start with the cheapest one that works.

| Tool | Use it when |
|---|---|
| `breakpoint()` then pdb | Local and interactive. Add the call, run the code, get a prompt on that line. |
| `python -m pdb script.py` | Launch an existing script under pdb without editing it. |
| `debugpy` | Remote or headless: attach to a process that is already running and cannot be restarted. |

## When to use

- A failing test whose traceback does not say which value was wrong.
- Stepping through a function to watch a collection change.
- A long-running process (a server, a worker, a daemon) misbehaves and cannot be restarted
  cleanly.
- Post-mortem: an exception fired and the locals at the crash site are what you need.

Do not reach for a debugger when `print()` or `logging.debug` settles it in a minute, or when
`pytest -vv --tb=long --showlocals` already shows the values.

## pdb quick reference

| Command | Action |
|---|---|
| `n` / `s` / `r` / `c` | next line / step into / return / continue |
| `unt N` / `j N` | continue until line N / jump to line N (same function only) |
| `l` / `ll` / `w` | list source / list the whole function / show the stack |
| `u` / `d` | move up / down the stack |
| `a` | arguments of the current function |
| `p expr` / `pp expr` | print / pretty-print an expression |
| `display expr` | print it again at every stop |
| `b file:line` / `b func` / `b file:line, cond` | set a breakpoint, plain, on entry, or conditional |
| `cl N` / `tbreak file:line` | clear breakpoint N / one-shot breakpoint |
| `!stmt` | run a statement in the current frame, assignments included |
| `interact` | drop into a full REPL in the current scope, Ctrl+D to leave |
| `h` / `q` | help / quit |

`interact` is the strongest of these: import anything, inspect complex objects, call methods
that mutate state. Locals are read-only from the `(Pdb)` prompt; use `!x = 42` to assign.

## Recipes

**Local breakpoint.** Edit the file, run it normally, land on the line:

```python
def compute(x, y):
    result = some_helper(x)
    breakpoint()
    return result + y
```

Remove it before committing. `grep -rn 'breakpoint()' --include='*.py' .` is the safety net,
and it belongs in a pre-commit check if the project has one.

**An existing script, unedited:**

```bash
python -m pdb path/to/script.py arg1
(Pdb) b path/to/script.py:42
(Pdb) c
```

**A failing test.** Run the project's own runner first, because it is what the project
promises, and it usually reports locals on its own:

```bash
scripts/run_tests.sh tests/path/to/test_file.py --showlocals --tb=long
```

If the runner captures each file in a subprocess, pdb cannot give you a prompt inside it.
For an interactive session, run the test file directly with the interpreter this machine uses
for development, `.venv/bin/python -m pytest tests/foo_test.py::test_bar --pdb`, and re-run
through the wrapper afterwards to confirm.

**Post-mortem.** Catch the crash and inspect the frame that raised:

```python
import pdb, sys
try:
    run_the_thing()
except Exception:
    pdb.post_mortem(sys.exc_info()[2])
```

Or let pdb catch it for a whole script:

```bash
python -m pdb -c continue script.py
```

**Remote attach with debugpy.** For a process that is already running and must not be
restarted. Add near the entry point:

```python
import debugpy
debugpy.listen(("127.0.0.1", 5678))
print("debugpy on 5678, waiting for a client", flush=True)
debugpy.wait_for_client()
```

or launch it under debugpy without an edit:

```bash
python -m debugpy --listen 127.0.0.1:5678 --wait-for-client script.py
python -m debugpy --listen 127.0.0.1:5678 --pid <pid>     # attach to a running process
```

`--pid` needs `ptrace` rights: on a hardened kernel, `/proc/sys/kernel/yama/ptrace_scope`
must be `0` for a process that is not your own child. Then attach a DAP client (an editor's
attach configuration, on port 5678). When DAP is more protocol than the problem deserves,
`remote-pdb` is easier: `set_trace(host="127.0.0.1", port=4444)` in the handler, and a plain
`nc 127.0.0.1 4444` gives an ordinary `(Pdb)` prompt.

## Pitfalls

- pdb under a runner that captures or parallelises output silently does nothing: no prompt,
  the process just hangs. Run the one test directly instead.
- A committed `breakpoint()` hangs any non-interactive run. Grep before you commit.
- `PYTHONBREAKPOINT=0` disables every `breakpoint()`. Check it when a breakpoint never fires.
- `debugpy.listen` only blocks if `wait_for_client()` follows it. Without the wait, the first
  breakpoint can fire before a client is attached.
- pdb debugs the current thread only. For threads, use debugpy, or `threading.settrace()`
  per thread.
- pdb does not follow forks. Each child process needs its own `breakpoint()` or `set_trace()`
  — debug one process at a time.
- `await` inside pdb needs Python 3.13+, or the `interact` mode on older versions. For an
  async deadlock, `interact` then `!import asyncio; asyncio.all_tasks()` shows what is pending.
- A debugging environment that strips credentials or moves `HOME` will not reproduce a bug
  that depends on user config. Reproduce with the raw interpreter first, then confirm the fix
  under the project's runner.

## Verification

- [ ] The port is actually listening when you attach: `ss -tlnp | grep 5678`.
- [ ] The first breakpoint hits. If it does not, check `PYTHONBREAKPOINT`, a capturing runner,
  and whether execution finished before the attach.
- [ ] `w` shows the call stack you expected before you start reading values.
- [ ] Nothing is left behind: `grep -rn 'breakpoint()\|set_trace(\|debugpy\.listen' --include='*.py' .`
