It was expected behavior in the code, but a bug in my demo instructions.

- `smoke_test.py` creates private services on random ports with a separate event store.
- `python_agent_smoke_test.py` does the same, including a temporary fake LLM.
- Their events disappear when each test finishes.
- `run-negative-cases.bat` calls the live connector on port `8765`, so those events appear on your dashboard.

I corrected this and added live-dashboard drivers.

## Correct live POC sequence

### Window 1 — Start dashboard

```powershell
cd C:\Users\User\Downloads\Laptop_BAP_CCD\laptop_bap_demo\local_poc
py -3 run_demo.py
```

Keep `http://127.0.0.1:8765` visible.

### Window 2 — Positive, approval, and deny cases

```powershell
cd C:\Users\User\Downloads\Laptop_BAP_CCD\laptop_bap_demo\local_poc
run-live-dashboard-demo.bat
```

This now generates visible dashboard events for:

- Development read: allow and execute.
- Development write: require approval, then execute.
- Delete: deny without execution.
- Production read: deny without execution.

### Show the Python agent lifecycle

```powershell
run-live-python-agent-demo.bat
```

This uses a temporary deterministic LLM and writes the full agent lifecycle to the live dashboard. It does not require port 8080.

### Show negative grant cases

```powershell
run-negative-cases.bat
```

This generates missing-grant and fictitious-grant denial evidence.

## Isolated regression tests

These still intentionally do not affect the dashboard:

```powershell
py -3 smoke_test.py
py -3 python_agent_smoke_test.py
```

They are CI-style tests, not presentation drivers.

I tested both new live commands successfully, and their events appeared through the live connector. The corrected instructions are in [local_poc/README.md](C:/Users/User/Downloads/Laptop_BAP_CCD/laptop_bap_demo/local_poc/README.md).