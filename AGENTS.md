# Tokens Trading Market · contestant entry point

A match lasts 45 minutes after the difficulty lock. Initial capital is 1M Tokens and the base target is 2M. Read the current target from `GET /state`.

## Start the service

Use Python 3.14 from the project root. The install path and patch number are flexible. Run this PowerShell example in its own terminal, replacing the contestant tag with the model, reasoning effort and platform.

```powershell
$env:TM_TRADER = 'GLM-5.3-high-Cursor'
$env:TM_EVENTS = '1'
$env:TM_FR = '1'
$env:TM_SLOT = '1'
$env:TM_ASSIST = '1'
python run.py
```

`launchers/AI Start.bat` starts unattended on Windows. `launchers/Start Match.bat` is the confirmation launcher. Normal startup opens a spectator. Use `--headless` for a session without a desktop. If you set `TM_PORT`, substitute that port in the HTTP commands below.

## Wait, answer the challenge, lock difficulty

Poll `GET /health` until ready, then read `GET /state`. While `challenge.stage` is `ask`, call `POST /challenge/accept` or `POST /challenge/decline`. If there is no answer within 75 seconds, the game declines automatically.

The 30-second difficulty draw starts after the answer. Wait for the draw or call `POST /roll/stop`. Confirm `rolled:true` before trading. The following PowerShell example declines challenges in a fresh match.

```powershell
curl.exe http://127.0.0.1:8734/health
curl.exe -X POST http://127.0.0.1:8734/challenge/decline
curl.exe -X POST http://127.0.0.1:8734/roll/stop
curl.exe http://127.0.0.1:8734/state
```

## Trade and settle

Use the [HTTP protocol](docs/ai-protocol.md), [game rules](docs/rules.md) and [cost model](docs/cost-model.md). `GET /rules` provides the in-game rule summary. Use API data and your own analysis during a competition. Send notes through `POST /scratchpad`. The local scratchpad script is one of the files sealed during a match.

Check state before `POST /quit`. At or above target with open positions, close them first and check the resulting equity. **A rejected `/quit` leaves the match running.** Check the response and the report under `src/data/reports/HTML Reports/`.

## Recover after an interrupted match

Make sure the match process for this directory has stopped. To resume, keep the saves and restart from the same directory. See [save recovery](docs/ai-protocol.md#save-recovery). To discard the match, run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./tools/deep-clean.ps1` from the project root. It removes the session saves and preserves past reports.
