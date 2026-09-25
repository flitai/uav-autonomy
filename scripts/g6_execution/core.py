"""Resolve the exact B02 preview bytes selected for G6-B04 review and activation."""
import base64
import hashlib
import json
from pathlib import Path
import sys
import xml.dom.minidom
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'out/generated/lmcp/py'))
sys.path.insert(0, str(ROOT / 'scripts/g6_release'))
import manage as release
sys.path.insert(0, str(ROOT / 'scripts/g6_planning'))
import isolated_preview
from lmcp import LMCPFactory


def need(value, message):
    if not value:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def lmcp_object(path, tag=None):
    document = xml.dom.minidom.parse(str(path))
    node = document.documentElement if tag is None else document.getElementsByTagName(tag)[0]
    return lmcp_node(node)


def lmcp_node(node):
    factory = LMCPFactory.LMCPFactory()
    result = factory.createObjectByName(node.getAttribute('Series'), node.localName)
    need(result is not None, 'Unknown LMCP message in qualified preview')
    result.unpackFromXMLNode(node, factory)
    return result


def observer_rows(session_file):
    path = session_file.parent / 'observer.jsonl'
    result = []
    if path.exists():
        with path.open(encoding='utf-8') as source:
            for line in source:
                try:
                    result.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return result


def resolve(session_file, plan_id, require_frozen=True):
    need(isinstance(plan_id, str) and len(plan_id) == 32 and
         all(char in '0123456789abcdef' for char in plan_id), 'Invalid plan ID')
    session_file = Path(session_file).resolve()
    active = isolated_preview.active_evidence(session_file) if require_frozen else None
    items = []
    for path in (session_file.parent / 'task-drafts/items').glob('*.json'):
        item = release.load(path)
        if item.get('preview') and item['preview'].get('planId') == plan_id:
            items.append(item)
    need(len(items) == 1, 'Selected plan is not an active saved draft preview')
    item = items[0]
    draft, plan = item['draft'], item['preview']
    need(plan['revision'] == draft['revision'] and plan['taskId'] == draft['taskId'] and
         plan['route']['vehicleId'] == draft['candidateEntityIds'][0],
         'Plan differs from saved draft revision or assignment')
    preview_rows = [release.load(path) for path in (session_file.parent / 'task-previews').glob('*.json')]
    sources = [row for row in preview_rows if row.get('planId') == plan_id and
               row.get('status') == 'previewed']
    need(len(sources) == 1 and sources[0]['plan'] == plan,
         'B02 original preview receipt differs')
    source = sources[0]
    identity = {name: source[name] for name in ('runId', 'segmentId', 'backendRunId', 'streamId')}
    need(all(plan[name] == value for name, value in identity.items()) and
         draft['runId'] == identity['runId'] and draft['segmentId'] == identity['segmentId'],
         'Plan, draft and source identity differ')
    if active:
        need(all(active[name] == value for name, value in identity.items()),
             'Plan source is stale against the active frozen session')
        need(active['forbiddenRows'] == [], 'Active execution already has planning or commands')
    planner = ROOT / 'out/runs' / (source['previewRunId'] + '-planner')
    result = release.load(planner / 'result.json')
    need(result['status'] == 'passed' and result['previewIsolationQualified'] and
         result['previews'][0]['responseSHA256'] == plan['responseSHA256'],
         'Qualified isolated planner receipt differs')
    task_file = planner / 'candidate-task.xml'
    plan_file = planner / ('plan-' + draft['taskId'] + '.xml')
    need(release.digest(task_file).lower() == plan['candidateTaskSHA256'].lower() and
         release.digest(plan_file).lower() == plan['responseXmlSHA256'].lower(),
         'Preview XML bytes changed')
    task = lmcp_object(task_file)
    response = lmcp_object(plan_file, 'AutomationResponse')
    task_bytes = LMCPFactory.packMessage(task, True)
    plan_bytes = LMCPFactory.packMessage(response, True)
    planner_rows = observer_rows_for(planner / 'planner.jsonl')
    unique_requests = [row for row in planner_rows if row['type'] ==
                       'uxas.messages.task.UniqueAutomationRequest']
    unique_responses = [row for row in planner_rows if row['type'] ==
                        'uxas.messages.task.UniqueAutomationResponse']
    need(len(unique_requests) == len(unique_responses) == 1 and
         unique_requests[0]['requestId'] == unique_responses[0]['responseId'] ==
         result['previews'][0]['requestId'],
         'Preview assignment context is ambiguous')
    request_xml = base64.b64decode(unique_requests[0]['xmlBase64'])
    response_xml = base64.b64decode(unique_responses[0]['xmlBase64'])
    unique_request = lmcp_node(xml.dom.minidom.parseString(request_xml).documentElement)
    unique_request.SandBoxRequest = False
    unique_response = lmcp_node(xml.dom.minidom.parseString(response_xml).documentElement)
    embedded = xml.dom.minidom.parseString(response_xml).getElementsByTagName('AutomationResponse')[0]
    need(LMCPFactory.packMessage(lmcp_node(embedded), True) == plan_bytes,
         'Activation context embeds a different plan')
    request_bytes = LMCPFactory.packMessage(unique_request, True)
    response_context_bytes = LMCPFactory.packMessage(unique_response, True)
    root = ET.parse(plan_file).getroot()
    commands = root.findall('OriginalResponse/AutomationResponse/MissionCommandList/MissionCommand')
    need(len(commands) == 1 and commands[0].findtext('VehicleID') == plan['route']['vehicleId'],
         'Preview assignment differs')
    command = commands[0]
    points = command.findall('WaypointList/Waypoint')
    need(len(points) == plan['route']['waypointCount'] and len(points) >= 2,
         'Preview route differs')
    action = lambda node: dict(type=node.tag,
        taskIds=[x.text for x in node.findall('AssociatedTaskList/int64')],
        payloadId=node.findtext('PayloadID'))
    actions = [action(node) for node in command.findall('VehicleActionList/*')]
    waypoints = []
    for index, point in enumerate(points):
        expected = plan['route']['waypoints'][index]
        need(point.findtext('Number') == expected['number'] and
             point.findtext('NextWaypoint') == expected['nextWaypoint'] and
             abs(float(point.findtext('Longitude')) - expected['longitude']) < 1e-9 and
             abs(float(point.findtext('Latitude')) - expected['latitude']) < 1e-9,
             'Full route differs from B02 display route')
        waypoints.append(dict(**expected, actions=[action(node) for node in
                              point.findall('VehicleActionList/*')]))
    need(any(draft['taskId'] in row['taskIds'] for row in actions) or
         any(draft['taskId'] in action_row['taskIds'] for point in waypoints
             for action_row in point['actions']) or
         draft['taskId'] in {node.text for node in command.findall('.//AssociatedTasks/int64')},
         'Preview has no task association')
    review = dict(planId=plan_id, draftId=draft['draftId'], revision=draft['revision'],
                  kind=draft['kind'], taskId=draft['taskId'], identity=identity,
                  assignment=dict(vehicleId=plan['route']['vehicleId'], order=[draft['taskId']]),
                  commandId=command.findtext('CommandID'),
                  taskBytesSHA256=digest(task_bytes), planBytesSHA256=digest(plan_bytes),
                  assignmentRequestSHA256=digest(request_bytes),
                  assignmentResponseSHA256=digest(response_context_bytes),
                  responseXmlSHA256=plan['responseXmlSHA256'],
                  responseRawSHA256=plan['responseSHA256'],
                  actions=actions, waypoints=waypoints,
                  previewRunId=source['previewRunId'],
                  simulationTimeMs='0', confirmationAllowed=bool(active))
    review['reviewSHA256'] = digest(json.dumps(review, sort_keys=True,
                                             ensure_ascii=False).encode('utf-8'))
    return review, task_bytes, request_bytes, response_context_bytes, plan_bytes


def observer_rows_for(path):
    rows = []
    with path.open(encoding='utf-8') as source:
        for line in source:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows
