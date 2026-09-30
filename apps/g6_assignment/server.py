"""G6-B05 run-local multi-task planning, review and explicit activation."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/g6_execution'))
import core
from lmcp import LMCPFactory
from fastapi import FastAPI, HTTPException, Request as HttpRequest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

ORIGIN = 'http://127.0.0.1:8080'
KEY = re.compile(r'[A-Za-z0-9-]{8,64}\Z')
HEX = re.compile(r'[0-9a-f]{32}\Z')
IDENTITY = ('runId', 'segmentId', 'backendRunId', 'streamId')


def need(condition, message):
    if not condition:
        raise ValueError(message)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode('utf-8')).hexdigest()


def journal_count(path, descriptor):
    if not path.is_file():
        return 0
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=.25) as db:
        db.execute('PRAGMA query_only=ON')
        return db.execute('SELECT COUNT(*) FROM msg WHERE descriptor=?', (descriptor,)).fetchone()[0]


def send_logged(packet, descriptor, journal, folder, label):
    before = journal_count(journal, descriptor)
    (folder / (label + '.bin')).write_bytes(packet)
    with socket.create_connection(('127.0.0.1', 9999), timeout=4) as sock:
        sock.settimeout(4)
        sock.sendall(packet)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if journal_count(journal, descriptor) > before:
                return
            time.sleep(.05)
        raise TimeoutError(label + ' was not committed to the active UxAS journal')


def packet(obj, name):
    raw = bytes(LMCPFactory.packMessage(obj, True))
    return core.isolated_preview.startup.wire.frame(raw, name, source='900',
                                                    service='1', group='G6MultiTaskConfirmed'), \
        hashlib.sha256(raw).hexdigest()


class AssignmentStore:
    def __init__(self, session_file):
        self.session_file = session_file.resolve()
        self.session = core.release.load(self.session_file)
        self.contract = core.release.load(ROOT / 'config/g6-assignment-contract-v1.json')
        self.root = self.session_file.parent / 'task-assignment'
        self.plans = self.root / 'plans'
        self.operations = self.root / 'operations'
        self.confirmations = self.root / 'confirmations'
        for directory in (self.plans, self.operations, self.confirmations):
            directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def active(self):
        try:
            state = core.isolated_preview.active_evidence(self.session_file)
            return {name: state[name] for name in IDENTITY}
        except Exception as error:
            raise HTTPException(409, 'Planning requires the frozen pre-start simulation') from error

    def state(self):
        identity = self.active()
        drafts = [core.release.load(path)['draft'] for path in
                  (self.session_file.parent / 'task-drafts/items').glob('*.json')]
        drafts.sort(key=lambda x: x['taskId'])
        return dict(identity=identity, contractId=self.contract['contractId'],
                    candidates=self.contract['qualifiedCandidates'],
                    relationships=self.contract['relationships'],
                    sequenceVehicleId=self.contract['sequenceVehicleId'], drafts=drafts,
                    plans=[{'planId': row['review']['planId'],
                            'relationship': row['review']['relationship'],
                            'taskOrder': row['review']['taskOrder']}
                           for path in self.plans.glob('*.json')
                           for row in [core.release.load(path)]])

    def validate(self, body):
        need(isinstance(body, dict) and set(body) == set(IDENTITY) |
             {'idempotencyKey', 'tasks', 'taskOrder', 'relationship'},
             'Multi-task planning fields differ')
        identity = self.active()
        need(all(body[name] == identity[name] for name in IDENTITY),
             'Active planning identity changed')
        key = body['idempotencyKey']
        need(isinstance(key, str) and KEY.fullmatch(key), 'Invalid planning key')
        rows = body['tasks']
        need(isinstance(rows, list) and 2 <= len(rows) <= 3, 'Select two or three saved drafts')
        relation = body['relationship']
        need(relation in self.contract['relationships'], 'Unsupported task relationship')
        selected = []
        for row in rows:
            need(isinstance(row, dict) and set(row) ==
                 {'draftId', 'revision', 'candidateEntityIds'}, 'Task selection fields differ')
            draft_id = row['draftId']
            need(isinstance(draft_id, str) and HEX.fullmatch(draft_id), 'Invalid draft ID')
            path = self.session_file.parent / 'task-drafts/items' / (draft_id + '.json')
            need(path.is_file(), 'Saved draft is missing')
            draft = core.release.load(path)['draft']
            need(draft['revision'] == row['revision'] and
                 draft['runId'] == identity['runId'] and
                 draft['segmentId'] == identity['segmentId'],
                 'Saved draft revision or run identity changed')
            eligible = row['candidateEntityIds']
            allowed = self.contract['qualifiedCandidates'][draft['kind']]
            need(isinstance(eligible, list) and eligible and len(eligible) == len(set(eligible))
                 and all(vehicle in allowed for vehicle in eligible) and
                 eligible == sorted(eligible), 'Vehicle candidate selection is not qualified')
            if relation == 'sequence':
                need(eligible == [self.contract['sequenceVehicleId']],
                     'Sequential tasks must use the same qualified vehicle')
            selected.append(dict(draftId=draft_id, revision=draft['revision'],
                                 taskId=draft['taskId'], kind=draft['kind'], draft=draft,
                                 candidateEntityIds=eligible,
                                 savedDraftSHA256=core.release.digest(path)))
        need(len({row['taskId'] for row in selected}) == len(selected) and
             len({row['kind'] for row in selected}) == len(selected),
             'A task appears more than once')
        order = body['taskOrder']
        need(isinstance(order, list) and len(order) == len(selected) and
             set(order) == {row['taskId'] for row in selected}, 'Task order differs')
        vehicles = sorted({vehicle for row in selected for vehicle in row['candidateEntityIds']})
        return dict(identity=identity, relationship=relation, taskOrder=order,
                    vehicleIds=vehicles, sequenceVehicleId=self.contract['sequenceVehicleId'],
                    tasks=selected)

    def review_file(self, plan_id):
        if not HEX.fullmatch(plan_id):
            raise HTTPException(404, 'Unknown multi-task plan')
        path = self.plans / (plan_id + '.json')
        if not path.is_file():
            raise HTTPException(404, 'Unknown multi-task plan')
        return path

    def review(self, plan_id):
        identity = self.active()
        row = core.release.load(self.review_file(plan_id))
        self.recheck(row, identity)
        return row['review']

    def recheck(self, row, identity):
        need(row['status'] == 'previewed' and row['spec']['identity'] == identity,
             'Multi-task plan is stale')
        source = ROOT / 'out/runs/g6-b05-plan' / row['plannerRunId']
        receipt = core.release.load(source / 'result.json')
        need(receipt['status'] == 'passed' and receipt['isolatedPlannerQualified'] and
             receipt['inputSHA256'] == core.release.digest(source / 'input.json') and
             receipt['plannerLogSHA256'] == core.release.digest(source / 'planner.jsonl') and
             receipt['responseXmlSHA256'] == core.release.digest(source / 'response.xml') and
             receipt['uniqueRequestSHA256'] == core.release.digest(source / 'unique-request.xml') and
             receipt['uniqueResponseSHA256'] == core.release.digest(source / 'unique-response.xml') and
             receipt['plan'] == row['review']['plan'],
             'Isolated planner evidence changed')
        for draft in row['spec']['tasks']:
            path = self.session_file.parent / 'task-drafts/items' / (draft['draftId'] + '.json')
            need(path.is_file() and core.release.digest(path) == draft['savedDraftSHA256'] and
                 core.release.load(path)['draft'] == draft['draft'],
                 'Saved draft changed after planning')
            task_file = source / ('task-' + draft['taskId'] + '.xml')
            expected = next(x['taskSHA256'] for x in receipt['sourceDrafts']
                            if x['taskId'] == draft['taskId'])
            need(core.release.digest(task_file) == expected, 'Planned task bytes changed')
        need(row['review']['reviewSHA256'] == digest({k: v for k, v in row['review'].items()
                                                      if k != 'reviewSHA256'}),
             'Review digest changed')
        return source

    def plan(self, body):
        with self.lock:
            spec = self.validate(body)
            key = body['idempotencyKey']
            fingerprint = digest(body)
            op_path = self.operations / (key + '.json')
            if op_path.exists():
                old = core.release.load(op_path)
                need(old['fingerprint'] == fingerprint, 'Planning key was reused')
                return old
            plan_id = uuid.uuid4().hex
            run_id = uuid.uuid4().hex
            spec_path = self.root / (plan_id + '-input.json')
            save(spec_path, spec)
            command = [str(sys.executable), '-I', '-B', '-X', 'utf8',
                       str(ROOT / 'scripts/g6_assignment/plan.py'), '--session', str(self.session_file),
                       '--input', str(spec_path), '--run-id', run_id]
            try:
                done = subprocess.run(command, capture_output=True, timeout=90,
                                      creationflags=subprocess.CREATE_NO_WINDOW)
                (self.root / (plan_id + '.stdout')).write_bytes(done.stdout)
                (self.root / (plan_id + '.stderr')).write_bytes(done.stderr)
                need(done.returncode == 0, 'Isolated multi-task planner failed')
                planner = core.release.load(ROOT / 'out/runs/g6-b05-plan' / run_id / 'result.json')
                need(planner['status'] == 'passed', 'Isolated planner receipt failed')
                self.validate(body)
                plan = planner['plan']
                review = dict(planId=plan_id, identity=spec['identity'],
                    relationship=spec['relationship'], taskOrder=spec['taskOrder'],
                    tasks=[{k: row[k] for k in ('draftId', 'revision', 'taskId', 'kind',
                                                'candidateEntityIds')} for row in spec['tasks']],
                    plan=plan, confirmationAllowed=plan['timeBudgetFits'],
                    plannerRunId=run_id, requestId=planner['requestId'],
                    responseXmlSHA256=planner['responseXmlSHA256'])
                review['reviewSHA256'] = digest(review)
                save(self.plans / (plan_id + '.json'),
                     dict(status='previewed', plannerRunId=run_id, spec=spec, review=review))
                result = dict(status='previewed', key=key, fingerprint=fingerprint,
                              planId=plan_id, review=review)
            except Exception as error:
                result = dict(status='rejected', key=key, fingerprint=fingerprint,
                              error=str(error))
            save(op_path, result)
            return result

    def confirmation(self, key):
        if not KEY.fullmatch(key):
            raise HTTPException(404, 'Unknown confirmation')
        path = self.confirmations / (key + '.json')
        if not path.exists():
            raise HTTPException(404, 'Unknown confirmation')
        row = core.release.load(path)
        if row['status'] in ('confirmed', 'executing', 'completed'):
            events = core.observer_rows(self.session_file)
            stages = {}
            for assignment in row['assignments']:
                task_id, vehicle = assignment['taskId'], assignment['vehicleId']
                active = next((event for event in events if event['type'] ==
                    'uxas.messages.task.TaskActive' and event.get('taskId') == task_id), None)
                complete = next((event for event in events if event['type'] ==
                    'uxas.messages.task.TaskComplete' and event.get('taskId') == task_id), None)
                state = dict(taskId=task_id, vehicleId=vehicle, status='assigned')
                if active:
                    node = ET.fromstring(base64.b64decode(active['xmlBase64']))
                    if node.findtext('EntityID') == vehicle:
                        state.update(status='active', taskActiveSHA256=active['rawSHA256'],
                                     activatedMs=node.findtext('TimeTaskActivated'))
                if complete and state['status'] == 'active':
                    node = ET.fromstring(base64.b64decode(complete['xmlBase64']))
                    if vehicle in [x.text for x in node.findall('EntitiesInvolved/int64')]:
                        state.update(status='completed', taskCompleteSHA256=complete['rawSHA256'],
                                     completedMs=node.findtext('TimeTaskCompleted'),
                                     durationMs=str(int(node.findtext('TimeTaskCompleted')) -
                                                    int(state['activatedMs'])))
                stages[task_id] = state
            row['tasks'] = list(stages.values())
            row['status'] = 'completed' if all(x['status'] == 'completed' for x in stages.values()) \
                else 'executing' if any(x['status'] != 'assigned' for x in stages.values()) \
                else 'confirmed'
            save(path, row)
        return row

    def activate(self, path, row, review, source):
        irreversible = False
        try:
            from urllib.request import Request, urlopen
            def control(method, resource, body=None):
                payload = json.dumps(body).encode() if body is not None else None
                headers = {'Origin': ORIGIN}
                if payload is not None:
                    headers['Content-Type'] = 'application/json'
                with urlopen(Request('http://127.0.0.1:8001/api/control/v1/' + resource,
                    data=payload, headers=headers, method=method), timeout=15) as response:
                    return json.load(response)
            state = control('GET', 'state')
            need(not state['started'] and state['streamId'] == review['identity']['streamId'],
                 'Frozen control state changed')
            start_key = 'g6-b05-start-' + hashlib.sha256(row['key'].encode()).hexdigest()[:32]
            row.update(phase='start-attempted', startKey=start_key)
            save(path, row)
            irreversible = True
            started = control('POST', 'operations', dict(
                runId=row['runId'], segmentId=row['segmentId'],
                expectedSequence=state['controlSequence'], idempotencyKey=start_key,
                action='start', multiple=None))
            need(started['status'] == 'confirmed' and started['key'] == start_key,
                 'Start operation was not confirmed')
            row['controlReceipt'] = started
            save(path, row)
            journal = self.session_file.parent / 'uxas/datawork/SavedMessages/messageLog_1_0.db3'
            def wait(label, predicate, seconds=20):
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    value = predicate()
                    if value:
                        return value
                    time.sleep(.1)
                raise TimeoutError(label)
            vehicles = {assignment['vehicleId'] for assignment in row['assignments']}
            wait('Initial active vehicle state missing', lambda:
                 {x.get('id') for x in core.observer_rows(self.session_file) if
                  x['type'] == 'afrl.cmasi.AirVehicleState' and x.get('timeMs') == '0'} >= vehicles)
            for task in review['tasks']:
                task_id = task['taskId']
                obj = core.lmcp_object(source / ('task-' + task_id + '.xml'))
                wire, sha = packet(obj, obj.FULL_LMCP_TYPE_NAME)
                row['phase'] = 'task-' + task_id + '-attempted'
                save(path, row)
                send_logged(wire, obj.FULL_LMCP_TYPE_NAME, journal, self.confirmations,
                            row['key'] + '-task-' + task_id)
                row.setdefault('taskRawSHA256', {})[task_id] = sha
                save(path, row)
            selected = {task['taskId'] for task in review['tasks']}
            wait('Task initialization incomplete', lambda:
                 {x.get('taskId') for x in core.observer_rows(self.session_file) if
                  x['type'] == 'uxas.messages.task.TaskInitialized'} >= selected, 30)
            request = core.lmcp_object(source / 'unique-request.xml')
            request.SandBoxRequest = False
            response = core.lmcp_object(source / 'unique-response.xml')
            plan = core.lmcp_object(source / 'response.xml', 'AutomationResponse')
            embedded = core.lmcp_object(source / 'unique-response.xml', 'AutomationResponse')
            need(bytes(LMCPFactory.packMessage(plan, True)) ==
                 bytes(LMCPFactory.packMessage(embedded, True)),
                 'Assignment response embeds a different reviewed plan')
            before_commands = {x['rawSHA256'] for x in core.observer_rows(self.session_file)
                               if x['type'] == 'afrl.cmasi.MissionCommand'}
            for label, obj in (('unique-request', request), ('unique-response', response),
                               ('automation-response', plan)):
                wire, sha = packet(obj, obj.FULL_LMCP_TYPE_NAME)
                row['phase'] = label + '-attempted'
                save(path, row)
                send_logged(wire, obj.FULL_LMCP_TYPE_NAME, journal, self.confirmations,
                            row['key'] + '-' + label)
                row.setdefault('contextRawSHA256', {})[label] = sha
                save(path, row)
            expected = {item['vehicleId'] for item in review['plan']['commands']}
            def mission_commands():
                expected_by_vehicle = {item['vehicleId']: {p['number']: p for p in item['waypoints']}
                                       for item in review['plan']['commands']}
                observed = []
                for event in core.observer_rows(self.session_file):
                    vehicle = event.get('vehicleId')
                    if event['type'] != 'afrl.cmasi.MissionCommand' or \
                            event.get('sourceEntity') != '100' or vehicle not in expected or \
                            event['rawSHA256'] in before_commands:
                        continue
                    node = ET.fromstring(base64.b64decode(event['xmlBase64']))
                    points = node.findall('WaypointList/Waypoint')
                    lookup = expected_by_vehicle[vehicle]
                    if len(points) < 2 or any(
                        point.findtext('Number') not in lookup or
                        abs(float(point.findtext('Longitude')) -
                            lookup[point.findtext('Number')]['longitude']) > 1e-7 or
                        abs(float(point.findtext('Latitude')) -
                            lookup[point.findtext('Number')]['latitude']) > 1e-7
                        for point in points):
                        continue
                    observed.append(event)
                return observed if {x['vehicleId'] for x in observed} >= expected else None
            observed = wait('Mission commands not observed', mission_commands, 30)
            row.update(status='confirmed', phase='commands-observed',
                       missionCommands=[{k: x.get(k) for k in ('vehicleId', 'commandId', 'rawSHA256')}
                                        for x in observed])
            save(path, row)
        except Exception as error:
            row.update(status='uncertain' if irreversible else 'rejected',
                       error=str(error))
            save(path, row)
        return row

    def confirm(self, plan_id, body):
        need(isinstance(body, dict) and set(body) == set(IDENTITY) |
             {'reviewSHA256', 'idempotencyKey', 'acknowledged'} and
             body['acknowledged'] is True, 'Confirmation fields differ')
        key = body['idempotencyKey']
        need(isinstance(key, str) and KEY.fullmatch(key), 'Invalid confirmation key')
        fingerprint = digest(dict(planId=plan_id, body=body))
        path = self.confirmations / (key + '.json')
        with self.lock:
            if path.exists():
                row = core.release.load(path)
                need(row['fingerprint'] == fingerprint, 'Confirmation key was reused')
                return self.confirmation(key)
            need(not list(self.confirmations.glob('*.json')) and
                 not list((self.session_file.parent / 'task-execution').glob('*.json')),
                 'A plan was already confirmed in this segment')
            identity = self.active()
            row_plan = core.release.load(self.review_file(plan_id))
            source = self.recheck(row_plan, identity)
            review = row_plan['review']
            need(all(body[name] == identity[name] for name in IDENTITY) and
                 body['reviewSHA256'] == review['reviewSHA256'],
                 'Reviewed plan or active identity changed')
            need(review['confirmationAllowed'], 'Planned flight exceeds simulation duration')
            row = dict(task='G6-B05', key=key, planId=plan_id,
                       fingerprint=fingerprint, reviewSHA256=review['reviewSHA256'],
                       assignments=review['plan']['assignments'],
                       status='pending', phase='prepared', **identity)
            save(path, row)
        return self.activate(path, row, review, source)


def application(store):
    app = FastAPI(title='G6 multi-task planning', docs_url=None, redoc_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=[ORIGIN],
                       allow_methods=['GET', 'POST'], allow_headers=['Content-Type'])

    async def content(request):
        if request.headers.get('origin') != ORIGIN:
            raise HTTPException(403, 'Planning origin rejected')
        if request.headers.get('content-type', '').split(';')[0].lower() != 'application/json':
            raise HTTPException(415, 'JSON required')
        raw = await request.body()
        if len(raw) > 65536:
            raise HTTPException(413, 'Planning payload too large')
        try:
            return json.loads(raw)
        except (ValueError, UnicodeDecodeError) as error:
            raise HTTPException(422, 'Invalid JSON') from error

    @app.get('/api/tasks/v2/state')
    def state():
        return store.state()

    @app.post('/api/tasks/v2/plans')
    async def plan(request: HttpRequest):
        import asyncio
        try:
            result = await asyncio.to_thread(store.plan, await content(request))
            return JSONResponse(result, status_code=200 if result['status'] == 'previewed' else 409)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.get('/api/tasks/v2/plans/{plan_id}')
    def review(plan_id: str):
        try:
            return store.review(plan_id)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.get('/api/tasks/v2/operations/{key}')
    def operation(key: str):
        if not KEY.fullmatch(key):
            raise HTTPException(404, 'Unknown planning operation')
        path = store.operations / (key + '.json')
        if not path.is_file():
            raise HTTPException(404, 'Unknown planning operation')
        return core.release.load(path)

    @app.post('/api/tasks/v2/plans/{plan_id}/confirm')
    async def confirm(plan_id: str, request: HttpRequest):
        import asyncio
        try:
            result = await asyncio.to_thread(store.confirm, plan_id, await content(request))
            return JSONResponse(result, status_code=200 if result['status'] in
                                ('confirmed', 'executing', 'completed') else 409)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.get('/api/tasks/v2/confirmations/{key}')
    def confirmation(key: str):
        return store.confirmation(key)

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session', type=Path, required=True)
    args = parser.parse_args()
    store = AssignmentStore(args.session)
    uvicorn.run(application(store), host='127.0.0.1', port=8005,
                log_level='warning', access_log=False)


if __name__ == '__main__':
    main()
