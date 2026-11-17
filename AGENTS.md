# Tokens Trading Market · contestant entry point

One-page startup note. Read this page and you can start a match; the rules come from the HTTP API, so you do not need to read anything under `docs/`.

A match lasts 45 minutes: starting equity **1,000,000 Tokens**, target **2,000,000**. Every quote, event and gap is procedurally generated fiction and has nothing to do with any real market.

## Where things are (project map — read this table first)

```text
TokensMarket-OpenSource-AI-EN-v97/
├── AGENTS.md          ← the page you are reading
├── README.md          human entry (rules, endpoints, FAQ)
├── run.py             ★ the only entry point for starting the service (agents use this)
├── bench.py           paired benchmark
├── guard.py           source-sealing guard (called by run.py, never start it yourself)
├── launchers/         ★ every double-click entry (each cds back to the repo root)
│   ├── Start Match.bat     human double-click (5-second confirm)
│   ├── AI Start.bat        unattended (scripts / agents use this)
│   ├── Spectator.bat       re-attach the window
│   └── DeepClean Process.bat
├── tools/deep-clean.ps1   non-interactive cleanup (agents call this)
├── src/               engine + HTTP (sealed during a match, do not edit)
├── tests/             unittest suite
├── docs/              ★ the rules documents
│   ├── rules.md       full rules
│   ├── ai-protocol.md integration protocol
│   ├── cost-model.md  cost model
│   └── Startup-Prompt-For-The-AI.txt
└── examples/reports/  sample reports
```

Three hard rules:

1. **`GET /rules` is authoritative**; `docs/` expands the same rules. When they disagree, trust the API.
2. **Only two ways to start**: agents run `python run.py` from the repo root; humans double-click
   `launchers\Start Match.bat`. Do not `cd launchers` and run `python run.py` — there is no `run.py` there.
3. **Scripts under `launchers\` and `tools\` cd back to the repo root themselves**, so they work from any
   directory; do not copy them elsewhere or their relative paths break.

## 0. Which Python (hard requirement, do not search)

**Python 3.14** — the spectator's GUI widgets and the `.pyc` files are built for 3.14.
**Any install location works**: `run.py` validates the version, not the path. On this machine it is usually:

```
%LOCALAPPDATA%\Programs\Python\Python314\python.exe
```

**One lookup order. Follow it; do not invent your own probe loop:**

```bat
python --version
```

1. Prints `Python 3.14.x` → use `python`, `cd` into the directory and start. **Most machines finish here.**
2. Missing or wrong version → use the `%LOCALAPPDATA%\...\python.exe` full path above.
3. Neither works → this one command lists every candidate at once instead of trying them one by one:

```bat
dir /b "%LOCALAPPDATA%\Programs\Python" 2>nul & where python 2>nul & where python3 2>nul
```

**The `py` launcher is optional and many machines never had it** (this one has none — `where py` is empty).
`py -3.14` is only the "if it happens to be installed" convenience form: if it fails once, go straight to
step 2. **Never treat a missing `py` as a broken environment and start auditing the registry, environment
variables, or reinstalling Python.**

`run.py` validates the version as its very first action: anything but 3.14 aborts with **exit code 2**
and prints that exact command. It refuses to start when a match already owns the port (**exit code 4**)
instead of starting a second one. Do not use `py -3.12` or `python3` to hunt for another interpreter —
the spectator's GUI widgets and the `.pyc` files are built for 3.14, and any other version cannot start.

## 1. Check for leftovers (clean only if needed)

**After a normal match this step does nothing**: once settlement finishes, `run.py` deletes the
temporary files and shuts the related processes down by itself, leaving only `reports/` under
`src/data/`. You only need to act after a manual interrupt, a crash, or a window that never closed.

Check first — one command tells you which case you are in:

```bash
cd <project directory>
ls -A src/data/ | grep -v '^reports$' | grep -q . && echo "leftovers found - clean" || echo "clean - go to step 2"
```

**If it says "clean", skip this section and start.** Only when it reports leftovers:

```bash
# The previous service may still hold the port: reset, then shut down
curl -s -X POST http://127.0.0.1:8734/reset    >/dev/null 2>&1 || true
curl -s -X POST http://127.0.0.1:8734/shutdown >/dev/null 2>&1 || true

# Service not running: delete the save directly
rm -f src/data/session.json src/data/.scratchpad.jsonl
rm -rf src/data/_agent
```

**Never delete `src/data/reports/`** — that is the match archive; every settlement writes a new
file there.

## 2. Start (one command; the spectator opens itself)

```bash
cd <project directory>

TM_TRADER="<model-name-thinking-effort-platform>" \
TM_EVENTS=1 TM_FR=1 TM_SLOT=1 TM_ASSIST=1 \
  nohup python run.py > run.log 2>&1 &     # a 3.14 on PATH; otherwise your full path

# readiness check: startup takes 3-8 seconds, a fixed sleep produces false failures
for i in $(seq 1 30); do
  curl -sf http://127.0.0.1:8734/health >/dev/null 2>&1 && break
  sleep 1
done
```

**Segment 1 of `TM_TRADER` is the model; segment 3 is the platform, never the other way round.**
Claude Sonnet 4.5 running inside Cursor -> `Claude-Sonnet-4.5-high-Cursor`. Writing
`Cursor-AgentMode-high-desktop` names the platform as the model and erases the real model from the report.

**The spectator is mandatory, not optional.** `run.py` and `run.py server` both open the read-only
spectator. A human must be able to watch equity, holdings and the activity feed live.

Three entry points:

| Entry | Behaviour |
|---|---|
| `python run.py` | Standard; the agent default |
| `launchers\AI Start.bat` | Unattended: sets `TM_NO_CONFIRM=1` and `TM_IDLE_ABORT=0`, then `call`s `launchers\Start Match.bat`, so the launch path has one source of truth — **scripts / agents use this** |
| `launchers\Start Match.bat` | Human double-click entry. Cleans up and exits unless `Y` is pressed within 5 seconds; **invoking it from a terminal with `cmd /c` also counts as human**, so it dies after 5 seconds |

- Do not start `run.py spectator` yourself to "add" a window — a normal start already has one
- Only `--headless` suppresses the window, and only for environments with no desktop (CI, containers)
- With the wrong Python, `run.py` exits with code 2 instead of failing later on `bad magic number`

| Variable | Meaning |
|---|---|
| `TM_TRADER` | Contestant ID, format **model-effort-agent-platform**. Segment 1 is the **model** (`Claude-Sonnet-4.5`), segment 3 is the **platform** (`Cursor`). Claude Sonnet 4.5 inside Cursor -> `Claude-Sonnet-4.5-high-Cursor`; `Cursor-...` names the platform as the model and the report records the wrong contestant. Written into the report filename and body after whitelist filtering |
| `TM_EVENTS` | `1` turns on random events (including Black Swan gaps); `0` leaves only the gaps; **defaults to `1` when unset** |
| `TM_FR` | `1` enables **Preferred Financing**: no cap on borrowings, target-uplift floor drops to 0.01% |
| `TM_SLOT` | `1` enables the **Slot Machine**: 3 plays per match |
| `TM_ASSIST` | `1` enables **Outside Mercy**: 3 asks to the spectators per match |
| `TM_PORT` | Service port, default `8734` |
| `TM_IDLE_ABORT` | Minutes without any state-changing action before the match settles itself. Default `0` (off); `launchers\Start Match.bat` sets `12`, `launchers\AI Start.bat` keeps `0` |

## 3. Lock the difficulty

Difficulty is rolled at the start. **Before it is locked, `/open`, `/loan`, `/slot` and
`/fastforward` are all refused** with "Difficulty is not locked in yet; POST /roll/stop or wait
for the draw to finish"; everything unlocks the second the draw ends, no extra call needed.

```bash
curl -X POST http://127.0.0.1:8734/roll/stop
```

## 4. Read these two at the start

| Endpoint | Contents |
|---|---|
| `GET /rules` | All rules: trading mechanics, event table, fees, the complete endpoint list |
| `GET /state` | Current position: equity, holdings, quotes, book depth, event feed |

Once you have these two, you never need to read another Markdown file during the match.

## 5. Settle

```bash
# at the target with positions still open: close everything first, or /quit is refused
curl -X POST http://127.0.0.1:8734/close_all
curl -X POST http://127.0.0.1:8734/quit
```

At or above the target with positions open, `/quit` returns `ok:false` and lists them; call
`/close_all` to bank the profit before exiting. If you never close, the match runs to the
45-minute time-up and the engine force-liquidates it (a give-back then voids the target).
The HTML report is written to `src/data/reports/`.

## Boundaries

- During a match `src/*.py` is sealed and replaced with decoys. What you read is a fake file; executing or importing it writes a cheating flag and ends the match immediately
- Spectators can only answer after you actually ask (`POST /assist/ask`). They cannot message you unprompted, and they cannot place orders for you
- Three asks per match; **pre-match only** (`TM_ASSIST=1`, free). Mid-match paid enabling was removed in v1.2.23 — `/assist/enable` now only returns an error.

## Split documents

`docs/rules.md`, `docs/ai-protocol.md` and `docs/cost-model.md` expand the above for human readers. During a match, the `GET /rules` response is authoritative.
