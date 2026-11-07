# Tokens Trading Market · contestant entry point

One-page startup note. Read this page and you can start a match; the rules come from the HTTP API, so you do not need to read anything under `docs/`.

A match lasts 45 minutes: starting equity **1,000,000 Tokens**, target **2,000,000**. Every quote, event and gap is procedurally generated fiction and has nothing to do with any real market.

## 0. Which Python (hard requirement, do not search)

Use this one interpreter only, **Python 3.14.7**:

```
C:\Users\User\AppData\Local\Programs\Python\Python314\python.exe
```

`run.py` validates the version as its very first action: anything but 3.14 aborts with exit code 2
and prints that exact command. Do not use `where python`, `py -3.12` or `python3` to hunt for another
interpreter — the spectator's GUI widgets and the `.pyc` files are built for 3.14, and any other
version simply cannot start. If the short name is not found, write the full path; do not report
"the environment is broken".

## 1. Clean and reset (do this BEFORE launching)

A leftover save file makes the service resume the previous match — **clean it first**. Both cases
are covered (service still running, or already stopped):

```bash
cd <project dir>

# If the previous service is still running: reset, then shut down
# (/reset wipes everything under data/ except reports/)
curl -s -X POST http://127.0.0.1:8734/reset    >/dev/null 2>&1 || true
curl -s -X POST http://127.0.0.1:8734/shutdown >/dev/null 2>&1 || true

# Belt and braces: delete the save directly when the service is not running
rm -f src/data/session.json
rm -f src/data/.scratchpad.jsonl
rm -rf src/data/_agent
```

PowerShell equivalent:

```powershell
Remove-Item -Force src/data/session.json            -ErrorAction SilentlyContinue
Remove-Item -Force src/data/.scratchpad.jsonl       -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force src/data/_agent         -ErrorAction SilentlyContinue
```

**Never delete `src/data/reports/`** — that is the match archive; every settlement writes a new
file there. When done, `src/data/` should contain only `reports/`.

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
| `TM_TRADER` | Contestant label, format **model-name-thinking-effort-platform**, e.g. `Doubao-1.5-pro-deep-think-Coze`; written verbatim into the report filename and body |
| `TM_EVENTS` | `1` turns on random events (including Black Swan gaps); `0` leaves only the gaps |
| `TM_FR` | `1` enables **Finance Reversal**: 2 borrowings per match |
| `TM_SLOT` | `1` enables the **Slot Machine**: 3 plays per match |
| `TM_ASSIST` | `1` enables **Outside Mercy**: 3 asks to the spectators per match |
| `TM_PORT` | Service port, default `8734` |

## 3. Lock the difficulty

Difficulty is rolled at the start, and `/tick` does not advance until it is locked.

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
