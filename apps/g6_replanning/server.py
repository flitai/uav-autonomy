"""G6-B06 run-local paused-execution replacement planning and cutover."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'apps/g6_assignment'))
import server as assignment
sys.path.insert(0, str(ROOT / 'scripts/g6_replanning'))
import live
sys.path.insert(0, str(ROOT / 'scripts/g6_tasks'))
import baseline

from afrl.cmasi.RemoveTasks import RemoveTasks
from fastapi import FastAPI, HTTPException, Request as HttpRequest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

core = assignment.core
IDENTITY = assignment.IDENTITY
ORIGIN = assignment.ORIGIN
KEY = assignment.KEY
HEX = assignment.HEX


def require(condition, message):
    if not condition:
        raise ValueError(message)


def control(method, resource, body=None):
    payload = json.dumps(body).encode() if body is not None else None
    headers = {'Origin': ORIGIN}
    if payload is not None:
        headers['Content-Type'] = 'application/json'
    with urlopen(Request('http://127.0.0.1:8001/api/control/v1/' + resource,
                         data=payload, headers=headers, method=method), timeout=15) as response:
        return json.load(response)


class ReplanningStore:
    def __init__(self, session_file):
        self.session_file = Path(session_file).resolve()
        self.session = core.release.load(self.session_file)
        self.contract = core.release.load(ROOT / 'config/g6-task-contract-v1.json')
        self.assignment_contract = core.release.load(ROOT / 'config/g6-assignment-contract-v1.json')
        self.root = self.session_file.parent / 'task-replanning'
        self.plans = self.root / 'plans'
        self.operations = self.root / 'operations'
        self.switches = self.root / 'switches'
        for folder in (self.plans, self.operations, self.switches):
            folder.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def initial(self):
        folder = self.session_file.parent / 'task-assignment/confirmations'
        rows = [core.release.load(path) for path in folder.glob('*.json')]
        require(len(rows) == 1 and rows[0]['status'] in ('confirmed', 'executing'),
                'Confirm one B05 plan before replanning')
        initial = rows[0]
        plan_path = self.session_file.parent / 'task-assignment/plans' / (initial['planId'] + '.json')
        require(plan_path.is_file(), 'Initial confirmed plan is unavailable')
        original = core.release.load(plan_path)
        require(original['review']['reviewSHA256'] == initial['reviewSHA256'],
                'Initial plan and confirmation differ')
        source = ROOT / 'out/runs/g6-b05-plan' / original['plannerRunId']
        receipt = core.release.load(source / 'result.json')
        require(receipt['status'] == 'passed' and receipt['isolatedPlannerQualified'] and
                receipt['plan'] == original['review']['plan'] and
                receipt['inputSHA256'] == core.release.digest(source / 'input.json') and
                receipt['responseXmlSHA256'] == core.release.digest(source / 'response.xml') and
                receipt['uniqueRequestSHA256'] ==
                    core.release.digest(source / 'unique-request.xml') and
                receipt['uniqueResponseSHA256'] ==
                    core.release.digest(source / 'unique-response.xml'),
                'Initial B05 planner evidence changed')
        return initial, original

    def state(self):
        current = control('GET', 'state')
        status = 'pre-start'
        initial = None
        try:
            initial, original = self.initial()
            status = 'pause-to-replan' if current['started'] else 'pre-start'
            if current['started'] and current['simulation'] and \
                    current['simulation']['state'] == 2:
                status = 'paused'
        except ValueError:
            original = None
        switches = [core.release.load(path) for path in self.switches.glob('*.json')]
        available = []
        if original:
            selected = {task['taskId'] for task in original['spec']['tasks']}
            available = [core.release.load(path)['draft'] for path in
                (self.session_file.parent / 'task-drafts/items').glob('*.json')
                if core.release.load(path)['draft']['taskId'] not in selected]
        return dict(identity={key: current[key] for key in IDENTITY}, status=status,
                    simulation=current['simulation'],
                    initialPlan=original['review'] if original else None,
                    originalTasks=original['spec']['tasks'] if original else [],
                    availableDrafts=available,
                    switch=switches[0] if switches else None)

    def validate(self, body):
        require(isinstance(body, dict) and set(body) == set(IDENTITY) |
                {'idempotencyKey', 'change'}, 'Replanning request fields differ')
        key = body['idempotencyKey']
        require(isinstance(key, str) and KEY.fullmatch(key), 'Invalid replanning key')
        change = body['change']
        require(isinstance(change, dict) and change.get('action') in ('revise', 'add'),
                'Choose an addition or revision')
        expected = {'action', 'taskId', 'geometry'} if change['action'] == 'revise' else \
                   {'action', 'draftId'}
        require(set(change) == expected, 'Task change fields differ')
        active = live.settled_snapshot(self.session_file)
        require(all(body[name] == active['identity'][name] for name in IDENTITY),
                'Run, segment, backend or stream changed')
        require(not list(self.switches.glob('*.json')), 'A replacement has already been attempted')
        initial, old = self.initial()
        original = old['review']
        old_ids = {row['taskId'] for row in original['tasks']}
        events = active['taskEvents']
        require(any(event['type'].endswith('.TaskActive') and event['taskId'] in old_ids
                    for event in events), 'No initial task has begun execution')
        require(not any(event['type'].endswith('.TaskComplete') and event['taskId'] in old_ids
                        for event in events), 'Completed tasks cannot be replayed in this B06 candidate')
        draft_rows = [dict(row) for row in old['spec']['tasks']]
        for source_row in draft_rows:
            source_file = self.session_file.parent / 'task-drafts/items' / \
                (source_row['draftId'] + '.json')
            require(source_file.is_file() and
                    core.release.digest(source_file) == source_row['savedDraftSHA256'] and
                    core.release.load(source_file)['draft'] == source_row['draft'],
                    'An initial saved task changed')
        change_kind = None
        if change['action'] == 'revise':
            require(change['taskId'] in old_ids, 'Revision target is not in the active plan')
            target = next(row for row in draft_rows if row['taskId'] == change['taskId'])
            draft = dict(target['draft'])
            draft['geometry'] = change['geometry']
            draft['revision'] = str(int(draft['revision']) + 1)
            baseline.validate_draft(draft, self.contract)
            target['draft'] = draft
            change_kind = draft['kind']
        else:
            require(isinstance(change['draftId'], str) and HEX.fullmatch(change['draftId']),
                    'Invalid new draft ID')
            file = self.session_file.parent / 'task-drafts/items' / (change['draftId'] + '.json')
            require(file.is_file(), 'New task must use a saved draft')
            draft = core.release.load(file)['draft']
            baseline.validate_draft(draft, self.contract)
            require(draft['taskId'] not in old_ids and len(draft_rows) < 3,
                    'Only one previously unused task can be added')
            eligible = self.assignment_contract['qualifiedCandidates'][draft['kind']]
            if old['spec']['relationship'] == 'sequence':
                eligible = [self.assignment_contract['sequenceVehicleId']]
            draft_rows.append(dict(draftId=draft['draftId'], revision=draft['revision'],
                                   taskId=draft['taskId'], kind=draft['kind'], draft=draft,
                                   candidateEntityIds=eligible,
                                   savedDraftSHA256=core.release.digest(file)))
            change_kind = draft['kind']
        require(len(draft_rows) in (2, 3) and
                len({row['kind'] for row in draft_rows}) == len(draft_rows),
                'Replacement must contain two or three distinct search types')
        id_by_kind = {'line': '3100', 'point': '3101', 'area': '3102'}
        tasks = []
        for row in draft_rows:
            draft = row['draft']
            baseline.validate_draft(draft, self.contract)
            tasks.append(dict(taskId=id_by_kind[draft['kind']], oldTaskId=row['taskId'],
                              kind=draft['kind'], draft=draft,
                              candidateEntityIds=row['candidateEntityIds'],
                              sourceDraftId=row['draftId'], revision=draft['revision']))
        order = [id_by_kind[next(row['kind'] for row in tasks
                                 if row['oldTaskId'] == task_id)]
                 for task_id in old['spec']['taskOrder']]
        if change['action'] == 'add':
            order.append(id_by_kind[change_kind])
        vehicles = sorted({vehicle for row in tasks for vehicle in row['candidateEntityIds']})
        return dict(identity=active['identity'], activeSnapshot=active,
                    initialPlanId=initial['planId'], initialReviewSHA256=initial['reviewSHA256'],
                    oldTaskIds=sorted(old_ids), change=change, tasks=tasks,
                    relationship=old['spec']['relationship'], taskOrder=order,
                    vehicleIds=vehicles,
                    sequenceVehicleId=self.assignment_contract['sequenceVehicleId'])

    def plan(self, body):
        with self.lock:
            spec = self.validate(body)
            key = body['idempotencyKey']
            fingerprint = assignment.digest(body)
            operation = self.operations / (key + '.json')
            if operation.exists():
                old = core.release.load(operation)
                require(old['fingerprint'] == fingerprint, 'Replanning key reused')
                return old
            plan_id = uuid.uuid4().hex
            planner_id = uuid.uuid4().hex
            spec_file = self.root / (plan_id + '-input.json')
            assignment.save(spec_file, spec)
            command = [str(sys.executable), '-I', '-B', '-X', 'utf8',
                       str(ROOT / 'scripts/g6_replanning/plan.py'), '--session',
                       str(self.session_file), '--input', str(spec_file), '--run-id', planner_id]
            try:
                done = subprocess.run(command, capture_output=True, timeout=100,
                                      creationflags=subprocess.CREATE_NO_WINDOW)
                (self.root / (plan_id + '.stdout')).write_bytes(done.stdout)
                (self.root / (plan_id + '.stderr')).write_bytes(done.stderr)
                require(done.returncode == 0, 'Isolated live-state planner failed')
                source = ROOT / 'out/runs/g6-b06-plan' / planner_id
                receipt = core.release.load(source / 'result.json')
                require(receipt['status'] == 'passed' and receipt['isolatedPlannerQualified'],
                        'Isolated live-state planner rejected the request')
                live.unchanged(spec['activeSnapshot'], live.settled_snapshot(self.session_file))
                old_plan = core.release.load(self.session_file.parent /
                    'task-assignment/plans' / (spec['initialPlanId'] + '.json'))['review']['plan']
                old_by_vehicle = {row['vehicleId']: row for row in old_plan['commands']}
                differences = []
                for command_row in receipt['plan']['commands']:
                    prior = old_by_vehicle.get(command_row['vehicleId'])
                    differences.append(dict(vehicleId=command_row['vehicleId'],
                        oldWaypointCount=len(prior['waypoints']) if prior else 0,
                        newWaypointCount=len(command_row['waypoints']),
                        oldRouteMeters=prior['timeBudget']['routeMeters'] if prior else 0,
                        newRouteMeters=command_row['timeBudget']['routeMeters']))
                review = dict(planId=plan_id, identity=spec['identity'],
                    change=spec['change'], taskOrder=spec['taskOrder'],
                    tasks=[{key: row[key] for key in
                            ('taskId', 'oldTaskId', 'kind', 'revision', 'candidateEntityIds')}
                           for row in spec['tasks']],
                    oldCoverage=spec['activeSnapshot']['coverageSummary'],
                    pausedAtMs=spec['activeSnapshot']['simulationTimeMs'],
                    oldPlanId=spec['initialPlanId'], plan=receipt['plan'],
                    differences=differences,
                    confirmationAllowed=receipt['plan']['timeBudgetFits'],
                    plannerRunId=planner_id,
                    responseXmlSHA256=receipt['responseXmlSHA256'])
                review['reviewSHA256'] = assignment.digest(review)
                assignment.save(self.plans / (plan_id + '.json'),
                                dict(spec=spec, review=review, plannerRunId=planner_id))
                result = dict(status='previewed', key=key, fingerprint=fingerprint,
                              planId=plan_id, review=review)
            except Exception as error:
                result = dict(status='rejected', key=key, fingerprint=fingerprint,
                              error=str(error))
            assignment.save(operation, result)
            return result

    def review(self, plan_id):
        require(isinstance(plan_id, str) and HEX.fullmatch(plan_id), 'Unknown replacement plan')
        path = self.plans / (plan_id + '.json')
        require(path.is_file(), 'Unknown replacement plan')
        row = core.release.load(path)
        self.recheck(row)
        return row['review']

    def recheck(self, row):
        spec, review = row['spec'], row['review']
        live.unchanged(spec['activeSnapshot'], live.settled_snapshot(self.session_file))
        require(review['reviewSHA256'] == assignment.digest({key: value
                for key, value in review.items() if key != 'reviewSHA256'}),
                'Replacement review digest changed')
        source = ROOT / 'out/runs/g6-b06-plan' / row['plannerRunId']
        receipt = core.release.load(source / 'result.json')
        require(receipt['status'] == 'passed' and receipt['isolatedPlannerQualified'] and
                receipt['inputSHA256'] == core.release.digest(source / 'input.json') and
                receipt['plannerLogSHA256'] == core.release.digest(source / 'planner.jsonl') and
                receipt['responseXmlSHA256'] == core.release.digest(source / 'response.xml') and
                receipt['uniqueRequestSHA256'] == core.release.digest(source / 'unique-request.xml') and
                receipt['uniqueResponseSHA256'] == core.release.digest(source / 'unique-response.xml') and
                receipt['plan'] == review['plan'], 'Replacement planner evidence changed')
        for task in spec['tasks']:
            file = source / ('task-' + task['taskId'] + '.xml')
            expected = next(item['taskSHA256'] for item in receipt['sourceDrafts']
                            if item['taskId'] == task['taskId'])
            require(core.release.digest(file) == expected, 'Replacement task bytes changed')
        return source

    def confirmation(self, key):
        require(isinstance(key, str) and KEY.fullmatch(key), 'Unknown replacement operation')
        path = self.switches / (key + '.json')
        require(path.is_file(), 'Unknown replacement operation')
        row = core.release.load(path)
        if row['status'] in ('switched', 'executing', 'completed'):
            events = core.observer_rows(self.session_file)
            stages = []
            for task in row['tasks']:
                active = [event for event in events if event['type'] ==
                          'uxas.messages.task.TaskActive' and event.get('taskId') == task['taskId']]
                complete = [event for event in events if event['type'] ==
                            'uxas.messages.task.TaskComplete' and event.get('taskId') == task['taskId']]
                stages.append(dict(taskId=task['taskId'], revision=task['revision'],
                    status='completed' if complete else 'active' if active else 'assigned',
                    taskActiveSHA256=active[0]['rawSHA256'] if active else None,
                    taskCompleteSHA256=complete[0]['rawSHA256'] if complete else None))
            row['taskStages'] = stages
            row['status'] = 'completed' if all(t['status'] == 'completed' for t in stages) else \
                'executing' if any(t['status'] != 'assigned' for t in stages) else 'switched'
            late = [event['rawSHA256'] for event in events[row['observerRowCountBeforeSwitch']:]
                    if event['type'] == 'uxas.messages.task.TaskComplete' and
                    event.get('taskId') in row['oldTaskIds']]
            row['lateOldCompletionSHA256'] = late
        return row

    def switch(self, plan_id, body):
        require(isinstance(body, dict) and set(body) == set(IDENTITY) |
                {'reviewSHA256', 'idempotencyKey', 'acknowledged'} and
                body['acknowledged'] is True, 'Replacement confirmation fields differ')
        key = body['idempotencyKey']
        require(isinstance(key, str) and KEY.fullmatch(key), 'Invalid confirmation key')
        fingerprint = assignment.digest(dict(planId=plan_id, body=body))
        path = self.switches / (key + '.json')
        with self.lock:
            if path.exists():
                old = core.release.load(path)
                require(old['fingerprint'] == fingerprint, 'Confirmation key reused')
                return self.confirmation(key)
            require(not list(self.switches.glob('*.json')),
                    'Another replacement has been attempted in this segment')
            require(isinstance(plan_id, str) and HEX.fullmatch(plan_id), 'Unknown plan')
            plan_path = self.plans / (plan_id + '.json')
            require(plan_path.is_file(), 'Unknown plan')
            plan_row = core.release.load(plan_path)
            source = self.recheck(plan_row)
            review, spec = plan_row['review'], plan_row['spec']
            require(review['confirmationAllowed'] and
                    body['reviewSHA256'] == review['reviewSHA256'] and
                    all(body[name] == spec['identity'][name] for name in IDENTITY),
                    'Replacement review or identity changed')
            row = dict(task='G6-B06', key=key, planId=plan_id,
                       fingerprint=fingerprint, reviewSHA256=review['reviewSHA256'],
                       oldTaskIds=spec['oldTaskIds'], tasks=review['tasks'],
                       status='pending', phase='prepared', **spec['identity'])
            assignment.save(path, row)
        return self.activate(path, row, review, spec, source)

    def activate(self, path, row, review, spec, source):
        try:
            old_snapshot = self.session_file.parents[1] / 'coverage/live.json'
            coverage = json.loads(old_snapshot.read_bytes())
            summary = [{key: task[key] for key in
                ('taskId', 'kind', 'seenCells', 'totalCells', 'observationMilliseconds')}
                for task in coverage['tasks']]
            require(coverage['runId'] == spec['identity']['backendRunId'] and
                    summary == spec['activeSnapshot']['coverageSummary'],
                    'Old coverage changed before switch')
            archive = self.root / (row['key'] + '-old-coverage.json')
            assignment.save(archive, coverage)
            row['oldCoverageSHA256'] = core.release.digest(archive)
            row['oldCoverageCursor'] = coverage['cursor']
            events = core.observer_rows(self.session_file)
            row['observerRowCountBeforeSwitch'] = len(events)
            journal = self.session_file.parent / 'uxas/datawork/SavedMessages/messageLog_1_0.db3'
            for task in review['tasks']:
                obj = core.lmcp_object(source / ('task-' + task['taskId'] + '.xml'))
                packet, sha = assignment.packet(obj, obj.FULL_LMCP_TYPE_NAME)
                row['phase'] = 'new-task-' + task['taskId'] + '-attempted'
                assignment.save(path, row)
                assignment.send_logged(packet, obj.FULL_LMCP_TYPE_NAME, journal,
                                       self.switches, row['key'] + '-task-' + task['taskId'])
                row.setdefault('newTaskRawSHA256', {})[task['taskId']] = sha
                assignment.save(path, row)
            target = {task['taskId'] for task in review['tasks']}
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                initialized = {event.get('taskId') for event in core.observer_rows(self.session_file)
                               if event['type'] == 'uxas.messages.task.TaskInitialized'}
                if initialized >= target:
                    break
                time.sleep(.1)
            require(initialized >= target, 'New tasks did not initialize')
            request = core.lmcp_object(source / 'unique-request.xml')
            request.SandBoxRequest = False
            response = core.lmcp_object(source / 'unique-response.xml')
            plan = core.lmcp_object(source / 'response.xml', 'AutomationResponse')
            embedded = core.lmcp_object(source / 'unique-response.xml', 'AutomationResponse')
            require(bytes(assignment.LMCPFactory.packMessage(plan, True)) ==
                    bytes(assignment.LMCPFactory.packMessage(embedded, True)),
                    'Replacement assignment embeds another plan')
            for label, obj in (('unique-request', request), ('unique-response', response),
                               ('automation-response', plan)):
                packet, sha = assignment.packet(obj, obj.FULL_LMCP_TYPE_NAME)
                row['phase'] = label + '-attempted'
                assignment.save(path, row)
                assignment.send_logged(packet, obj.FULL_LMCP_TYPE_NAME, journal,
                                       self.switches, row['key'] + '-' + label)
                row.setdefault('contextRawSHA256', {})[label] = sha
                assignment.save(path, row)
            expected = {command['vehicleId'] for command in review['plan']['commands']}
            expected_points = {command['vehicleId']:
                {point['number']: point for point in command['waypoints']}
                for command in review['plan']['commands']}
            before = set(spec['activeSnapshot']['commandHashes'])
            deadline = time.monotonic() + 30
            observed = []
            while time.monotonic() < deadline:
                observed = []
                for event in core.observer_rows(self.session_file):
                    vehicle = event.get('vehicleId')
                    if event['type'] != 'afrl.cmasi.MissionCommand' or \
                            event.get('sourceEntity') != '100' or vehicle not in expected or \
                            event['rawSHA256'] in before:
                        continue
                    node = ET.fromstring(base64.b64decode(event['xmlBase64']))
                    points = node.findall('WaypointList/Waypoint')
                    planned = expected_points[vehicle]
                    if len(points) < 2 or any(
                        point.findtext('Number') not in planned or
                        abs(float(point.findtext('Longitude')) -
                            planned[point.findtext('Number')]['longitude']) > 1e-7 or
                        abs(float(point.findtext('Latitude')) -
                            planned[point.findtext('Number')]['latitude']) > 1e-7
                        for point in points):
                        continue
                    observed.append(event)
                if {event['vehicleId'] for event in observed} >= expected:
                    break
                time.sleep(.1)
            require({event['vehicleId'] for event in observed} >= expected,
                    'Replacement mission commands were not observed')
            row['newMissionCommands'] = [{key: event.get(key) for key in
                ('vehicleId', 'commandId', 'rawSHA256')} for event in observed]
            row['phase'] = 'new-commands-observed'
            assignment.save(path, row)
            removal = RemoveTasks()
            removal.TaskList = list(map(int, spec['oldTaskIds']))
            packet, sha = assignment.packet(removal, removal.FULL_LMCP_TYPE_NAME)
            row['phase'] = 'remove-old-attempted'
            assignment.save(path, row)
            assignment.send_logged(packet, removal.FULL_LMCP_TYPE_NAME, journal,
                                   self.switches, row['key'] + '-remove-old')
            row['removeOldRawSHA256'] = sha
            row['phase'] = 'old-tasks-removed'
            assignment.save(path, row)
            state = control('GET', 'state')
            require(state['simulation']['state'] == 2 and
                    state['streamId'] == spec['identity']['streamId'] and
                    state['simulation']['simulation_time_ms'] ==
                    spec['activeSnapshot']['simulationTimeMs'],
                    'Simulation changed before replacement resume')
            resume_key = 'g6-b06-resume-' + hashlib.sha256(row['key'].encode()).hexdigest()[:32]
            row['phase'] = 'resume-attempted'
            row['resumeKey'] = resume_key
            assignment.save(path, row)
            resumed = control('POST', 'operations', dict(runId=row['runId'],
                segmentId=row['segmentId'], expectedSequence=state['controlSequence'],
                idempotencyKey=resume_key, action='resume', multiple=None))
            require(resumed['status'] == 'confirmed', 'Replacement resume not confirmed')
            row['resumeReceipt'] = resumed
            row['phase'] = 'replacement-resumed'
            row['status'] = 'switched'
            assignment.save(path, row)
        except Exception as error:
            row.update(status='uncertain', error=str(error))
            assignment.save(path, row)
        return row


def application(store):
    app = FastAPI(title='G6 controlled replanning', docs_url=None, redoc_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=[ORIGIN],
                       allow_methods=['GET', 'POST'], allow_headers=['Content-Type'])

    async def content(request):
        if request.headers.get('origin') != ORIGIN:
            raise HTTPException(403, 'Replanning origin rejected')
        if request.headers.get('content-type', '').split(';')[0].lower() != 'application/json':
            raise HTTPException(415, 'JSON required')
        raw = await request.body()
        if len(raw) > 65536:
            raise HTTPException(413, 'Replanning payload too large')
        try:
            return json.loads(raw)
        except (ValueError, UnicodeDecodeError) as error:
            raise HTTPException(422, 'Invalid JSON') from error

    @app.get('/api/tasks/v3/state')
    def state():
        return store.state()

    @app.post('/api/tasks/v3/plans')
    async def plan(request: HttpRequest):
        import asyncio
        try:
            result = await asyncio.to_thread(store.plan, await content(request))
            return JSONResponse(result, status_code=200 if result['status'] == 'previewed' else 409)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.get('/api/tasks/v3/plans/{plan_id}')
    def review(plan_id: str):
        try:
            return store.review(plan_id)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.get('/api/tasks/v3/operations/{key}')
    def operation(key: str):
        if not KEY.fullmatch(key):
            raise HTTPException(404, 'Unknown replanning operation')
        path = store.operations / (key + '.json')
        if not path.is_file():
            raise HTTPException(404, 'Unknown replanning operation')
        return core.release.load(path)

    @app.post('/api/tasks/v3/plans/{plan_id}/confirm')
    async def confirm(plan_id: str, request: HttpRequest):
        import asyncio
        try:
            result = await asyncio.to_thread(store.switch, plan_id, await content(request))
            return JSONResponse(result, status_code=200 if result['status'] in
                                ('switched', 'executing', 'completed') else 409)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.get('/api/tasks/v3/confirmations/{key}')
    def confirmation(key: str):
        try:
            return store.confirmation(key)
        except ValueError as error:
            raise HTTPException(404, str(error)) from error

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session', type=Path, required=True)
    args = parser.parse_args()
    store = ReplanningStore(args.session)
    uvicorn.run(application(store), host='127.0.0.1', port=8006,
                access_log=False, log_level='warning')


if __name__ == '__main__':
    main()
