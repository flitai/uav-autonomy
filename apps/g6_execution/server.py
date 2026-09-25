"""G6-B04 fixed-assignment confirmation of the exact saved B02 preview."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sys
import threading
import time
import xml.etree.ElementTree as ET
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/g6_execution'))
import core
from fastapi import FastAPI, HTTPException, Request as HttpRequest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

ORIGIN = 'http://127.0.0.1:8080'
KEY = re.compile(r'[A-Za-z0-9-]{8,64}\Z')
IDENTITY = ('runId', 'segmentId', 'backendRunId', 'streamId')


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def request(port, method, path, body=None, timeout=8):
    payload = json.dumps(body).encode('utf-8') if body is not None else None
    headers = {'Origin': ORIGIN}
    if payload is not None:
        headers['Content-Type'] = 'application/json'
    try:
        with urlopen(Request(f'http://127.0.0.1:{port}{path}', data=payload,
                             headers=headers, method=method), timeout=timeout) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


def wait(label, predicate, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(.1)
    raise TimeoutError(label + ' timed out')


def frame(raw, name):
    return core.isolated_preview.startup.wire.frame(raw, name,
        source='900', service='1', group='G6ConfirmedPlan')


def send_once(packet):
    with socket.create_connection(('127.0.0.1', 9999), timeout=4) as sock:
        sock.settimeout(4)
        sock.sendall(packet)
    # Closing promptly is required: the bridge sends a high-volume observation stream
    # to every connected client, including write clients.


def command_matches(row, review):
    if row['type'] != 'afrl.cmasi.MissionCommand' or row.get('sourceEntity') != '100' or \
            row.get('vehicleId') != review['assignment']['vehicleId']:
        return False
    root = ET.fromstring(base64.b64decode(row['xmlBase64']))
    points = root.findall('WaypointList/Waypoint')
    expected = review['waypoints']
    if not points or len(points) > len(expected):
        return False
    expected_by_number = {point['number']: point for point in expected}
    for point in points:
        match = expected_by_number.get(point.findtext('Number'))
        if match is None or abs(float(point.findtext('Longitude'))-match['longitude']) > 1e-7 or \
                abs(float(point.findtext('Latitude'))-match['latitude']) > 1e-7 or \
                abs(float(point.findtext('Altitude'))-match['altitudeMeters']) > 1e-6:
            return False
    return True


class ExecutionStore:
    def __init__(self, session_file):
        self.session_file = session_file.resolve()
        self.session = core.release.load(self.session_file)
        self.folder = self.session_file.parent / 'task-execution'
        self.folder.mkdir(exist_ok=True)
        self.lock = threading.Lock()

    def review(self, plan_id):
        try:
            return core.resolve(self.session_file, plan_id)[0]
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        except Exception as error:
            raise HTTPException(503, str(error)) from error

    def operation(self, key):
        if not KEY.fullmatch(key):
            raise HTTPException(404, 'Unknown confirmation operation')
        path = self.folder / (key + '.json')
        if not path.is_file():
            raise HTTPException(404, 'Unknown confirmation operation')
        row = core.release.load(path)
        if row['status'] in ('confirmed', 'completed'):
            rows = core.observer_rows(self.session_file)
            active = next((item for item in rows if item['type'] == 'uxas.messages.task.TaskActive' and
                           item.get('taskId') == row['taskId'] and item.get('sourceEntity') == '100'), None)
            if active:
                root = ET.fromstring(base64.b64decode(active['xmlBase64']))
                if root.findtext('EntityID') == row['vehicleId']:
                    row['taskActiveSHA256'] = active['rawSHA256']
                    row['taskActiveTimeMs'] = root.findtext('TimeTaskActivated')
            completed = next((item for item in rows if item['type'] == 'uxas.messages.task.TaskComplete' and
                              item.get('taskId') == row['taskId'] and item.get('sourceEntity') == '100'), None)
            if completed and active:
                root = ET.fromstring(base64.b64decode(completed['xmlBase64']))
                if row['vehicleId'] in [node.text for node in root.findall('EntitiesInvolved/int64')]:
                    row.update(status='completed', taskCompleteSHA256=completed['rawSHA256'],
                               taskCompleteTimeMs=root.findtext('TimeTaskCompleted'))
                    row['taskDurationMs'] = str(int(row['taskCompleteTimeMs'])-
                                                int(row['taskActiveTimeMs']))
                    save(path, row)
            states = [item for item in rows if item['type'] == 'afrl.cmasi.AirVehicleState' and
                      item.get('id') == row['vehicleId']]
            if states:
                row['latestVehicleTimeMs'] = states[-1].get('timeMs')
                row['latestVehicleSHA256'] = states[-1]['rawSHA256']
        return row

    def activate(self, path, row, review, task_bytes, assignment_request_bytes,
                 assignment_response_bytes, plan_bytes):
        irreversible = False
        try:
            code, control = request(8001, 'GET', '/api/control/v1/state')
            if code != 200 or control['started'] or control['streamId'] != row['streamId']:
                raise ValueError('Frozen control state changed before confirmation')
            start_key = 'g6-b04-start-' + hashlib.sha256(row['key'].encode()).hexdigest()[:32]
            row.update(phase='start-submitted', controlKey=start_key)
            save(path, row)
            start_body = dict(runId=row['runId'], segmentId=row['segmentId'],
                expectedSequence=control['controlSequence'], idempotencyKey=start_key,
                action='start', multiple=None)
            code, started = request(8001, 'POST', '/api/control/v1/operations', start_body, 12)
            irreversible = True
            row['controlReceipt'] = started
            save(path, row)
            if code != 200 or started.get('status') != 'confirmed':
                raise RuntimeError('Start result is not confirmed')
            vehicle = row['vehicleId']
            def first_state():
                return next((item for item in core.observer_rows(self.session_file) if
                    item['type'] == 'afrl.cmasi.AirVehicleState' and item.get('id') == vehicle and
                    item.get('timeMs') == '0'), None)
            initial = wait('initial vehicle state', first_state, 20)
            scene = ET.parse(self.session_file.parent / 'scene/scenario.xml')
            source = next(node for node in scene.getroot().findall('ScenarioEventList/AirVehicleState')
                          if node.findtext('ID') == vehicle)
            latitude = float(source.findtext('Location/Location3D/Latitude'))
            longitude = float(source.findtext('Location/Location3D/Longitude'))
            if abs(initial['latitude']-latitude) > 1e-8 or \
                    abs(initial['longitude']-longitude) > 1e-8:
                raise RuntimeError('Initial active position differs from preview input')
            row.update(phase='initial-state-verified', initialStateSHA256=initial['rawSHA256'])
            save(path, row)
            task_packet = frame(task_bytes, 'afrl.cmasi.' +
                                {'point':'PointSearchTask','line':'LineSearchTask','area':'AreaSearchTask'}[review['kind']])
            (self.folder / (row['key'] + '-task.bin')).write_bytes(task_packet)
            row.update(phase='task-attempted')
            save(path, row)
            send_once(task_packet)
            row.update(phase='task-sent')
            save(path, row)
            initialized = wait('task initialized', lambda: next((item for item in
                core.observer_rows(self.session_file) if item['type'] ==
                'uxas.messages.task.TaskInitialized' and item.get('taskId') == row['taskId']), None), 25)
            row['taskInitializedSHA256'] = initialized['rawSHA256']
            for label, raw, name in (
                    ('assignment-request', assignment_request_bytes,
                     'uxas.messages.task.UniqueAutomationRequest'),
                    ('assignment-response', assignment_response_bytes,
                     'uxas.messages.task.UniqueAutomationResponse')):
                packet = frame(raw, name)
                (self.folder / (row['key'] + '-' + label + '.bin')).write_bytes(packet)
                row.update(phase=label + '-attempted')
                save(path, row)
                send_once(packet)
                row.update(phase=label + '-sent')
                save(path, row)
            before = {item['rawSHA256'] for item in core.observer_rows(self.session_file) if
                      item['type'] == 'afrl.cmasi.MissionCommand'}
            plan_packet = frame(plan_bytes, 'afrl.cmasi.AutomationResponse')
            (self.folder / (row['key'] + '-plan.bin')).write_bytes(plan_packet)
            row.update(phase='plan-attempted', priorCommandCount=len(before))
            save(path, row)
            send_once(plan_packet)
            row.update(phase='plan-sent')
            save(path, row)
            def command():
                return next((item for item in core.observer_rows(self.session_file) if
                    item['type'] == 'afrl.cmasi.MissionCommand' and
                    item['rawSHA256'] not in before and command_matches(item, review)), None)
            observed = wait('same-plan mission command', command, 25)
            row.update(status='confirmed', phase='command-observed',
                       missionCommandSHA256=observed['rawSHA256'],
                       missionCommandId=observed.get('commandId'))
            save(path, row)
        except Exception as error:
            row.update(status='uncertain' if irreversible else 'rejected',
                       error=str(error), phase=row.get('phase', 'prepared'))
            save(path, row)
        return row

    def confirm(self, plan_id, body):
        required = set(IDENTITY) | {'draftId', 'expectedRevision', 'reviewSHA256',
                                    'idempotencyKey', 'acknowledged'}
        if not isinstance(body, dict) or set(body) != required or body['acknowledged'] is not True:
            raise HTTPException(422, 'Explicit confirmation fields differ')
        key = body['idempotencyKey']
        if not isinstance(key, str) or not KEY.fullmatch(key):
            raise HTTPException(422, 'Invalid confirmation key')
        fingerprint = hashlib.sha256(json.dumps(dict(planId=plan_id, body=body),
                                                sort_keys=True).encode()).hexdigest()
        path = self.folder / (key + '.json')
        with self.lock:
            if path.exists():
                row = core.release.load(path)
                if row['fingerprint'] != fingerprint:
                    raise HTTPException(409, 'Confirmation key reused with different input')
                return self.operation(key)
            if list(self.folder.glob('*.json')):
                raise HTTPException(409, 'A confirmation already exists in this segment')
            review, task_bytes, assignment_request_bytes, assignment_response_bytes, plan_bytes = \
                core.resolve(self.session_file, plan_id)
            if (body['draftId'] != review['draftId'] or
                    body['expectedRevision'] != review['revision'] or
                    body['reviewSHA256'] != review['reviewSHA256'] or
                    any(body[name] != review['identity'][name] for name in IDENTITY)):
                raise HTTPException(409, 'Reviewed plan or active identity changed')
            row = dict(task='G6-B04', key=key, planId=plan_id,
                draftId=review['draftId'], revision=review['revision'],
                taskId=review['taskId'], vehicleId=review['assignment']['vehicleId'],
                reviewSHA256=review['reviewSHA256'],
                taskBytesSHA256=review['taskBytesSHA256'],
                planBytesSHA256=review['planBytesSHA256'],
                assignmentRequestSHA256=review['assignmentRequestSHA256'],
                assignmentResponseSHA256=review['assignmentResponseSHA256'],
                fingerprint=fingerprint, status='pending', phase='prepared',
                **review['identity'])
            save(path, row)
        return self.activate(path, row, review, task_bytes, assignment_request_bytes,
                             assignment_response_bytes, plan_bytes)


def application(store):
    app = FastAPI(title='G6 fixed plan confirmation', docs_url=None, redoc_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=[ORIGIN],
                       allow_methods=['GET','POST'], allow_headers=['Content-Type'])

    @app.get('/api/tasks/v1/confirmation-state')
    def state():
        return dict(runId=store.session['runId'],segmentId=store.session['segmentId'],
                    backendRunId=store.session['backendRunId'],
                    operations=[core.release.load(path) for path in store.folder.glob('*.json')])

    @app.get('/api/tasks/v1/plans/{plan_id}/review')
    def review(plan_id: str):
        return store.review(plan_id)

    @app.get('/api/tasks/v1/confirmations/{key}')
    def operation(key: str):
        return store.operation(key)

    @app.post('/api/tasks/v1/plans/{plan_id}/confirm')
    async def confirm(plan_id: str, request: HttpRequest):
        if request.headers.get('origin') != ORIGIN:
            raise HTTPException(403, 'Confirmation origin rejected')
        if request.headers.get('content-type', '').split(';')[0].lower() != 'application/json':
            raise HTTPException(415, 'JSON required')
        payload = await request.body()
        if len(payload) > 4096:
            raise HTTPException(413, 'Confirmation payload too large')
        try:
            body = json.loads(payload)
        except (ValueError, UnicodeDecodeError) as error:
            raise HTTPException(422, 'Invalid JSON') from error
        import asyncio
        row = await asyncio.to_thread(store.confirm, plan_id, body)
        return JSONResponse(row, status_code=200 if row['status'] in ('confirmed','completed') else
                            202 if row['status']=='uncertain' else 409)

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session',type=Path,required=True)
    args = parser.parse_args()
    uvicorn.run(application(ExecutionStore(args.session)), host='127.0.0.1',port=8004,
                access_log=False,timeout_graceful_shutdown=5)


if __name__=='__main__':
    main()
