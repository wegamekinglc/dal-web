# DAL Web Operations Reference

Brings up or tears down the two-service web UI that sits on top of the DAL Python public API.

## Contents

- [Platform dispatch](#platform-dispatch)
- [Startup flow](#startup-flow)
- [Shutdown flow](#shutdown-flow)
- [Running tests](#running-tests)
- [Compiled DAL backend](#dal-backend-dal-python)
- [Persistence](#persistence)
- [Troubleshooting](#troubleshooting)

Four launcher scripts handle the actual work — pick by platform:

| Platform          | Start                                                             | Stop (graceful → force)                                                         |
|-------------------|-------------------------------------------------------------------|---------------------------------------------------------------------------------|
| Linux / macOS     | `./scripts/start.sh`                                              | `./scripts/stop.sh` → `./scripts/stop.sh --force`                               |
| Windows (pwsh 7+) | `pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/start.ps1` | `pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/stop.ps1` → add `-Force` |

`scripts/setup-playwright.sh` (one-time frontend e2e browser/runtime setup) has no PowerShell equivalent; run it under bash/git-bash on Windows.

## Platform dispatch

Choose the launcher by platform, not by guess:

- **Windows** — when `pwsh` is on `PATH` (PowerShell 7+) or the session platform is `win32`, use the `.ps1` scripts.
- **Linux / macOS / WSL / git-bash** — otherwise use the `.sh` scripts.

The two families are behaviourally equivalent in ports, health checks, smoke
test, PID/log files, and exit codes. Platform differences are worth remembering:

- **Prerequisites:** the bash start script checks `python3`, `curl`, `grep`,
  `nohup`, and either `ss` or `lsof`; its stopper requires `grep` and `lsof`.
  PowerShell checks `python` and uses native networking/process commands.
- **Log files:** on Linux/macOS each service writes a single merged `.server.log`. On Windows each service writes two files — `.server.log` (stdout) and `.server.log.err` (stderr).
- **Force flag spelling:** `--force` (bash) versus `-Force` (PowerShell). Do not mix them.

## When to use

- **User wants to start the web UI** → run the start script for the current platform.
- **User wants to stop the web UI** → run the stop script for the current platform.
- **User wants to run tests** → the skill can also invoke the test suites directly (see below).

## Startup flow

When the user asks to start the web UI, run the launcher for the current platform:

```bash
./scripts/start.sh                                              # Linux/macOS
```
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/start.ps1  # Windows
```

The script:
1. Verifies prerequisite commands (Python, uv, node, and npm) and enforces
   Python ≥ 3.13. Bash also checks `curl`, `grep`, `nohup`, and either `ss` or
   `lsof`; the bash stopper requires `grep` and `lsof`. The committed frontend
   toolchain requires Node.js `^20.19.0` or `>=22.12.0`.
2. Reads the backend port from `frontend/vite.config.ts` (currently `:8001`)
3. Checks that both ports are free
4. Runs `uv sync --inexact` in `backend/` so the locally installed
   native `dal` package is preserved
5. Starts uvicorn in the background (PID saved to `backend/.server.pid`)
6. Waits for `/api/health` to respond (up to 20s)
7. Runs `npm install` in `frontend/`
8. Starts vite in the background (PID saved to `frontend/.server.pid`)
9. Waits for `:5173` to respond (up to 30s)
10. Smoke-tests the proxy (frontend → backend)
11. Prints the URLs

Logs go to `.server.log` next to each server (plus a separate `.server.log.err` for stderr on Windows).

## Shutdown flow

When the user asks to stop the web UI, run the stopper for the current platform:

```bash
./scripts/stop.sh                  # Linux/macOS; add --force to escalate
```
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/stop.ps1   # Windows; add -Force to escalate
```

The script:
1. Reads the backend port from `vite.config.ts`
2. Kills the backend by PID (from `.server.pid`). On Windows it walks the PID's process tree first so child workers (uvicorn `--reload` worker, node/vite children) are terminated.
3. Kills the frontend the same way
4. Falls back to a port-based kill if a child still holds the socket after the PID kill
5. Removes PID files
6. Verifies both ports are free

If a service refuses to stop within 5s, the script warns. Re-run with `--force` (bash) or `-Force` (PowerShell) to escalate to a hard kill.

## Running tests

If the user asks to run tests after starting the UI:

```bash
# Backend tests (pytest, uses a fake dal module)
(cd backend && uv run pytest)

# Frontend type-check + production build
(cd frontend && npm run build)

# Frontend e2e smoke tests (Playwright; starts/stops the web UI itself)
./scripts/setup-playwright.sh   # one-time browser/runtime setup
(cd frontend && npm run test:e2e)
```

## DAL backend (dal-python)

The backend imports the compiled `dal` package (dal-python pybind11 bindings) directly -- there is no pure-Python fallback. `dal-python>=2026.8.14` is a declared backend dependency, so `uv sync` installs the published wheel from PyPI with no C++ build:

```bash
cd backend && uv sync
```

To develop against an unreleased DAL build, install from a DAL source checkout into the backend environment instead:

```bash
cd backend
uv pip install /path/to/Derivatives-Algorithms-Lib/dal-python \
  "--config-settings=cmake.define.DAL_INSTALL_PREFIX=/path/to/build/stage/<platform-preset>"
```

The start scripts run `uv sync --inexact`, which preserves such a manually installed local binding. Preflight the import either way:

```bash
uv run --no-sync python -m app.native_runtime
```

See `README.md#native-dal-package` for the full contract.

The start scripts inherit the caller's environment, so once `dal` is importable just run them directly:

```bash
./scripts/start.sh
```

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/start.ps1
```

The pytest suite uses a fake `dal` module (see `backend/tests/conftest.py`), so `uv run pytest` needs no C++ build.

## Persistence

The backend persists all entities (products, models, trades, portfolios, valuation results) to a SQLAlchemy database behind the `Store` seam. The start scripts pass the caller environment through, so the relevant variables work out of the box:

| Variable               | Default                               | Meaning                                                               |
|------------------------|---------------------------------------|-----------------------------------------------------------------------|
| `DAL_WEB_DB_URL`       | `sqlite:///<backend>/.data/dalweb.db` | SQLAlchemy URL for the DB. Point at Postgres/MySQL to switch.         |
| `DAL_WEB_STORE`        | unset                                 | `memory` bypasses the DB and uses the legacy in-memory store.         |
| `DAL_WEB_AUTO_MIGRATE` | unset                                 | `1` runs `alembic upgrade head` on startup; otherwise `create_all()`. |

Default SQLite file is gitignored under `backend/.data/`. To run the Alembic migrations by hand: `cd backend && uv run alembic upgrade head`.

## Troubleshooting

- **Port already in use** — run the stop script for your platform first. For
  manual diagnosis, use `sudo fuser -k <port>/tcp` on Linux; on macOS, find
  listeners with `lsof -tiTCP:<port> -sTCP:LISTEN` and pass the returned PIDs
  to `kill`; on Windows, use
  `Get-NetTCPConnection -LocalPort <port> -State Listen` then
  `Stop-Process -Id <pid> -Force`.
- **Backend fails to start** — check `backend/.server.log` (and `.server.log.err` on Windows). Common causes: missing dependencies, port conflict, Python version mismatch.
- **Frontend fails to start** — check `frontend/.server.log` (and `.server.log.err` on Windows). Common causes: port conflict, node_modules out of date (try `rm -rf node_modules && npm install`).
- **Proxy not forwarding** — verify `frontend/vite.config.ts` has the correct `proxy.target` port, and that the backend is actually running.

## Reference

For full details on the web UI architecture, see `README.md`.
