"""G6-B07 durable task operations and fail-closed recovery over B06."""
import argparse
import hashlib
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
spec = spec_from_file_location('g6_b06_server', ROOT / 'apps/g6_replanning/server.py')
base = module_from_spec(spec)
spec.loader.exec_module(base)

from fastapi import HTTPException, Request as HttpRequest
from fastapi.responses import JSONResponse
import uvicorn

SEGMENT = re.compile(r'segment-[0-9]{3}\Z')
MAX_OPERATIONS = 8
DEFAULT_PLANNER_DEADLINE_SECONDS = 90


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n',
                             encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class LifecycleStore(base.ReplanningStore):
    def __init__(self, session_file, planner_deadline_seconds=DEFAULT_PLANNER_DEADLINE_SECONDS):
        super().__init__(session_file)
        base.require(1 <= planner_deadline_seconds <= 100,
                     'Planner deadline must be 1–100 seconds')
        self.planner_deadline_seconds = planner_deadline_seconds
        self.ledger = self.root / 'lifecycle'
        self.ledger.mkdir(parents=True, exist_ok=True)
        self.lifecycle_lock = threading.RLock()
        self.planner_running = False
        self.recover()

    def records(self):
        return [base.core.release.load(path) for path in sorted(self.ledger.glob('*.json'))]

    def operation(self, key):
        base.require(isinstance(key, str) and base.KEY.fullmatch(key),
                     'Unknown lifecycle operation')
        path = self.ledger / (key + '.json')
        base.require(path.is_file(), 'Unknown lifecycle operation')
        return base.core.release.load(path)

    def recover(self):
        # A planning process only reads the active backend. A cutover can send
        # commands, so its interrupted receipt must remain blocked for review.
        with self.lifecycle_lock:
            for path in self.ledger.glob('*.json'):
                row = base.core.release.load(path)
                if row['status'] == 'pending':
                    row.update(status='interrupted',
                               reason='Planning service restarted before a result was recorded')
                    save(path, row)
                elif row['status'] == 'confirming':
                    row.update(status='uncertain',
                               reason='Service restarted during confirmation; no command was resent')
                    save(path, row)
            for path in self.switches.glob('*.json'):
                row = base.core.release.load(path)
                if row['status'] == 'pending':
                    row.update(status='uncertain', recovery='manual-reconciliation',
                               error='Service restarted during task cutover; no command was resent')
                    save(path, row)

    def health(self):
        try:
            current = base.control('GET', 'state')
            session = base.core.release.load(self.session_file)
            from sim_bridge.windows import process_identity
            uxas = base.core.release.load(self.session_file.parent / 'uxas/process.json')
            base.require(process_identity(session['amaseProcess']['pid']) ==
                         session['amaseProcess'] and
                         process_identity(uxas['pid']) is not None,
                         'Owned AMASE or UxAS backend process is unavailable')
            manifest = base.core.release.load(self.session_file.parent /
                                              'gateway-host/manifest.json')
            with base.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2) as response:
                gateway = json.load(response)
            # Control is authoritative for segment and stream identity. A
            # gateway replacement with a new stream cannot reuse old plans.
            base.require(all(current[name] == session[name] for name in base.IDENTITY[:3]),
                         'Control session identity changed')
            base.require(gateway['status'] not in ('failed', 'stopped'),
                         'Gateway is unavailable')
            base.require(current['streamId'] == gateway['stream_id'],
                         'Control and gateway streams differ')
            base.require(manifest['run_id'] == session['backendRunId'],
                         'Gateway manifest backend identity changed')
            return dict(readOnly=False, reason=None, identity={name: current[name]
                        for name in base.IDENTITY})
        except Exception as error:
            return dict(readOnly=True, reason=str(error), identity=None)

    def state(self):
        health = self.health()
        self.stale_previews(health)
        records = self.records()
        if health['readOnly']:
            session = base.core.release.load(self.session_file)
            return dict(identity={name: session.get(name) for name in base.IDENTITY},
                        status='backend-unavailable', simulation=None,
                        initialPlan=None, originalTasks=[], availableDrafts=[],
                        switch=self.latest_switch(), lifecycle=records, health=health)
        state = super().state()
        state.update(lifecycle=records, health=health)
        return state

    def stale_previews(self, health):
        if health['readOnly']:
            return
        with self.lifecycle_lock:
            for path in self.ledger.glob('*.json'):
                row = base.core.release.load(path)
                if row['status'] == 'previewed' and row['identity'] != health['identity']:
                    row.update(status='stale',
                               reason='Backend or gateway stream identity changed')
                    save(path, row)

    def latest_switch(self):
        paths = sorted(self.switches.glob('*.json'))
        return base.core.release.load(paths[0]) if paths else None

    def _active_preview(self):
        return next((row for row in self.records()
                     if row['status'] in ('pending', 'previewed')), None)

    def plan(self, body):
        base.require(isinstance(body, dict) and
                     isinstance(body.get('idempotencyKey'), str) and
                     base.KEY.fullmatch(body['idempotencyKey']),
                     'Invalid lifecycle planning key')
        key = body['idempotencyKey']
        fingerprint = base.assignment.digest(body)
        path = self.ledger / (key + '.json')
        with self.lifecycle_lock:
            if path.is_file():
                row = base.core.release.load(path)
                base.require(row['fingerprint'] == fingerprint,
                             'Planning key was reused for different input')
                return row
            health = self.health()
            base.require(not health['readOnly'],
                         'Backend identity unavailable; planning is read-only')
            self.stale_previews(health)
            base.require(not self.latest_switch(),
                         'A replacement has already been attempted in this segment')
            base.require(not self.planner_running and not self._active_preview(),
                         'Another replacement preview owns this segment')
            base.require(len(self.records()) < MAX_OPERATIONS,
                         'Planning operation limit reached for this segment')
            # Validation reads the stable paused snapshot before ownership is
            # recorded, so rejected input cannot reserve the segment.
            checked = self.validate(body)
            row = dict(task='G6-B07', kind='plan', key=key,
                       fingerprint=fingerprint, status='pending',
                       identity=checked['identity'], submittedAtMs=str(int(time.time() * 1000)),
                       deadlineSeconds=self.planner_deadline_seconds)
            save(path, row)
            self.planner_running = True
        started = time.monotonic()
        # The B06 planner has its own 100 s bound and executes in isolation.
        # Cancellation stops promotion; its child finishes safely before the
        # next planner can acquire the fixed isolated TCP port.
        internal = dict(body, idempotencyKey='b07-' + uuid.uuid4().hex)
        try:
            result = super().plan(internal)
            with self.lifecycle_lock:
                current = base.core.release.load(path)
                if current['status'] == 'canceled':
                    current['lateResult'] = result['status']
                elif time.monotonic() - started > self.planner_deadline_seconds:
                    current.update(status='timed-out',
                                   reason='Isolated planner exceeded the operation deadline',
                                   lateResult=result['status'])
                elif result['status'] == 'previewed':
                    current.update(status='previewed', planId=result['planId'],
                                   review=result['review'])
                else:
                    current.update(status='rejected', reason=result.get('error',
                                                                       'Planner rejected request'))
                save(path, current)
                return current
        except Exception as error:
            with self.lifecycle_lock:
                current = base.core.release.load(path)
                if current['status'] == 'pending':
                    current.update(status='rejected', reason=str(error))
                    save(path, current)
                return current
        finally:
            with self.lifecycle_lock:
                self.planner_running = False

    def cancel(self, key, body):
        base.require(isinstance(body, dict) and
                     set(body) == set(base.IDENTITY) | {'idempotencyKey'} and
                     isinstance(body['idempotencyKey'], str) and
                     base.KEY.fullmatch(body['idempotencyKey']),
                     'Invalid cancellation fields')
        with self.lifecycle_lock:
            row = self.operation(key)
            base.require(all(body[name] == row['identity'][name] for name in base.IDENTITY),
                         'Cancellation identity differs')
            base.require(row['status'] in ('pending', 'previewed', 'canceled'),
                         'Only an unconfirmed preview can be canceled')
            if row['status'] != 'canceled':
                row.update(status='canceled', canceledBy=body['idempotencyKey'],
                           canceledAtMs=str(int(time.time() * 1000)))
                save(self.ledger / (key + '.json'), row)
            else:
                base.require(row['canceledBy'] == body['idempotencyKey'],
                             'Cancellation key differs')
            return row

    def review(self, plan_id):
        health = self.health()
        self.stale_previews(health)
        base.require(any(row.get('planId') == plan_id and row['status'] == 'previewed'
                         for row in self.records()),
                     'Plan is canceled, stale or belongs to another segment')
        base.require(not health['readOnly'],
                     'Backend identity unavailable; review is read-only')
        return super().review(plan_id)

    def switch(self, plan_id, body):
        key = body.get('idempotencyKey') if isinstance(body, dict) else None
        if isinstance(key, str) and base.KEY.fullmatch(key) and \
                (self.switches / (key + '.json')).is_file():
            return super().switch(plan_id, body)
        health = self.health()
        base.require(not health['readOnly'],
                     'Backend identity unavailable; confirmation is read-only')
        self.stale_previews(health)
        active = next((row for row in self.records() if
                       row.get('planId') == plan_id and row['status'] == 'previewed'), None)
        base.require(active is not None and not self.planner_running,
                     'Plan was canceled, superseded or is still planning')
        path = self.ledger / (active['key'] + '.json')
        with self.lifecycle_lock:
            current = base.core.release.load(path)
            base.require(current['status'] == 'previewed',
                         'Plan status changed before confirmation')
            current.update(status='confirming', confirmationKey=key)
            save(path, current)
        try:
            result = super().switch(plan_id, body)
        except ValueError:
            # B06 raises before recording any cutover if review or identity is
            # stale. If a switch receipt exists, its status remains uncertain.
            with self.lifecycle_lock:
                current = base.core.release.load(path)
                current['status'] = 'uncertain' if self.latest_switch() else 'previewed'
                save(path, current)
            raise
        with self.lifecycle_lock:
            current = base.core.release.load(path)
            current.update(status='confirmed' if result['status'] in
                           ('switched', 'executing', 'completed') else 'uncertain',
                           confirmationKey=result['key'])
            save(path, current)
        return result


def application(store):
    app = base.application(store)

    async def content(request):
        if request.headers.get('origin') != base.ORIGIN:
            raise HTTPException(403, 'Lifecycle origin rejected')
        if request.headers.get('content-type', '').split(';')[0].lower() != 'application/json':
            raise HTTPException(415, 'JSON required')
        raw = await request.body()
        if len(raw) > 65536:
            raise HTTPException(413, 'Lifecycle payload too large')
        try:
            return json.loads(raw)
        except (ValueError, UnicodeDecodeError) as error:
            raise HTTPException(422, 'Invalid JSON') from error

    @app.get('/api/tasks/v4/state')
    def state():
        return store.state()

    @app.get('/api/tasks/v4/operations/{key}')
    def operation(key: str):
        try:
            return store.operation(key)
        except ValueError as error:
            raise HTTPException(404, str(error)) from error

    @app.post('/api/tasks/v4/operations/{key}/cancel')
    async def cancel(key: str, request: HttpRequest):
        try:
            return store.cancel(key, await content(request))
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.get('/api/tasks/v4/history/{segment}/{key}')
    def history(segment: str, key: str):
        if not SEGMENT.fullmatch(segment) or not base.KEY.fullmatch(key):
            raise HTTPException(404, 'Unknown historical operation')
        file = store.session_file.parents[1] / segment / 'task-replanning/lifecycle' / (key + '.json')
        if not file.is_file():
            raise HTTPException(404, 'Unknown historical operation')
        row = base.core.release.load(file)
        if row['identity']['runId'] != store.session['runId']:
            raise HTTPException(404, 'Historical run differs')
        return dict(row, stale=segment != store.session_file.parent.name)

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--planner-deadline-seconds', type=int,
                        default=DEFAULT_PLANNER_DEADLINE_SECONDS)
    args = parser.parse_args()
    store = LifecycleStore(args.session, args.planner_deadline_seconds)
    uvicorn.run(application(store), host='127.0.0.1', port=8006,
                access_log=False, log_level='warning')


if __name__ == '__main__':
    main()
