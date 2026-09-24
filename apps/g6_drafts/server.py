"""G6-B03 run-local task drafts. Saved drafts never enter the active LMCP bus."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/g6_tasks'))
import baseline
sys.path.insert(0, str(ROOT / 'scripts/g6_planning'))
import isolated_preview

from fastapi import FastAPI, HTTPException, Request as HttpRequest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

ORIGIN = 'http://127.0.0.1:8080'
KEY = re.compile(r'[A-Za-z0-9-]{8,64}\Z')
IDENTITY = {'runId', 'segmentId', 'backendRunId', 'streamId'}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def require_body(body, fields):
    if not isinstance(body, dict) or set(body) != fields:
        raise HTTPException(422, 'Draft operation fields differ')


def key_of(body):
    key = body.get('idempotencyKey')
    if not isinstance(key, str) or not KEY.fullmatch(key):
        raise HTTPException(422, 'Invalid idempotency key')
    return key


class DraftStore:
    def __init__(self, session_file):
        self.session_file = session_file.resolve()
        self.session = baseline.load(self.session_file)
        self.contract = baseline.load(ROOT / 'config/g6-task-contract-v1.json')
        self.root = self.session_file.parent / 'task-drafts'
        self.drafts = self.root / 'items'
        self.operations = self.root / 'operations'
        self.drafts.mkdir(parents=True, exist_ok=True)
        self.operations.mkdir(parents=True, exist_ok=True)
        self.lock = asyncio.Lock()

    def active(self):
        try:
            value = isolated_preview.active_evidence(self.session_file)
        except Exception as error:
            raise HTTPException(503, 'Active backend unavailable: ' + str(error)) from error
        return {name: value[name] for name in IDENTITY}

    def match(self, body):
        current = self.active()
        if any(body.get(name) != current[name] for name in IDENTITY):
            raise HTTPException(409, 'Run, segment, backend or stream identity changed')
        return current

    def item(self, draft_id):
        if not re.fullmatch(r'[0-9a-f]{32}', draft_id):
            raise HTTPException(404, 'Unknown draft')
        path = self.drafts / (draft_id + '.json')
        if not path.is_file():
            raise HTTPException(404, 'Unknown draft')
        return baseline.load(path)

    def all(self):
        rows = [baseline.load(path) for path in self.drafts.glob('*.json')]
        rows.sort(key=lambda value: value['draft']['draftId'])
        return rows

    def catalog(self):
        return dict(contractId=self.contract['contractId'],
                    altitudeDatum=self.contract['taskAltitudeDatum'],
                    terrainBounds=self.contract['qualifiedTerrainBoundsDegrees'],
                    taskTypes=self.contract['taskTypes'],
                    limits=self.contract['limits'],
                    parameters=self.contract['searchParameters'],
                    identity=self.active())

    def request(self, body, action):
        key = key_of(body)
        fingerprint = hashlib.sha256(json.dumps(dict(action=action, body=body),
                                                sort_keys=True).encode('utf-8')).hexdigest()
        path = self.operations / (key + '.json')
        if path.exists():
            old = baseline.load(path)
            if old['fingerprint'] != fingerprint:
                raise HTTPException(409, 'Idempotency key reused with different input')
            return old, path, fingerprint
        return None, path, fingerprint

    def receipt(self, path, fingerprint, action, item):
        row = dict(status='confirmed', action=action, fingerprint=fingerprint,
                   draft=item)
        save(path, row)
        return row

    def draft(self, body, draft_id, revision):
        kind = body['kind']
        task = self.contract['taskTypes'].get(kind)
        if task is None:
            raise HTTPException(422, 'Unsupported task type')
        if body['altitudeDatum'] != self.contract['taskAltitudeDatum']:
            raise HTTPException(422, 'Unqualified height datum')
        if body['candidateEntityIds'] != task['baselineEntityIds']:
            raise HTTPException(422, 'Unqualified entity selection')
        value = dict(schemaVersion=1, contractId=self.contract['contractId'],
                     runId=body['runId'], segmentId=body['segmentId'],
                     draftId=draft_id, revision=str(revision), taskId=task['baselineTaskId'],
                     kind=kind, candidateEntityIds=body['candidateEntityIds'],
                     geometry=body['geometry'], parameters=self.contract['searchParameters'])
        try:
            baseline.validate_draft(value, self.contract)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        return value

    async def create(self, body):
        require_body(body, IDENTITY | {'idempotencyKey', 'kind', 'geometry',
                                      'candidateEntityIds', 'altitudeDatum'})
        async with self.lock:
            old, path, fingerprint = self.request(body, 'create')
            if old:
                return old
            self.match(body)
            if len(self.all()) >= self.contract['limits']['draftCount']:
                raise HTTPException(409, 'Draft count limit reached')
            draft_id = uuid.uuid4().hex
            draft = self.draft(body, draft_id, 1)
            item = dict(draft=draft, preview=None)
            save(self.drafts / (draft_id + '.json'), item)
            return self.receipt(path, fingerprint, 'create', item)

    async def update(self, draft_id, body):
        require_body(body, IDENTITY | {'idempotencyKey', 'expectedRevision',
                                      'kind', 'geometry', 'candidateEntityIds', 'altitudeDatum'})
        async with self.lock:
            old, path, fingerprint = self.request(body, 'update:' + draft_id)
            if old:
                return old
            self.match(body)
            item = self.item(draft_id)
            if body['expectedRevision'] != item['draft']['revision']:
                raise HTTPException(409, 'Draft revision changed')
            if body['kind'] != item['draft']['kind']:
                raise HTTPException(422, 'Changing task type requires a new draft')
            revision = int(item['draft']['revision']) + 1
            item = dict(draft=self.draft(body, draft_id, revision), preview=None)
            save(self.drafts / (draft_id + '.json'), item)
            return self.receipt(path, fingerprint, 'update', item)

    async def copy(self, draft_id, body):
        require_body(body, IDENTITY | {'idempotencyKey', 'expectedRevision'})
        async with self.lock:
            old, path, fingerprint = self.request(body, 'copy:' + draft_id)
            if old:
                return old
            self.match(body)
            source = self.item(draft_id)
            if body['expectedRevision'] != source['draft']['revision']:
                raise HTTPException(409, 'Draft revision changed')
            if len(self.all()) >= self.contract['limits']['draftCount']:
                raise HTTPException(409, 'Draft count limit reached')
            new_id = uuid.uuid4().hex
            draft = dict(source['draft'], draftId=new_id, revision='1')
            item = dict(draft=draft, preview=None)
            save(self.drafts / (new_id + '.json'), item)
            return self.receipt(path, fingerprint, 'copy', item)

    async def delete(self, draft_id, body):
        require_body(body, IDENTITY | {'idempotencyKey', 'expectedRevision'})
        async with self.lock:
            old, path, fingerprint = self.request(body, 'delete:' + draft_id)
            if old:
                return old
            self.match(body)
            item = self.item(draft_id)
            if body['expectedRevision'] != item['draft']['revision']:
                raise HTTPException(409, 'Draft revision changed')
            (self.drafts / (draft_id + '.json')).unlink()
            return self.receipt(path, fingerprint, 'delete', item)

    async def preview(self, draft_id, body):
        require_body(body, IDENTITY | {'idempotencyKey', 'expectedRevision'})
        async with self.lock:
            old, path, fingerprint = self.request(body, 'preview:' + draft_id)
            if old:
                return old
            self.match(body)
            item = self.item(draft_id)
            draft = item['draft']
            if body['expectedRevision'] != draft['revision']:
                raise HTTPException(409, 'Draft revision changed')
            request = dict(**{name: body[name] for name in IDENTITY},
                           revision=draft['revision'], idempotencyKey=body['idempotencyKey'],
                           draft=draft)
            payload = json.dumps(request, ensure_ascii=False).encode('utf-8')
            try:
                with urlopen(Request('http://127.0.0.1:8002/api/tasks/v1/previews',
                    data=payload, headers={'Content-Type': 'application/json', 'Origin': ORIGIN},
                    method='POST'), timeout=65) as response:
                    result = json.load(response)
            except HTTPError as error:
                detail = json.load(error)
                raise HTTPException(error.code, detail.get('detail', 'Preview rejected')) from error
            except Exception as error:
                raise HTTPException(503, 'Preview service unavailable: ' + str(error)) from error
            if result.get('status') != 'previewed' or result.get('revision') != draft['revision']:
                raise HTTPException(502, 'Preview result does not match draft revision')
            item = dict(draft=draft, preview=result['plan'])
            save(self.drafts / (draft_id + '.json'), item)
            return self.receipt(path, fingerprint, 'preview', item)


def application(store):
    app = FastAPI(title='G6 task drafts', docs_url=None, redoc_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=[ORIGIN], allow_methods=['GET', 'POST', 'PUT', 'DELETE'],
                       allow_headers=['Content-Type'])

    @app.get('/api/tasks/v1/catalog')
    def catalog():
        return store.catalog()

    @app.get('/api/tasks/v1/drafts')
    def drafts():
        return dict(identity=store.active(), items=store.all())

    @app.get('/api/tasks/v1/drafts/{draft_id}')
    def draft(draft_id: str):
        store.active()
        return store.item(draft_id)

    @app.get('/api/tasks/v1/operations/{key}')
    def operation(key: str):
        if not KEY.fullmatch(key):
            raise HTTPException(404, 'Unknown draft operation')
        path = store.operations / (key + '.json')
        if not path.is_file():
            raise HTTPException(404, 'Unknown draft operation')
        return baseline.load(path)

    async def content(request):
        if request.headers.get('origin') != ORIGIN:
            raise HTTPException(403, 'Draft origin rejected')
        if request.headers.get('content-type', '').split(';')[0].lower() != 'application/json':
            raise HTTPException(415, 'JSON required')
        raw = await request.body()
        if len(raw) > 65536:
            raise HTTPException(413, 'Draft payload too large')
        try:
            return json.loads(raw)
        except (ValueError, UnicodeDecodeError) as error:
            raise HTTPException(422, 'Invalid JSON') from error

    @app.post('/api/tasks/v1/drafts')
    async def create(request: HttpRequest):
        return JSONResponse(await store.create(await content(request)), status_code=201)

    @app.put('/api/tasks/v1/drafts/{draft_id}')
    async def update(draft_id: str, request: HttpRequest):
        return await store.update(draft_id, await content(request))

    @app.post('/api/tasks/v1/drafts/{draft_id}/copy')
    async def copy(draft_id: str, request: HttpRequest):
        return JSONResponse(await store.copy(draft_id, await content(request)), status_code=201)

    @app.delete('/api/tasks/v1/drafts/{draft_id}')
    async def delete(draft_id: str, request: HttpRequest):
        return await store.delete(draft_id, await content(request))

    @app.post('/api/tasks/v1/drafts/{draft_id}/preview')
    async def preview(draft_id: str, request: HttpRequest):
        return await store.preview(draft_id, await content(request))

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session', type=Path, required=True)
    args = parser.parse_args()
    uvicorn.run(application(DraftStore(args.session)), host='127.0.0.1', port=8003,
                access_log=False, timeout_graceful_shutdown=5)


if __name__ == '__main__':
    main()
