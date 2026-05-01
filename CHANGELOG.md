# Changelog

All significant changes to this project are documented here.


## [Unreleased] - Phase 5: Simplification (Portfolio Refactor)

### Why this phase exists

The original team project was built to demonstrate breadth — A/B testing, Prefect orchestration, PySpark Streaming, Delta Lake, Spark ML pipelines. After the course ended, running the full stack locally required Java 8/11 (incompatible with the Java 21 that ships on modern Windows), a working Hadoop native library, and ~10 Docker containers just to get a health check. The complexity-to-value ratio for a portfolio piece was poor.

This phase strips the stack down to what is actually defensible in an interview: the sklearn matrix factorization models, the MLflow registry, the FastAPI serving layer, and the Prometheus/Grafana monitoring.

### What was removed and why

| Component | Reason for removal |
|-----------|-------------------|
| **A/B testing** (`src/experiments/`) | Statistically sound but entirely mocked — no real traffic split, no real significance test. Harder to defend than to remove. |
| **Prefect pipelines** (`src/pipelines/`) | Adds a scheduler dependency and a UI service for what is essentially a cron job wrapper around existing training code. Removed the Prefect container from `docker-compose.yml`. |
| **PySpark / Delta Lake** (`pyspark`, `delta-spark`) | Java 21 incompatibility breaks the JVM on every modern Windows machine. The actual ML (SVD, NMF) never used Spark at runtime — it was only used to read a flat file. Replaced with `pd.read_csv`. |
| **Spark Streaming feature processor** | Entire `feature_processor.py` was PySpark Structured Streaming + Spark ML. Rewritten as a kafka-python consumer with pandas batch processing and Redis feature writes — same behaviour, no JVM. |
| **spark-master / spark-worker containers** | Removed from `docker-compose.yml`. Cuts cold-start time from ~3 min to ~30 s. |
| **`src/init_delta_tables.py`** | Only existed to seed Delta Lake tables. No longer needed. |
| **`hydra-core`** | Used in zero production code paths; config is already handled by plain PyYAML. |

### What was kept (and why it stays)

- **MLflow Model Registry** — version control and hot-reload of Production models is genuinely useful and easy to demo.
- **Kafka + Zookeeper** — `feature_processor.py` still consumes from Kafka; the streaming architecture remains intact.
- **Postgres** — MLflow backend store; removing it would break model registry persistence.
- **Prometheus + Grafana** — the Grafana dashboard and P95 latency screenshots are resume material; keeping them costs nothing.
- **sklearn TruncatedSVD + NMF** — the actual recommendation logic; unchanged.

### Key technical decisions

- Data layer: Delta Lake → `pd.read_csv("data/sample_interactions.csv")`. At this dataset scale (hundreds of users, hundreds of items) pandas is faster, has zero dependencies, and is trivially reproducible.
- Feature processing: PySpark Structured Streaming → kafka-python consumer loop. Same micro-batch pattern, no JVM, sklearn PCA kept for offline dimensionality reduction.
- Fallback training: `n_components` is now capped to `min(config_value, matrix_features)` to prevent sklearn ValueError when config overspecifies factors for small datasets.
- Redis port: host mapping corrected to 6550 (Docker remaps from Windows reserved range).


## [Unreleased] - MLOps Transformation Phases 1 & 2

### 🚀 Major Features
Converted the standalone recommendation scripts into a fully containerized, orchestrated, production-grade MLOps platform.

- **Model registry**: Added **MLflow Model Registry** so we can version-control models and manage their lifecycle across Staging and Production stages.
- **Model CI/CD**: Implemented metric-based "auto-promotion" plus API hot reload, enabling zero-downtime updates.
- **Containerization**: Moved Spark, the API, and MLflow tracking into Docker containers to eliminate local dependency drift.

### 🏗️ Infrastructure Changes
- **`docker-compose.yml`**:
    - Swapped the `kafka` and `zookeeper` images to `bitnamilegacy` to recover from upstream pull-policy changes.
    - Configured `mlflow` with artifact serving (proxy mode) bound to `0.0.0.0`, fixing cross-container permissions and access issues.
    - Updated every volume mount so the repo root maps to `/app` inside each container for instant code sync.

### 💻 Code Modifications

#### 1. Model Training (`src/models/train_models.py`)
- **Delta Lake support**: Introduced `configure_spark_with_delta_pip` and set the Ivy cache to `/tmp/.ivy2`, solving the container `ClassNotFoundException` for Delta dependencies.
- **Better data handling**: Added `drop_duplicates` during loading to avoid pivot failures caused by duplicate samples.
- **MLflow integration**:
    - Uses `infer_signature` to capture model input/output schema.
    - Refactored return values so each training call provides a `run_id` for downstream registration.

#### 3. Serving Engine (`src/models/recommendation_engine.py`)
- **Spark configuration parity**: Mirrored the training Spark settings so inference can read the same Delta tables.
- **Model loading**:
    - Prefer loading from the MLflow Registry `Production` stage.
    - Added a fallback path that retrains locally if no Production model exists.
- **Environment awareness**: Prioritizes the `MLFLOW_TRACKING_URI` env var to fix container networking issues.

#### 4. API Service (`src/api/recommendation_api.py`)
- **Hot reload endpoint**: Added `POST /admin/reload-models` so the API can pull the latest Production model without a restart.
- **Startup resilience**: Hardened the `lifespan` logic with better exception handling when MLflow is temporarily unavailable.

#### 5. Utility Scripts
- **New `src/init_delta_tables.py`**: Provides a container-friendly data initializer so we can avoid local Windows Hadoop/Java setup pain.

### 🐛 Bug Fixes
- **SVD dimension mismatch**: Increased the sample dataset item count (5 → 50) to avoid failing when `n_components=10` exceeds available features.
- **Connection refused**: Replaced `localhost` with Docker service names (`mlflow`, `spark-master`) for inter-container traffic.
- **YAML parsing**: Fixed multi-line commands in `docker-compose.yml` so API and MLflow bind to `0.0.0.0` correctly.

## [Unreleased] - Phase 3: Quality Assurance & Automation

### 🚀 Major Features

This phase focuses on code quality, automated testing, and CI/CD to keep the platform reliable and maintainable.

- **Load testing**: Integrated **Locust** for high-concurrency benchmarking; target p95 latency < 100 ms for the recommendation API.
- **Code quality enforcement**: Added **pre-commit hooks** to mandate Black, isort, Flake8, and MyPy before commits land.
- **Stronger test coverage**: Added unit tests for cache, metrics, and other critical modules to reach 70%+ coverage.

### 🏗️ Infrastructure Changes

- **Docker Compose additions**:
    - Added a `locust-master` service for containerized load testing.
    - Wired Locust into the API network so concurrent user simulations work end-to-end.

- **Pre-commit configuration** (`.pre-commit-config.yaml`):
    - Black: formatting (line-length 100)
    - isort: import sorting (profile=black)
    - Flake8: linting (max-line-length 100)
    - MyPy: static typing
    - Bandit: security scanning (test modules excluded)
    - pydocstyle: docstring validation

- **Project config files** (`pyproject.toml`, `.flake8`):
    - Centralize all tool settings to avoid scattered configs.
    - Provide a single source for Black, isort, MyPy, pytest, and more.

### 💻 Code Modifications

#### 1. Load Testing (`tests/locustfile.py`)
- **Locust user script**:
    - Adds `RecommendationUser` to emulate real clients.
    - Implements three weighted tasks:
      - `get_recommendations()` weight 3
      - `get_recommendations_with_filters()` weight 1
      - `check_health()` weight 1
    - Captures latency, success rate, and p95 metrics.
    - Auto-generates a report with:
      - Success/failure counts
      - Latency percentiles (p50, p75, p90, p95, p99)
      - Throughput (RPS)
      - Goal evaluation (p95 < 100 ms, success > 99.5%)

#### 2. Docker Orchestration (`docker-compose.yml`)
- **Locust integration**:
    - Runs in master mode on port 8089
    - Installs Locust + requests on container startup
    - Shares the network with Spark Master for API access

#### 3. Makefile Enhancements (`Makefile`)
- **New targets**:
    - `make lint`: Flake8 + Bandit
    - `make format`: Black + isort
    - `make type-check`: MyPy
    - `make pre-commit`: run every hook
    - `make pre-commit-install`: install the hooks
    - `make test-unit`: unit tests only
    - `make test-integration`: integration tests only
    - `make test-smoke`: smoke tests
    - `make load-test`: start the Locust UI
    - `make load-test-headless`: headless Locust run (5 min, 100 users)
    - `make ci`: lint + type-check + unit tests
    - `make ci-full`: CI plus load testing

#### 4. Test Enhancements (`tests/unit/test_cache.py`)
- **CacheManager unit tests** cover initialization, get/set, TTL expiry, delete/clear, key generation, and more.
- **Performance check**: validates 1,000 ops finish in < 100 ms.
- **Edge cases**: handles `None` values, large payloads, and simulated connection failures.

#### 5. Test Configuration (`tests/conftest.py`)
- **Pytest markers**:
    - `@pytest.mark.smoke`
    - `@pytest.mark.unit`
    - `@pytest.mark.integration`
    - `@pytest.mark.slow`
    - `@pytest.mark.performance`

- **Dependency mocking**: Pre-mocks heavyweight services (PySpark, MLflow, Redis, Kafka) to keep test startup fast.

### 📊 Performance Targets

| Metric | Target | Notes |
|--------|--------|-------|
| Response time p95 | < 100 ms | 95% of requests should finish within 100 ms |
| Success rate | > 99.5% | Production-grade availability |
| Code coverage | ≥ 70% | Unit tests cover critical modules |
| Throughput | 100+ RPS | Sustains 100 concurrent users |

### 🐛 Known Issues & Future Work

- **Docker Compose Locust topology**: Currently master-only; add workers for distributed load.
- **CI/CD deployment**: Still need concrete Kubernetes manifests or another target environment.
- **Test databases**: Integration tests rely on temporary Postgres/Redis containers; consider testcontainers.
- **Performance baselining**: Validate targets in a production-like environment.

---
