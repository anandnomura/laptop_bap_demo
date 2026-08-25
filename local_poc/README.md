# Local Python proof of concept

This directory preserves the original Python-only BAP demonstration. It is useful for learning and comparison; it is not the production-shaped architecture. All commands below start from this directory:

```powershell
cd local_poc
```

## Run the POC

```powershell
py -3 run_demo.py
```

Dashboard: `http://127.0.0.1:8765`

## Live dashboard demonstrations

With `run_demo.py` still running, use a second terminal:

```powershell
run-live-dashboard-demo.bat
run-live-python-agent-demo.bat
run-negative-cases.bat
```

All three commands call the live connector at `127.0.0.1:8765`, so their events appear on the visible dashboard. The live Python-agent driver uses a deterministic temporary fake LLM; it does not require port 8080.

## Isolated smoke tests

```powershell
py -3 smoke_test.py
py -3 python_agent_smoke_test.py
```

These tests intentionally create private services on random ports. They prove regression behavior but do **not** write to the live dashboard on port 8765.

## Negative cases

With `run_demo.py` running:

```powershell
run-negative-cases.bat
```

This demonstrates missing-grant, fictitious-grant, destructive-action, production-resource, and direct-resource denial.

## Local LLM and Claude Code

Run the OpenAI-compatible model on `127.0.0.1:8080`, then:

```powershell
start-ccbridge.bat
test-local-claude.bat
start-local-claude.bat
```

The bridge listens on `127.0.0.1:4080`. Use `tools/db_client.py` with forward slashes when asking Claude to execute a command.

## Python agent

```powershell
start-python-agent-demo.bat
```

## Stakeholder demo

1. Start `py -3 run_demo.py` and keep the dashboard visible.
2. Run `run-live-dashboard-demo.bat` to show read, approval-required write, delete deny, and production deny on the dashboard.
3. Run `run-live-python-agent-demo.bat` to show the complete agent lifecycle on the same dashboard.
4. Run `run-negative-cases.bat` while watching missing and fictitious grant denials.
5. Explain that this POC uses local HTTP and Python hooks; the active enterprise design is in `..\enterprise_demo`.

## Stop

```powershell
stop-demo.bat
```
