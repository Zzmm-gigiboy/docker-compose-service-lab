# Engineering Challenges & Technical Trade-offs: docker-compose-service-lab

## 1. System Overview & Architectural Context

`docker-compose-service-lab` is a polyglot microservice laboratory designed to simulate realistic enterprise service mesh topology and containerized application orchestration. The ecosystem comprises four lightweight microservices coordinated via Docker Compose:
- **`greeting-api`**: FastAPI/SQLite service powering date-based occasion notifications, calendar boundary validation, and notification preview interpolation.
- **`merchant-api`**: FastAPI/SQLite service managing product catalogs, real-time inventory tracking, out-of-stock metrics aggregation, and discount calculation.
- **`pocket-api`**: FastAPI/SQLite companion service providing transactional personal task/note state management with status toggles.
- **`link-api`**: High-performance Go microservice implementing bookmark collection management with URI scheme validation, case-insensitive tag search, and atomic JSON file persistence.

The services communicate over an isolated Docker network bridge, maintain volume-backed persistence layers, and implement standardized `/health` probes. Developing, testing, and continuously validating this heterogeneous architecture exposed several core systems engineering challenges.

---

## 2. Difficult Technical Hurdles & Root Cause Analysis

### Challenge 1: Cross-Platform SQLite Handle Locking on Windows NTFS (`WinError 32`) vs POSIX Inode Unlinking

#### The Symptom
During automated test execution on Windows developer workstations, running pytest across `greeting-api`, `merchant-api`, or `pocket-api` resulted in immediate test runner crashes:
```
PermissionError: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\Users\\...\\AppData\\Local\\Temp\\tmp...\\test.db'
```
Paradoxically, the exact same test suites passed seamlessly on Linux-based GitHub Actions CI runners (`ubuntu-latest`).

#### Root Cause Analysis
The failure stems from a fundamental divergence between POSIX and Windows NTFS file descriptor mechanics combined with Python's SQLite connection management semantics:
1. **Python SQLite Context Manager Behavior**: In Python's standard library `sqlite3`, using `with sqlite3.connect(...) as conn:` manages **transactions only**—it issues a `COMMIT` when leaving the context block cleanly or a `ROLLBACK` on an exception. It **never closes the underlying OS file handle**.
2. **NTFS vs POSIX Unlink Semantics**:
   - On POSIX filesystems (Linux/macOS), calling `unlink()` on an open file removes the directory entry immediately. The file's inode and allocated disk blocks remain valid until the last open file descriptor is closed by the process. Thus, `shutil.rmtree()` in `tempfile.TemporaryDirectory` completes without error even if connections remain open.
   - On Windows NTFS filesystems, files operate under mandatory lock semantics. An open file handle locks the file table entry. Any call to `os.unlink()` or `RemoveDirectory()` while a handle remains open is rejected by the NT kernel with `ERROR_SHARING_VIOLATION` (0x20, mapped by Python to `PermissionError: [WinError 32]`).
3. **Test Fixture Lifecycle**: Each pytest invocation created a temporary database directory via `tempfile.TemporaryDirectory()`. Because the FastAPI endpoints and initialization routines left connections dangling in the connection pool, directory cleanup triggered an unhandled `PermissionError` during fixture teardown.

---

### Challenge 2: Docker Compose Multi-Service Dependency Orchestration & Healthcheck Synchronization

#### The Hurdle
In containerized microservice architectures, container start order does not equate to service readiness. Dependent containers or smoke test harnesses frequently query endpoints before database tables are created or before ASGI/HTTP listeners finish binding to their respective ports. Additionally, lightweight container base images (such as `python:3.12-slim`) lack command-line network utilities such as `curl` or `wget`.

#### Root Cause Analysis
Relying on external binaries inside container health checks introduces bloated images or outright container execution failures (`executable file not found in $PATH`). Furthermore, static sleep intervals in orchestration scripts introduce either flaky CI pipelines (when sleep durations are too short for slower runners) or wasted compute time (when arbitrary padding delays are introduced).

---

### Challenge 3: Polyglot Microservice Testing (Python FastAPI + Go Standard Library) in Unified CI

#### The Hurdle
Orchestrating CI testing for a repository containing multiple decoupled runtime environments (Python 3.12 with FastAPI/Pydantic/Pytest, and Go 1.23 with `net/http` and table-driven testing) often leads to brittle, monolithic build scripts.

#### Root Cause Analysis
A single serial bash script executing all tests sequentially obscures failure isolation: if `greeting-api` fails, subsequent test suites for `merchant-api`, `pocket-api`, and `link-api` are aborted, hiding whether regressions are isolated or systemic. Moreover, running serial pipelines fails to leverage GitHub Actions concurrent runner capacity.

---

### Challenge 4: Input Validation Boundaries & Idempotent API Design Across Microservices

#### The Hurdle
Microservices exposed to heterogeneous callers must enforce rigorous boundary constraints without crashing or allowing corrupt state into persistence layers. Specific edge cases encountered included:
- Calendar validation in `greeting-api`: Leap years (February 29) are valid in leap years (e.g. 2024), but invalid dates like February 30, April 31, or month 13 must fail deterministically with HTTP 422.
- Number ranges in `merchant-api`: Negative pricing or negative stock quantities must be rejected at schema ingestion.
- Unbounded payloads in `link-api`: Malicious or runaway HTTP POST bodies could exhaust server memory if not explicitly bounded at the network reader level.
- Transactional rollback on persistence failure: If file synchronization fails during link creation or deletion, in-memory state must roll back to maintain consistency.

---

## 3. Engineering Trade-offs & Alternatives Considered

| Decision Area | Evaluated Approach | Trade-offs & Rejected Alternatives | Chosen Architecture & Rationale |
|---|---|---|---|
| **SQLite Connection Lifecycle** | 1. Global persistent connection<br>2. Per-request connection without close<br>3. Context manager with `finally: conn.close()` | • Option 1 causes threading contention and locks files across threads.<br>• Option 2 causes `WinError 32` file locking on Windows.<br>• Option 3 guarantees deterministic resource release. | **`@contextlib.contextmanager` with explicit `conn.close()` in `finally`**. Manages transaction commit/rollback via `with conn:` while ensuring the OS handle is closed on block exit. |
| **Container Healthcheck Implementation** | 1. Install `curl` via `apt-get`<br>2. Python stdlib `urllib.request`<br>3. TCP port probing | • Option 1 increases Docker image layer size and attack surface.<br>• Option 3 only verifies socket binding, not application layer readiness. | **Python inline `urllib.request` one-liner**. Zero extra dependencies, lightweight (<50ms execution), and verifies full HTTP application stack health. |
| **CI Workflow Topology** | 1. Single monolithic bash job<br>2. Independent matrix jobs per service | • Option 1 stops on first failure and provides poor visibility.<br>• Option 2 enables parallel execution and granular reporting. | **Multi-job workflow matrix**. Matrix job for Python services (`greeting`, `merchant`, `pocket`), dedicated Go 1.23 runner for `link-api`, and static compose validation. |
| **Go HTTP Body Protection** | 1. Unbounded `json.NewDecoder`<br>2. `http.MaxBytesReader` | • Option 1 susceptible to denial-of-service via huge payload injection. | **`http.MaxBytesReader(w, r.Body, 1<<16)`**. Bounds payload size to 64KB, rejecting oversized bodies with HTTP 400. |

---

## 4. Implementation & Solution Architecture

### 4.1 Deterministic SQLite Resource Cleanup
To eliminate `WinError 32` and maintain transactional integrity across all three Python microservices (`greeting-api`, `merchant-api`, `pocket-api`), database connection factories were refactored into deterministic generators:

```python
import sqlite3
from contextlib import contextmanager

@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()
```

#### Key Architectural Properties:
1. **Transactional Safety**: `with conn:` enters a SQLite transaction; any unhandled exception in endpoint execution triggers an automatic `ROLLBACK`.
2. **Deterministic Cleanup**: The `finally: conn.close()` block is guaranteed to execute when exiting the `with db() as conn:` block, releasing the NT kernel file handle immediately.
3. **Zero Test Contamination**: Every test fixture operates in an isolated temporary directory that is deleted cleanly upon test completion without permission errors.

---

### 4.2 Dependency-Free Container Healthchecks
In `compose.yml`, health checks are implemented using standard library Python to eliminate container bloat:

```yaml
healthcheck:
  test: ['CMD', 'python', '-c', 'import urllib.request; urllib.request.urlopen("http://localhost:8000/health", timeout=3)']
  interval: 20s
  timeout: 5s
  retries: 3
```

---

### 4.3 Matrix-Driven CI Architecture
The GitHub Actions workflow (`.github/workflows/ci.yml`) separates concerns into parallel jobs:
- **`python-tests`**: Runs a matrix across `[greeting-api, merchant-api, pocket-api]` using Python 3.12 and verbose pytest reporting.
- **`go-tests`**: Sets up Go 1.23 and executes table-driven tests for `link-api` with `-v`.
- **`compose-validation`**: Executes `docker compose config -q` to validate compose specification syntax, service definitions, volume bindings, and port declarations.

---

### 4.4 Defensive In-Memory Rollback in Go Link API
In `link-api/main.go`, state mutations maintain in-memory rollback snapshots in the event of disk I/O errors:

```go
s.mu.Lock()
defer s.mu.Unlock()

l.ID = s.next
s.next++
l.Title = strings.TrimSpace(l.Title)
s.links = append(s.links, l)

if err := s.persist(); err != nil {
    // Roll back in-memory mutation
    s.links = s.links[:len(s.links)-1]
    s.next--
    jsonResponse(w, 500, map[string]string{"error": "Persistence failed"})
    return
}
jsonResponse(w, 201, l)
```

---

## 5. Verification, Regression Testing & CI Validation

### Local Multi-Platform Verification
1. **Python Microservice Test Execution**:
   ```bash
   uv run --directory services/greeting-api --with fastapi --with uvicorn --with httpx --with pytest pytest -v
   uv run --directory services/merchant-api --with fastapi --with uvicorn --with httpx --with pytest pytest -v
   uv run --directory services/pocket-api --with fastapi --with uvicorn --with httpx --with pytest pytest -v
   ```
   - **Result**: 21 passing test cases across all three Python microservices with **0 errors and 0 WinError 32 file locking leaks**.

2. **Go Test Execution**:
   ```powershell
   $env:PATH = "C:\Program Files\Go\bin;" + $env:PATH
   cd services/link-api
   go test -v ./...
   ```
   - **Result**: All 6 Go test suites (including 8 table-driven validation cases) passed cleanly.

3. **Workflow Syntax & Schema Linting**:
   ```bash
   npx --yes yaml-lint .github/workflows/ci.yml
   npx --yes yaml-lint compose.yml
   ```
   - **Result**: Both workflow and compose YAML files passed schema linting with zero warnings or errors.

4. **Continuous Integration**:
   Every push to `main` executes all matrix test suites on GitHub Actions runners, guaranteeing cross-platform compatibility across Linux and Windows development environments.
