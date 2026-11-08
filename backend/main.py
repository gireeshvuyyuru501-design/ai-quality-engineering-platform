"""Local, explicit adapters to the user's ten independently cloned AI QA projects.

Only predefined Python scripts can run. No user-controlled shell commands, no API keys.
Offline fixture evaluations remain labeled as such.
"""
import json
import sqlite3
import csv
import io
import hmac
import uuid
from concurrent.futures import ThreadPoolExecutor
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title='AI Quality Engineering Platform', version='0.5.0')
app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://localhost:5173', 'http://127.0.0.1:5173'],
    allow_methods=['GET', 'POST'], allow_headers=['*'],
)

PROJECTS_ROOT = Path(os.environ.get('AI_QA_PROJECTS_ROOT') or (Path(__file__).resolve().parent.parent))
@app.middleware('http')
async def local_auth(request: Request, call_next):
    if LOCAL_TOKEN and request.url.path.startswith('/api/') and request.url.path != '/api/health':
        if not hmac.compare_digest(request.headers.get('x-local-token', ''), LOCAL_TOKEN):
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=401, content={'detail': 'Invalid or missing local access token'})
    return await call_next(request)


# slug, name, main source filename, CLI arguments, result filename, provenance
MODULES = [
    ('golden-dataset-builder', 'Golden Dataset Builder', 'dataset_validation.py', [], 'dataset_validation_report.json', 'SQuAD reference sanity check; not model inference'),
    ('json-output-validator', 'JSON Output Validator', 'validator.py', [], 'report.json', 'Synthetic labeled JSON outputs'),
    ('llm-as-judge-scorecard', 'LLM-as-Judge Scorecard', 'scorecard.py', [], 'scorecard_report.json', 'Offline lexical overlap; not an LLM judge'),
    ('prompt-regression-suite', 'Prompt Regression Suite', 'prompt_regression.py', ['--limit', '50'], 'regression_report.json', 'SQuAD offline heuristic comparison; not prompt/model execution'),
    ('hallucination-hunter', 'Hallucination Hunter', 'hunter.py', ['--limit', '50'], 'evidence_report.json', 'SQuAD extractive evidence matching; not full hallucination detection'),
    ('rag-retrieval-tester', 'RAG Retrieval Tester', 'retrieval.py', ['--limit', '25', '--k', '5'], 'retrieval_report.json', 'SQuAD TF-IDF corpus retrieval benchmark'),
    ('docs-to-test-case-generator', 'Docs-to-Test-Case Generator', 'generator.py', ['--spec', 'examples/petstore.json'], 'generated_test_cases.json', 'Synthetic OpenAPI example; test specifications only, no HTTP execution'),
    ('red-team-attack-pack', 'Red-Team Attack Pack', 'red_team.py', [], 'red_team_report.json', 'Synthetic adversarial fixtures and heuristic response checks'),
    ('agent-tool-call-tester', 'Agent Tool-Call Tester', 'tool_tester.py', [], 'tool_call_report.json', 'Synthetic tool-call fixtures; no agent inference'),
    ('ai-quality-monitor', 'AI Quality Monitor', 'monitor.py', [], 'quality_report.json', 'Synthetic example trace analysis; not production telemetry'),
]
INDEX = {row[0]: row for row in MODULES}
_RUN_LOCK = threading.Lock()
_WORKERS = ThreadPoolExecutor(max_workers=1, thread_name_prefix='qa-evaluation')
JOB_LOCK = threading.Lock()
LOCAL_TOKEN = os.environ.get('AI_QA_LOCAL_TOKEN', '')

def require_local_token(request: Request):
    """Optional shared token for LOCAL development; not a production auth solution."""
    if LOCAL_TOKEN and not hmac.compare_digest(request.headers.get('x-local-token', ''), LOCAL_TOKEN):
        raise HTTPException(status_code=401, detail='Invalid or missing local access token')

LOG_PATH = Path(__file__).resolve().parent / 'evaluation_history.jsonl'
DB_PATH = Path(os.environ.get('AI_QA_DB_PATH', Path(__file__).resolve().parent / 'evaluation_history.db'))

def connect_db():
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, module_id TEXT NOT NULL, module_name TEXT NOT NULL, run_at TEXT NOT NULL, duration_ms INTEGER NOT NULL, provenance TEXT NOT NULL, live_model_evaluated INTEGER NOT NULL, summary_json TEXT NOT NULL, report_json TEXT)')
    con.execute('CREATE INDEX IF NOT EXISTS runs_module_time ON runs(module_id, run_at)')
    con.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, module_id TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, started_at TEXT, completed_at TEXT, run_id TEXT, error TEXT)')
    con.execute('CREATE INDEX IF NOT EXISTS jobs_created_at ON jobs(created_at)')
    con.commit()
    return con

def migrate_history():
    with connect_db() as con:
        if not LOG_PATH.exists():
            return
        for line in LOG_PATH.read_text(encoding='utf-8').splitlines():
            try:
                r = json.loads(line)
                con.execute('INSERT OR IGNORE INTO runs VALUES (?,?,?,?,?,?,?,?,?)',
                    (r['id'],r['module_id'],r['module_name'],r['run_at'],r['duration_ms'],r['provenance'],int(r.get('live_model_evaluated',False)),json.dumps(r.get('summary',{})),json.dumps(r.get('report')) if 'report' in r else None))
            except (ValueError,KeyError,TypeError):
                continue
        con.commit()

def decode_run(r):
    d = dict(r)
    d['live_model_evaluated'] = bool(d['live_model_evaluated'])
    d['summary'] = json.loads(d.pop('summary_json'))
    report = d.pop('report_json')
    if report is not None: d['report'] = json.loads(report)
    return d



def project_path(slug):
    return PROJECTS_ROOT / slug


def is_ready(row):
    return (project_path(row[0]) / row[2]).is_file()


def summary_metrics(report):
    """Display existing measured report fields only; do not infer model scores."""
    result = {}
    selected = (
        'total_questions', 'sample_checked', 'reference_sanity_exact_match',
        'reference_sanity_f1', 'total', 'passed', 'failed', 'count',
        'mean_lexical_f1', 'sample_count', 'generated_count', 'executed_count',
        'supported', 'unsupported', 'support_rate', 'questions', 'hit_at_k',
        'mrr_at_k', 'corpus_passages', 'total_traces', 'error_count',
        'error_rate', 'mean_latency_ms', 'p95_latency_ms',
        'mean_quality_score', 'low_quality_count',
    )
    for key in selected:
        value = report.get(key)
        if isinstance(value, (str, int, float, bool)) and value is not None:
            result[key] = value
    if isinstance(report.get('delta'), dict):
        result['delta'] = report['delta']
    if isinstance(report.get('alerts'), list):
        result['alert_count'] = len(report['alerts'])
    return result


@app.get('/api/health')
def health():
    return {'status': 'ok', 'version': '0.5.0'}


@app.get('/api/modules')
def modules():
    return [
        {'id': slug, 'name': name, 'status': 'ready' if is_ready(row) else 'missing',
         'provenance': provenance,
         'repository': 'https://github.com/gireeshvuyyuru501-design/' + slug}
        for row in MODULES
        for slug, name, _, _, _, provenance in [row]
    ]


@app.get('/api/runs')
def recent_runs(limit: int = 30, module_id: str | None = None):
    migrate_history()
    limit = max(1, min(limit, 500))
    with connect_db() as con:
        if module_id:
            rows = con.execute('SELECT * FROM runs WHERE module_id=? ORDER BY run_at DESC LIMIT ?', (module_id,limit)).fetchall()
        else:
            rows = con.execute('SELECT * FROM runs ORDER BY run_at DESC LIMIT ?', (limit,)).fetchall()
    return [decode_run(r) for r in rows]

@app.get('/api/analytics')
def analytics():
    rows = recent_runs(500)
    groups = {}
    for r in rows:
        g = groups.setdefault(r['module_id'], {'module_id':r['module_id'], 'module_name':r['module_name'], 'runs':0, 'latest':{}, 'trend':[]})
        g['runs'] += 1
        if g['runs'] == 1: g['latest'] = r['summary']
        metric = next(((k,v) for k,v in r['summary'].items() if k in ('hit_at_k','mean_lexical_f1','support_rate','mean_quality_score','reference_sanity_f1') and isinstance(v,(int,float))), None)
        if metric:
            g['trend'].append({'date':r['run_at'], 'metric':metric[0], 'value':metric[1]})
    return {'total_runs':len(rows), 'module_count':len(groups), 'modules':list(groups.values()), 'note':'Offline and synthetic fixture measurements; latest 500 recorded runs.'}

@app.get('/api/export/{format}')
def export_runs(format: str):
    if format not in ('csv','json'):
        raise HTTPException(400,'Use csv or json')
    rows = recent_runs(500)
    if format == 'json':
        data = json.dumps(rows,indent=2).encode('utf-8')
        return StreamingResponse(io.BytesIO(data),media_type='application/json',headers={'Content-Disposition':'attachment; filename="ai_quality_runs.json"'})
    output=io.StringIO()
    writer=csv.writer(output)
    writer.writerow(['id','module_id','module_name','run_at','duration_ms','provenance','live_model_evaluated','summary_json'])
    for r in rows:
        writer.writerow([r['id'],r['module_id'],r['module_name'],r['run_at'],r['duration_ms'],r['provenance'],r['live_model_evaluated'],json.dumps(r['summary'])])
    return StreamingResponse(iter([output.getvalue()]),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="ai_quality_runs.csv"'})

def save_run(record):
    with connect_db() as con:
        con.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)',
            (record['id'],record['module_id'],record['module_name'],record['run_at'],record['duration_ms'],record['provenance'],int(record['live_model_evaluated']),json.dumps(record['summary']),json.dumps(record.get('report'))))
        con.commit()

def run_module(module_id: str):
    row = INDEX.get(module_id)
    if row is None:
        raise HTTPException(status_code=404, detail='Unknown module')
    if not is_ready(row):
        raise HTTPException(status_code=404, detail=f'Module script missing: {row[2]}')
    if not _RUN_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail='An evaluation is already running')
    try:
        slug, name, script, args, report_name, provenance = row
        folder = project_path(slug)
        args = list(args)
        # Reuse the validated public dataset so we do not redownload it in each repo.
        shared = project_path('golden-dataset-builder') / 'squad_validation.json'
        if shared.is_file() and slug in ('prompt-regression-suite', 'hallucination-hunter'):
            args.extend(['--dataset', str(shared)])
        if shared.is_file() and slug == 'rag-retrieval-tester':
            rag_data = folder / 'squad_dev.json'
            if not rag_data.exists():
                shutil.copyfile(shared, rag_data)
        output_path = folder / report_name
        started = time.time()
        command = [sys.executable, str(folder / script), *args]
        try:
            process = subprocess.run(command, cwd=folder, capture_output=True,
                                     text=True, timeout=180, shell=False,
                                     encoding='utf-8', errors='replace')
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail='Evaluation exceeded 180 seconds')
        if process.returncode != 0:
            raise HTTPException(status_code=422, detail={
                'message': 'Evaluation script failed',
                'stderr': process.stderr[-1200:], 'stdout': process.stdout[-1200:]})
        if not output_path.is_file() or output_path.stat().st_mtime < started - 2:
            raise HTTPException(status_code=422, detail=f'Script did not write a fresh {report_name}')
        try:
            report = json.loads(output_path.read_text(encoding='utf-8'))
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=f'Could not read report: {exc}')
        record = {
            'id': f'{module_id}-{time.time_ns()}',
            'module_id': module_id, 'module_name': name,
            'run_at': datetime.now(timezone.utc).isoformat(),
            'duration_ms': round((time.time() - started) * 1000),
            'provenance': provenance, 'live_model_evaluated': False,
            'summary': summary_metrics(report),
        }
        record['report'] = report
        save_run(record)
        return record
    finally:
        _RUN_LOCK.release()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _execute_job(job_id: str, module_id: str):
    with connect_db() as con:
        con.execute('UPDATE jobs SET status=?, started_at=? WHERE id=?', ('running', _now(),job_id))
        con.commit()
    try:
        result = run_module(module_id)
        with connect_db() as con:
            con.execute('UPDATE jobs SET status=?,completed_at=?,run_id=? WHERE id=?',('completed',_now(),result['id'],job_id))
            con.commit()
    except Exception as exc:
        # Avoid leaking private paths or error tracebacks to client.
        detail = exc.detail if isinstance(exc,HTTPException) else str(exc)
        if isinstance(detail, dict):
            detail = detail.get('message','Evaluation failed. See server logs.')
        with connect_db() as con:
            con.execute('UPDATE jobs SET status=?,completed_at=?,error=? WHERE id=?',('failed',_now(),str(detail)[:300],job_id))
            con.commit()


@app.post('/api/jobs',status_code=202)
def create_job(request: dict):
    module_id=request.get('module_id') if isinstance(request,dict) else None
    row=INDEX.get(module_id)
    if row is None:
        raise HTTPException(status_code=404, detail='Unknown module')
    if not is_ready(row):
        raise HTTPException(status_code=404, detail=f'Module missing: {row[2]}')
    job_id=str(uuid.uuid4())
    with JOB_LOCK:
        with connect_db() as con:
            pending=con.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
            if pending>=10:
                raise HTTPException(status_code=429, detail='Queue full (max 10 jobs)')
            con.execute('INSERT INTO jobs (id,module_id,status,created_at) VALUES (?,?,?,?)',(job_id,module_id,'queued',_now()))
            con.commit()
        _WORKERS.submit(_execute_job,job_id,module_id)
    return {'job_id':job_id,'module_id':module_id,'status':'queued'}


@app.get('/api/jobs/{job_id}')
def get_job(job_id: str):
    with connect_db() as con:
        row=con.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
        if not row: raise HTTPException(404,'Job not found')
        job=dict(row)
        if row['run_id']:
            run=con.execute('SELECT * FROM runs WHERE id=?',(row['run_id'],)).fetchone()
            if run:job['result']=decode_run(run)
    return job


@app.get('/api/jobs')
def get_jobs(limit: int=30):
    with connect_db() as con:
        return [dict(x) for x in con.execute('SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?', (max(1,min(limit,100)),)).fetchall()]


@app.post('/api/modules/{module_id}/run',deprecated=True)
def run_legacy(module_id: str):
    """Backward compatible synchronous API; use POST /api/jobs for async runs."""
    return run_module(module_id)
