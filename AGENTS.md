# Tokens Trading Market · contestant entry point

One-page startup note. Read this page and you can start a match; the rules come from the HTTP API, so you do not need to read anything under `docs/`.

A match lasts 45 minutes: starting equity **1,000,000 Tokens**, target **2,000,000**. Every quote, event and gap is procedurally generated fiction and has nothing to do with any real market.

## 0. Which Python

Use `python`. The requirement is **3.10 or newer**; no minor version is mandated.

```bash
python -c "import sys, tkinter; print(sys.version)"
```

If that prints a version, you are ready — nothing needs installing.

Two traps worth naming:

- `py -3.12` or `py -3.13` may answer with a "get it from the Microsoft Store" prompt on these machines. That means the version is **not installed**, not that the environment is broken. Go back to `python`
- `python: ["3.11", "3.13"]` in `.github/workflows/ci.yml` is the CI **test matrix**, not a runtime requirement. Do not infer a version from it

## 1. Start

```bash
cd <project directory>

TM_TRADER="<model-name-thinking-effort-platform>" \
TM_EVENTS=1 TM_FR=1 TM_SLOT=1 TM_ASSIST=1 \
  nohup python run.py server > run.log 2>&1 &

# readiness check: startup takes 3-8 seconds, a fixed sleep produces false failures
for i in $(seq 1 30); do
  curl -sf http://127.0.0.1:8734/health >/dev/null 2>&1 && break
  sleep 1
done
```

`run.py server` is headless. `python run.py` without `server` also opens a read-only spectator window, and on a machine with no desktop the window creation failure takes the whole process down.

| Variable | Meaning |
|---|---|
| `TM_TRADER` | Contestant label, format **model-name-thinking-effort-platform**, e.g. `Doubao-1.5-pro-deep-think-Coze`; written verbatim into the report filename and body |
| `TM_EVENTS` | `1` turns on random events (including Black Swan gaps); `0` leaves only the gaps |
| `TM_FR` | `1` enables **Finance Reversal**: 2 borrowings per match |
| `TM_SLOT` | `1` enables the **Slot Machine**: 3 plays per match |
| `TM_ASSIST` | `1` enables **Outside Mercy**: 3 asks to the spectators per match |
| `TM_PORT` | Service port, default `8734` |

## 2. Lock the difficulty

Difficulty is rolled at the start, and `/tick` does not advance until it is locked.

```bash
curl -X POST http://127.0.0.1:8734/roll/stop
```

## 3. Read these two at the start

| Endpoint | Contents |
|---|---|
| `GET /rules` | All rules: trading mechanics, event table, fees, the complete endpoint list |
| `GET /state` | Current position: equity, holdings, quotes, book depth, event feed |

Once you have these two, you never need to read another Markdown file during the match.

## 4. Settle

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
