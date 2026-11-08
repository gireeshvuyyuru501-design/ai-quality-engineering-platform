# AI Quality Engineering Platform — v0.5

Offline-first React + TypeScript + FastAPI integration of ten independently maintained Python AI QA projects.

## Supported and verified behavior
- FastAPI dynamically detects fixed, allowlisted sibling Python scripts.
- Executions are queued using an in-process, single-worker executor and polled by the React frontend.
- SQLite persists runs, report JSON, summaries, and queued job metadata; prior v0.2 JSONL run history can be migrated.
- Dashboard charts show recorded runs and original report metrics. CSV/JSON export included.
- No Gemini inference or production telemetry: most evaluations use sample cases, heuristic baselines, or SQuAD data.

## Folder layout
```
C:\AI\ai-qa-10-projects\
  ai-quality-platform\         <- this repository
    backend\
    frontend\
    compose.yaml
  golden-dataset-builder\
  json-output-validator\
  llm-as-judge-scorecard\
  prompt-regression-suite\
  hallucination-hunter\
  rag-retrieval-tester\
  docs-to-test-case-generator\
  red-team-attack-pack\
  agent-tool-call-tester\
  ai-quality-monitor\
```

## Run with Docker Desktop
From PowerShell in `C:\AI\ai-qa-10-projects\ai-quality-platform`:

```powershell
docker compose up --build -d
docker compose ps
```

Open http://localhost:5173 and http://localhost:8000/docs. Docker mounts the parent folder so all ten Python repos remain accessible. It writes evaluation reports into the sibling repositories, and persists SQLite in `backend/evaluation_history.db`. Stop with `docker compose down` (does not delete SQLite data).

**Security**: Docker ports are bound to 127.0.0.1. This is a local demonstration; do not expose it publicly. Backend executes allowlisted local scripts, can download public SQuAD, and uses a single-process thread queue; restarts are not durable queue recovery. `AI_QA_LOCAL_TOKEN` is an optional shared token, not production authentication. No passwords, API keys, or local databases belong in Git.

## Run without Docker

Backend terminal:
```powershell
cd C:\AI\ai-qa-10-projects\ai-quality-platform\backend
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s . -p 'test_*.py' -v
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```
Frontend terminal:
```powershell
cd C:\AI\ai-qa-10-projects\ai-quality-platform\frontend
npm install
npm run dev
```

## API
`GET /api/health`, `/api/modules`, `/api/runs`, `/api/analytics`, `/api/jobs`, `/api/jobs/{job_id}`, `/api/export/csv`, `/api/export/json`; `POST /api/jobs` with `{"module_id":"json-output-validator"}`.

## Tests and CI
`python -m unittest discover -s . -p 'test_*.py' -v` from `backend`. `npm run build` from `frontend`. GitHub Actions runs both.

## Known limitations
This is a portfolio-ready **local prototype**, not a cloud-deployed or production-secured service. In-process jobs are lost on restart; jobs recorded as queued/running may need manual reconciliation. Runs use offline fixture data and transparent baselines only. Live LLM assessment, robust RBAC, persistent worker queues, and secured public hosting are future features.
