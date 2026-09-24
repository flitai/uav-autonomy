"""Run-local G6-B02 preview API with a separate UxAS planner process."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/g6_tasks'))
import baseline
sys.path.insert(0, str(ROOT / 'scripts/g6_planning'))
import isolated_preview

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

ORIGIN = 'http://127.0.0.1:8080'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)


class PreviewService:
    def __init__(self, session_file):
        self.session_file = session_file.resolve()
        self.session = baseline.load(self.session_file)
        self.folder = self.session_file.parent / 'task-previews'
        self.folder.mkdir(exist_ok=True)
        self.contract = baseline.load(ROOT / 'config/g6-task-contract-v1.json')
        self.lock = asyncio.Lock()

    def state(self):
        active = isolated_preview.active_evidence(self.session_file)
        return {key: active[key] for key in ('runId', 'segmentId', 'backendRunId', 'streamId')}

    async def preview(self, body):
        async with self.lock:
            required = {'runId', 'segmentId', 'backendRunId', 'streamId',
                        'revision', 'idempotencyKey', 'draft'}
            if not isinstance(body, dict) or set(body) != required:
                raise HTTPException(422, 'Preview fields differ')
            key = body['idempotencyKey']
            if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9-]{8,64}', key):
                raise HTTPException(422, 'Invalid idempotency key')
            fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True).encode('utf-8')).hexdigest()
            receipt = self.folder / (key + '.json')
            if receipt.exists():
                previous = baseline.load(receipt)
                if previous['fingerprint'] != fingerprint:
                    raise HTTPException(409, 'Idempotency key used with different input')
                return previous
            try:
                baseline.validate_draft(body['draft'], self.contract)
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
            try:
                active = self.state()
            except Exception as error:
                raise HTTPException(503, 'Active backend unavailable: ' + str(error)) from error
            if any(body[name] != active[name] for name in ('runId', 'segmentId', 'backendRunId', 'streamId')):
                raise HTTPException(409, 'Active run identity or stream changed')
            if (body['draft']['runId'] != body['runId'] or
                    body['draft']['segmentId'] != body['segmentId'] or
                    body['draft']['revision'] != body['revision']):
                raise HTTPException(409, 'Draft revision or segment changed')
            run_id = 'g6-b02-api-' + uuid.uuid4().hex
            run = ROOT / 'out/runs' / run_id
            run.mkdir()
            draft_file = run / 'draft.json'
            write(draft_file, body['draft'])
            row = dict(task='G6-B02', status='pending', key=key,
                       fingerprint=fingerprint, runId=body['runId'],
                       segmentId=body['segmentId'], backendRunId=body['backendRunId'],
                       streamId=body['streamId'], revision=body['revision'],
                       previewRunId=run_id, planId=uuid.uuid4().hex)
            write(receipt, row)
            command = [sys.executable, '-I', '-B', '-X', 'utf8',
                       str(ROOT / 'scripts/g6_planning/isolated_preview.py'),
                       '--run-id', run_id + '-planner', '--draft', str(draft_file),
                       '--active-session', str(self.session_file)]
            try:
                result = await asyncio.to_thread(subprocess.run, command, cwd=ROOT,
                    capture_output=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
                (run / 'stdout.log').write_bytes(result.stdout)
                (run / 'stderr.log').write_bytes(result.stderr)
                candidate = baseline.load(ROOT / 'out/runs' / (run_id + '-planner') / 'result.json')
                if result.returncode or candidate['status'] != 'passed' or \
                        not candidate['previewIsolationQualified']:
                    raise RuntimeError(candidate.get('error', 'Planner did not qualify preview'))
                preview = candidate['previews'][0]
                row.update(status='previewed', plan=dict(planId=row['planId'],
                    taskId=preview['taskId'], revision=body['revision'],
                    runId=body['runId'], segmentId=body['segmentId'],
                    backendRunId=body['backendRunId'], streamId=body['streamId'],
                    candidateTaskSHA256=candidate['candidateTaskSHA256'],
                    responseSHA256=preview['responseSHA256'],
                    responseXmlSHA256=preview['responseXmlSHA256'],
                    route=preview['route'],
                    confirmationEnabled=False))
            except Exception as error:
                row.update(status='rejected', error=str(error))
            write(receipt, row)
            return row


def application(service):
    app = FastAPI(title='G6 task preview', docs_url=None, redoc_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=[ORIGIN],
                       allow_methods=['GET', 'POST'], allow_headers=['Content-Type'])

    @app.get('/api/tasks/v1/state')
    def state():
        try:
            return service.state()
        except Exception as error:
            raise HTTPException(503, str(error)) from error

    @app.get('/api/tasks/v1/operations/{key}')
    def operation(key: str):
        if not re.fullmatch(r'[A-Za-z0-9-]{8,64}', key):
            raise HTTPException(404, 'Unknown preview operation')
        path = service.folder / (key + '.json')
        if not path.is_file():
            raise HTTPException(404, 'Unknown preview operation')
        return baseline.load(path)

    @app.get('/api/tasks/v1/plans/{plan_id}')
    def plan(plan_id: str):
        if not re.fullmatch(r'[0-9a-f]{32}', plan_id):
            raise HTTPException(404, 'Unknown plan')
        for path in service.folder.glob('*.json'):
            row = baseline.load(path)
            if row.get('planId') == plan_id and row['status'] == 'previewed':
                return row['plan']
        raise HTTPException(404, 'Unknown plan')

    @app.post('/api/tasks/v1/previews')
    async def preview(request: Request):
        if request.headers.get('origin') != ORIGIN:
            raise HTTPException(403, 'Preview origin rejected')
        if request.headers.get('content-type', '').split(';')[0].lower() != 'application/json':
            raise HTTPException(415, 'JSON required')
        raw = await request.body()
        if len(raw) > 65536:
            raise HTTPException(413, 'Preview payload too large')
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as error:
            raise HTTPException(422, 'Invalid JSON') from error
        row = await service.preview(body)
        return JSONResponse(row, status_code=200 if row['status'] == 'previewed' else 422)

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session', type=Path, required=True)
    args = parser.parse_args()
    service = PreviewService(args.session)
    uvicorn.run(application(service), host='127.0.0.1', port=8002,
                access_log=False, timeout_graceful_shutdown=5)


if __name__ == '__main__':
    main()
