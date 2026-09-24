"""Run-local G6 control API. Only the owned AMASE process executes commands."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Literal
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
import uvicorn
from sim_bridge.windows import process_identity

ORIGIN = 'http://127.0.0.1:8080'
RATES = {'0.25', '0.5', '1', '2', '5', '10'}


class Operation(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    runId: str
    segmentId: str
    expectedSequence: str = Field(pattern=r'^[0-9]{1,12}$')
    idempotencyKey: str = Field(pattern=r'^[A-Za-z0-9-]{8,64}$')
    action: Literal['start', 'pause', 'resume', 'rate', 'reset']
    multiple: str | None = None


def save(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)


class Controller:
    def __init__(self, session_file):
        self.session = json.loads(session_file.read_text(encoding='utf-8'))
        self.run = session_file.parent
        self.history = self.run.parent / 'control-reset-receipts'
        self.java = Path(self.session['javaDirectory']).resolve()
        if not self.java.is_relative_to(self.run.resolve()):
            raise RuntimeError('AMASE control directory escaped this run')
        self.records = self.run / 'control-operations'
        self.records.mkdir(exist_ok=True)
        self.lock = asyncio.Lock()
        used = [int(p.stem) for p in (self.java / 'results').glob('*.json')]
        used += [int(row['sequence']) for p in self.records.glob('*.json')
                 if (row := json.loads(p.read_text(encoding='utf-8'))).get('sequence', '').isdigit()]
        self.sequence = max(used, default=0)

    def snapshot(self):
        identity = process_identity(self.session['amaseProcess']['pid'])
        if identity != self.session['amaseProcess']:
            raise RuntimeError('AMASE process identity changed')
        with urlopen('http://127.0.0.1:8000/api/v1/snapshot', timeout=2) as response:
            value = json.load(response)
        if value['run_id'] != self.session['backendRunId'] or not value['stream_id']:
            raise RuntimeError('Gateway run identity changed')
        return value

    def health(self):
        identity = process_identity(self.session['amaseProcess']['pid'])
        if identity != self.session['amaseProcess']:
            raise RuntimeError('AMASE process identity changed')
        with urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2) as response:
            value = json.load(response)
        if value['run_id'] != self.session['backendRunId'] or not value['stream_id']:
            raise RuntimeError('Gateway run identity changed')
        return value

    def state(self):
        health = self.health()
        try:
            snapshot = self.snapshot()
        except Exception:
            snapshot = None
        return {'runId': self.session['runId'], 'segmentId': self.session['segmentId'],
                'backendRunId': health['run_id'], 'streamId': health['stream_id'],
                'durationMs': self.session['durationMs'], 'controlSequence': str(self.sequence),
                'started': (self.java / 'request-start').exists(),
                'simulation': snapshot['state']['simulation'] if snapshot else None,
                'ready': snapshot is not None}

    def refresh(self, row):
        if row['status'] in ('confirmed', 'rejected'):
            return row
        if row['action'] == 'reset':
            receipt = self.history / (row['key'] + '.json')
            return json.loads(receipt.read_text(encoding='utf-8')) if receipt.is_file() else row
        if row['action'] == 'start':
            events = self.java / 'events.jsonl'
            if (events.exists() and events.stat().st_size < 1024 * 1024 and
                    '"kind":"start-request"' in events.read_text(encoding='utf-8')):
                row['status'] = 'applied'
                try:
                    snapshot = self.snapshot()
                    if snapshot['stream_id'] != row['streamId']:
                        row.update(status='uncertain', error='Gateway stream changed before operation confirmation')
                        save(self.records / (row['key'] + '.json'), row)
                        return row
                    simulation = snapshot['state']['simulation']
                    if simulation['state'] == 1:
                        row['status'] = 'confirmed'
                        row['feedback'] = simulation
                except Exception:
                    pass
                save(self.records / (row['key'] + '.json'), row)
            return row
        receipt = self.java / 'results' / (row['sequence'] + '.json')
        if receipt.is_file():
            ack = json.loads(receipt.read_text(encoding='utf-8'))
            if ack['id'] != row['sequence'] or ack['action'] != row['action']:
                row['status'] = 'uncertain'
                row['error'] = 'AMASE receipt identity differs'
            elif ack['outcome'] != 'applied':
                row['status'] = 'rejected'
                row['ack'] = ack
            else:
                row['ack'] = ack
                row['status'] = 'applied'
                try:
                    snapshot = self.snapshot()
                    if snapshot['stream_id'] != row['streamId']:
                        row.update(status='uncertain', error='Gateway stream changed before operation confirmation')
                        save(self.records / (row['key'] + '.json'), row)
                        return row
                    simulation = snapshot['state']['simulation']
                    target = {'pause': 2, 'resume': 1}.get(row['action'])
                    match = (target is None or simulation['state'] == target)
                    if row['action'] == 'rate':
                        match = simulation['real_time_multiple'] == float(row['multiple'])
                    event = simulation.get('source', {}).get('event_id')
                    if match and event and event != row.get('baseEvent'):
                        row['status'] = 'confirmed'
                        row['feedback'] = simulation
                except Exception:
                    pass
            save(self.records / (row['key'] + '.json'), row)
        return row

    async def submit(self, operation):
        async with self.lock:
            key = operation.idempotencyKey
            path = self.records / (key + '.json')
            request = operation.model_dump()
            fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
            if path.exists():
                old = json.loads(path.read_text(encoding='utf-8'))
                if old['fingerprint'] != fingerprint:
                    raise HTTPException(409, 'Idempotency key used with different input')
                return self.refresh(old)
            if operation.runId != self.session['runId'] or operation.segmentId != self.session['segmentId']:
                raise HTTPException(409, 'Run or segment identity differs')
            if operation.expectedSequence != str(self.sequence):
                raise HTTPException(409, 'Control version differs')
            if operation.action == 'rate':
                if operation.multiple not in RATES:
                    raise HTTPException(422, 'Unsupported simulation multiple')
            elif operation.multiple is not None:
                raise HTTPException(422, 'Multiple is only valid for rate')
            try:
                live = self.health() if operation.action == 'start' else self.snapshot()
            except Exception as error:
                raise HTTPException(503, 'Qualified backend unavailable: ' + str(error)) from error
            simulation = None if operation.action == 'start' else live['state']['simulation']
            allowed = {'pause': 1, 'resume': 2}
            if operation.action in allowed and simulation['state'] != allowed[operation.action]:
                raise HTTPException(409, 'Simulation state does not allow this action')
            if operation.action == 'rate' and (simulation['state'] not in (1, 2) or
                    simulation['real_time_multiple'] == float(operation.multiple)):
                raise HTTPException(409, 'Simulation multiple is already set or state is invalid')
            if operation.action == 'reset' and simulation['state'] not in (1, 2):
                raise HTTPException(409, 'Simulation state does not allow reset')
            if operation.action == 'start' and (self.java / 'request-start').exists():
                raise HTTPException(409, 'This segment has already started')
            for previous in self.records.glob('*.json'):
                row = self.refresh(json.loads(previous.read_text(encoding='utf-8')))
                if row['status'] in ('pending', 'uncertain'):
                    raise HTTPException(409, 'Prior control result is not confirmed')
                if row['status'] == 'applied' and not (row['action'] == 'rate' and operation.action == 'resume'
                        and self.snapshot()['state']['simulation']['state'] == 2):
                    raise HTTPException(409, 'Prior control feedback is pending')
            self.sequence += 1
            sequence = f'{self.sequence:012d}'
            row = {'key': key, 'sequence': sequence, 'fingerprint': fingerprint,
                   'runId': operation.runId, 'segmentId': operation.segmentId,
                   'action': operation.action, 'multiple': operation.multiple,
                   'streamId': live['stream_id'],
                   'baseEvent': simulation.get('source', {}).get('event_id') if simulation else None,
                   'status': 'pending', 'submittedAtMs': int(time.time() * 1000)}
            save(path, row)
            if operation.action == 'reset':
                (self.run / 'request-reset').touch()
                return row
            if operation.action == 'start':
                (self.java / 'request-start').touch()
            else:
                command = self.java / 'requests' / (sequence + '.request')
                temporary = command.with_suffix('.tmp')
                temporary.write_text(operation.action + '\n' + (operation.multiple or '') + '\n', encoding='ascii')
                os.replace(temporary, command)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                row = self.refresh(row)
                if row['status'] in ('confirmed', 'rejected'):
                    return row
                if row['status'] == 'applied':
                    if operation.action == 'rate':
                        return row  # A paused timer has no new SessionStatus until resumed.
                await asyncio.sleep(.1)
            row = self.refresh(row)
            if row['status'] == 'pending':
                row['status'] = 'uncertain'
                save(path, row)
            return row


def application(controller):
    app = FastAPI(title='G6 local simulation control', docs_url=None, redoc_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=[ORIGIN], allow_methods=['GET', 'POST'],
                       allow_headers=['Content-Type'], allow_credentials=False)

    @app.get('/api/control/v1/state')
    def state():
        try:
            return controller.state()
        except Exception as error:
            raise HTTPException(503, str(error)) from error

    @app.get('/api/control/v1/operations/{key}')
    def operation(key: str):
        if not re.fullmatch(r'[A-Za-z0-9-]{8,64}', key):
            raise HTTPException(404, 'Unknown operation')
        path = controller.records / (key + '.json')
        if not path.is_file():
            receipt = controller.history / (key + '.json')
            if receipt.is_file():
                return json.loads(receipt.read_text(encoding='utf-8'))
            raise HTTPException(404, 'Unknown operation')
        return controller.refresh(json.loads(path.read_text(encoding='utf-8')))

    @app.get('/api/control/v1/operations')
    def operations():
        rows = [controller.refresh(json.loads(path.read_text(encoding='utf-8')))
                for path in controller.records.glob('*.json')]
        rows += [receipt for path in controller.history.glob('*.json')
                 if (receipt := json.loads(path.read_text(encoding='utf-8'))).get('toSegmentId') ==
                 controller.session['segmentId']]
        rows.sort(key=lambda row: (row.get('submittedAtMs', 0), row['sequence']), reverse=True)
        return {'runId': controller.session['runId'], 'segmentId': controller.session['segmentId'],
                'items': rows[:32]}

    @app.post('/api/control/v1/operations')
    async def submit(request: Request):
        if request.headers.get('origin') != ORIGIN:
            raise HTTPException(403, 'Control origin rejected')
        if request.headers.get('content-type', '').split(';')[0].lower() != 'application/json':
            raise HTTPException(415, 'JSON required')
        if len(await request.body()) > 1024:
            raise HTTPException(413, 'Control payload too large')
        try:
            value = Operation.model_validate(await request.json())
        except (ValidationError, ValueError) as error:
            raise HTTPException(422, 'Invalid control request') from error
        row = await controller.submit(value)
        return JSONResponse(row, status_code=409 if row['status'] == 'rejected' else
                            202 if row['status'] in ('pending', 'uncertain', 'applied') else 200)

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session', type=Path, required=True)
    args = parser.parse_args()
    controller = Controller(args.session.resolve())
    server = uvicorn.Server(uvicorn.Config(application(controller), host='127.0.0.1', port=8001,
                                           access_log=False, timeout_graceful_shutdown=5))

    async def run():
        async def stop_requested():
            while not server.should_exit:
                if (controller.run / 'control-request-stop').exists():
                    server.should_exit = True
                    return
                await asyncio.sleep(.1)
        watcher = asyncio.create_task(stop_requested())
        try:
            await server.serve()
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
    asyncio.run(run())


if __name__ == '__main__':
    main()
