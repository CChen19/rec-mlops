# Quick Start Guide

Run the following commands **exactly in order** (each step has been verified).


## Phase 0: Local Development Setup (Windows)

This section documents fixes required to run the stack on Windows. All changes live on the `refactor/slim-down` branch.

### Port conflicts (Windows reserved ranges)

Windows reserves certain port ranges for Hyper-V / WSL. The following host-port mappings were changed in `docker-compose.yml`:

| Service | Original | New | Reason |
|---------|----------|-----|--------|
| Redis | 6379:6379 | 6550:6379 | Reserved range 6333–6432 |
| Spark master (RPC) | 7077:7077 | 7600:7077 | Reserved range 7001–7100 |
| Locust UI | 8089:8089 | 8190:8089 | Port in use by iCloudDrive |

### Spark / Java compatibility

PySpark 3.4 requires Java 8 or 11. Java 17+ (and 21, which ships with recent Windows JDKs) removed the `DirectByteBuffer` constructor that Spark relies on, causing a hard crash at startup.

**Fix**: The `RecommendationEngine.__init__` Spark session creation is now wrapped in a `try/except`. If the JVM cannot start, `self.spark = None` and the engine falls back to in-memory sample data automatically. The actual SVD/NMF recommendation logic does not use Spark at runtime.

Additionally, `spark.jars.ivy` was hardcoded to `/tmp/.ivy2` (a Unix path). It now uses `tempfile.gettempdir()` so it resolves to a valid absolute path on Windows.

### MLflow tracking URI

`config/config.yaml` previously used `http://mlflow:5000` (Docker-internal hostname). Changed to `http://localhost:5000` for local development.

### Starting the stack locally

```bash
# 1. Start all infrastructure services
docker compose up -d

# 2. Start the recommendation API (using the rec_mlops conda env)
conda activate rec_mlops
python -m uvicorn src.api.recommendation_api:app --host 0.0.0.0 --port 8000

# 3. Verify
curl http://localhost:8000/health
# Expected: {"status":"healthy","active_models":[...],"uptime_seconds":...}
```

Service URLs after startup:

| Service | URL |
|---------|-----|
| Recommendation API | http://localhost:8000 |
| Grafana | http://localhost:3000 |
| Prometheus | http://localhost:9090 |
| MLflow | http://localhost:5000 |
| Spark Master UI | http://localhost:8080 |
| Locust UI | http://localhost:8190 |


## Phase 1: Model Registry & Quality Gates

### Steps:

```bash
# Start infrastructure and API first (see Phase 0), then:

# Trigger a hot-reload to pull the latest Production model from MLflow
curl -s -X POST http://localhost:8000/admin/reload-models | python -m json.tool
```

Expected response (example):

```json
{
  "status": "success",
  "message": "Models reloaded from Production",
  "current_state": {
    "Recommendation_SVD": {
      "version": "1",
      "stage": "Production",
      "loaded_at": "2025-12-04T08:88:88.888888"
    }
  }
}
```


## Phase 3: Quality Assurance & Automation

**Install all dev tooling:**

```bash
make install-dev
```

Automatically creates a virtualenv, installs every tool, and configures the Git hooks.

**Activate the virtual environment:**

```bash
source venv_py313/bin/activate
```

**Code quality checks (for daily work):**

```bash
make ci              # lint + type-check
make format          # format code with Black + isort
make lint            # run Flake8 + Bandit
make type-check      # run MyPy
make pre-commit      # execute every pre-commit hook
```

**Load testing:**

```bash
make load-test              # start the Locust UI (http://localhost:8190)
make load-test-headless     # headless run (5 min, 100 users)
```

**Unit tests (requires the full dependency stack):**

```bash
make ci-test         # CI workflow + unit tests
make test            # unit tests only
make test-smoke      # smoke tests
```

**Locust Monitoring:**

Under a high load of 500, our system maintains a P95 latency of under 6 milliseconds, which ensures a smooth experience for our users.

![Locust Monitoring](./images/Locust.jpg)

**Grafana Dashboard Monitoring:**

Including API Error Rate (%), In-flight Requests, API Latency (p95), API Throughput (Requests Per Second)

![Grafana Monitoring](images/Grafana.jpg)


## Phase 3's Tooling

| Tool | Purpose | Config File |
|------|---------|-------------|
| Black | Code formatting | pyproject.toml |
| isort | Import sorting | pyproject.toml |
| Flake8 | Code linting | .flake8 |
| MyPy | Static type checking | pyproject.toml |
| Bandit | Security scanning | pyproject.toml |
| pytest | Unit testing | pyproject.toml |
| pre-commit | Git hooks | .pre-commit-config.yaml |
| Locust | Load testing | tests/locustfile.py |


## Phase 4: CI/CD Pipeline

In this phase, the entire MLOps stack becomes fully automated through GitHub Actions, achieving zero-touch testing and deployment.

### Steps: 

1. Add or update locally inside the project:
   
```bash
.github/workflows/ci-cd.yml
```

2. Commit your changes
 
```bash
git add .
git commit -m "feat: update recommendation engine"
```

3. Push to GitHub and this automatically triggers the full CI/CD workflow:

```bash
git push origin main
```



