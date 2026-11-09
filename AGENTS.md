# Tokens Trading Market · contestant entry point

One-page startup note. Read this page and you can start a match; the rules come from the HTTP API, so you do not need to read anything under `docs/`.

A match lasts 45 minutes: starting equity **1,000,000 Tokens**, target **2,000,000**. Every quote, event and gap is procedurally generated fiction and has nothing to do with any real market.

## 0. Which Python (hard requirement, do not search)

**Python 3.14.7** — the spectator's GUI widgets and the `.pyc` files are built for 3.14. The pinned path on this machine is:

```
C:\Users\User\AppData\Local\Programs\Python\Python314\python.exe
```

`run.py` validates the version as its very first action: anything but 3.14 aborts with exit code 2
and prints that exact command. Do not use `where python`, `py -3.12` or `python3` to hunt for another
interpreter — the spectator's GUI widgets and the `.pyc` files are built for 3.14, and any other
version simply cannot start. If the short name is not found, write the full path; do not report
"the environment is broken".

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
  nohup "C:/Users/User/AppData/Local/Programs/Python/Python314/python.exe" run.py > run.log 2>&1 &

# readiness check: startup takes 3-8 seconds, a fixed sleep produces false failures
for i in $(seq 1 30); do
  curl -sf http://127.0.0.1:8734/health >/dev/null 2>&1 && break
  sleep 1
done
```

**The spectator is mandatory, not optional.** Since v1.0.11, `run.py`, `run.py server` and
double-clicking `Start Match.bat` behave identically: all three open the read-only spectator.
A human must be able to watch equity, holdings and the activity feed live.

- Do not start `run.py spectator` yourself to "add" a window — a normal start already has one
- Only `--headless` suppresses the window, and only for environments with no desktop (CI, containers)
- With the wrong Python, `run.py` exits with code 2 instead of failing later on `bad magic number`

| Variable | Meaning |
|---|---|
| `TM_TRADER` | Contestant label, format **model-name-thinking-effort-platform**, e.g. `Doubao-1.5-pro-deep-think-Coze`; written into the report filename and body after whitelist filtering |
| `TM_EVENTS` | `1` turns on random events (including Black Swan gaps); `0` leaves only the gaps; **defaults to `1` when unset** |
| `TM_FR` | `1` enables **Preferred Financing**: no cap on borrowings, target-uplift floor drops to 0.01% |
| `TM_SLOT` | `1` enables the **Slot Machine**: 3 plays per match |
| `TM_ASSIST` | `1` enables **Outside Mercy**: 3 asks to the spectators per match |
| `TM_PORT` | Service port, default `8734` |
| `TM_IDLE_ABORT` | Minutes without a write call before the match settles itself, default `12`, `0` disables |

## 3. Lock the difficulty

Difficulty is rolled at the start; before it is locked `/fastforward` is refused too
(`Session has not started, confirm the rules first`).

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
curl -X POST http://127.0.0.1:8734/quit
```

The HTML report is written to `src/data/reports/`.

## Boundaries

- During a match `src/*.py` is sealed and replaced with decoys. What you read is a fake file; executing or importing it writes a cheating flag and ends the match immediately
- Spectators can only answer after you actually ask (`POST /assist/ask`). They cannot message you unprompted, and they cannot place orders for you
- Three asks per match; enabling it mid-match costs 500,000 cash and is the contestant's own decision — the spectator window has no enable control

## Split documents

`docs/rules.md`, `docs/ai-protocol.md` and `docs/cost-model.md` expand the above for human readers. During a match, the `GET /rules` response is authoritative.
