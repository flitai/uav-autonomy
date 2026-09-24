"""G6-B01: bind the first task contract to real qualified scene inputs."""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import traceback
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/g6_release'))
import manage as release


def need(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    return release.digest(path)


def load(path):
    return release.load(path)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    release.save(path, value)


def number(value, label):
    need(type(value) in (int, float) and math.isfinite(value), label + ' must be finite')
    return float(value)


def identifier(value, label, positive=True):
    need(isinstance(value, str) and re.fullmatch(r'(0|[1-9][0-9]*)', value), label + ' must be a decimal string')
    count = int(value)
    need(count <= 9223372036854775807 and (not positive or count > 0), label + ' exceeds int64 range')
    return value


def in_bounds(point, bounds):
    need(isinstance(point, list) and len(point) == 2, 'Coordinate pair required')
    lon, lat = (number(value, 'Coordinate') for value in point)
    need(bounds['west'] <= lon <= bounds['east'] and bounds['south'] <= lat <= bounds['north'],
         'Coordinate outside qualified terrain')
    return lon, lat


def validate_draft(draft, contract):
    need(isinstance(draft, dict) and set(draft) == {'schemaVersion', 'contractId', 'runId',
         'segmentId', 'draftId', 'revision', 'taskId', 'kind', 'candidateEntityIds',
         'geometry', 'parameters'}, 'Draft fields differ')
    need(draft['schemaVersion'] == 1 and draft['contractId'] == contract['contractId'], 'Draft version differs')
    need(all(isinstance(draft[key], str) and draft[key] for key in ('runId', 'segmentId', 'draftId')),
         'Draft identity missing')
    identifier(draft['revision'], 'Revision')
    identifier(draft['taskId'], 'Task ID')
    kind = draft['kind']
    need(kind in contract['taskTypes'], 'Unsupported task type')
    task = contract['taskTypes'][kind]
    need(draft['candidateEntityIds'] == task['baselineEntityIds'], 'Entity eligibility differs')
    for entity in draft['candidateEntityIds']:
        identifier(entity, 'Entity ID')
    need(draft['parameters'] == contract['searchParameters'], 'Unqualified search parameters')
    geometry, bounds = draft['geometry'], contract['qualifiedTerrainBoundsDegrees']
    need(isinstance(geometry, dict) and geometry.get('type') == task['geometry'], 'Geometry type differs')
    if kind == 'point':
        need(set(geometry) == {'type', 'coordinates'}, 'Point geometry fields differ')
        in_bounds(geometry['coordinates'], bounds)
    elif kind == 'line':
        need(set(geometry) == {'type', 'coordinates'}, 'Line geometry fields differ')
        coordinates = geometry['coordinates']
        minimum, maximum = contract['limits']['linePointCount']
        need(isinstance(coordinates, list) and minimum <= len(coordinates) <= maximum,
             'Line point count outside contract')
        previous = None
        for point in coordinates:
            current = in_bounds(point, bounds)
            need(current != previous, 'Consecutive duplicate line point')
            previous = current
    else:
        need(set(geometry) == {'type', 'center', 'widthMeters', 'heightMeters', 'rotationDegrees'},
             'Rectangle geometry fields differ')
        lon, lat = in_bounds(geometry['center'], bounds)
        width = number(geometry['widthMeters'], 'Rectangle width')
        height = number(geometry['heightMeters'], 'Rectangle height')
        need(contract['limits']['rectangleWidthMeters'][0] <= width <=
             contract['limits']['rectangleWidthMeters'][1] and
             contract['limits']['rectangleHeightMeters'][0] <= height <=
             contract['limits']['rectangleHeightMeters'][1], 'Rectangle dimensions outside contract')
        need(geometry['rotationDegrees'] == 0, 'Rectangle rotation is not qualified')
        half_lon = width / (2 * 111320 * math.cos(math.radians(lat)))
        half_lat = height / (2 * 111320)
        in_bounds([lon - half_lon, lat - half_lat], bounds)
        in_bounds([lon + half_lon, lat + half_lat], bounds)
    need(len(json.dumps(draft, ensure_ascii=False).encode('utf-8')) <= contract['limits']['requestBytes'],
         'Draft request budget exceeded')
    return True


def fields(document, name):
    node = document.find(".//Struct[@Name='" + name + "']")
    need(node is not None, 'Missing MDM struct ' + name)
    return {field.attrib['Name']: field.attrib for field in node.findall('Field')}


def assert_mdm():
    cm = ET.parse(ROOT / 'OpenUxAS/mdms/CMASI.xml').getroot()
    ux = ET.parse(ROOT / 'OpenUxAS/mdms/UXTASK.xml').getroot()
    expected = {
        'Task': {'TaskID': 'int64', 'EligibleEntities': 'int64[]', 'RevisitRate': 'real32'},
        'SearchTask': {'DwellTime': 'int64', 'GroundSampleDistance': 'real32',
                       'DesiredWavelengthBands': 'WavelengthBand[]'},
        'PointSearchTask': {'SearchLocation': 'Location3D', 'StandoffDistance': 'real32'},
        'LineSearchTask': {'PointList': 'Location3D[]', 'UseInertialViewAngles': 'bool'},
        'AreaSearchTask': {'SearchArea': 'AbstractGeometry'},
        'Location3D': {'Latitude': 'real64', 'Longitude': 'real64', 'Altitude': 'real32',
                       'AltitudeType': 'AltitudeType'},
        'Rectangle': {'CenterPoint': 'Location3D', 'Width': 'real32', 'Height': 'real32',
                      'Rotation': 'real32'},
        'AutomationRequest': {'EntityList': 'int64[]', 'TaskList': 'int64[]',
                              'TaskRelationships': 'string', 'OperatingRegion': 'int64',
                              'RedoAllTasks': 'bool'},
        'AutomationResponse': {'MissionCommandList': 'MissionCommand[]'},
    }
    for name, entries in expected.items():
        actual = fields(cm, name)
        for field, typ in entries.items():
            need(actual.get(field, {}).get('Type') == typ, name + '.' + field + ' changed')
    need(fields(cm, 'LineSearchTask')['PointList'].get('MaxArrayLength') == '1024',
         'Line MDM point budget changed')
    unique = fields(ux, 'UniqueAutomationRequest')
    task = fields(ux, 'TaskAutomationRequest')
    need(unique['SandBoxRequest']['Type'] == 'bool' and task['SandBoxRequest']['Type'] == 'bool' and
         fields(ux, 'TaskAutomationResponse')['ResponseID']['Type'] == 'int64',
         'Sandbox or response correlation model changed')
    return {'CMASI': digest(ROOT / 'OpenUxAS/mdms/CMASI.xml'),
            'UXTASK': digest(ROOT / 'OpenUxAS/mdms/UXTASK.xml')}


def assert_planning_chain():
    services = {
        'validator': ROOT / 'OpenUxAS/src/cpp/Services/AutomationRequestValidatorService.cpp',
        'builder': ROOT / 'OpenUxAS/src/cpp/Services/PlanBuilderService.cpp',
        'waypointManager': ROOT / 'OpenUxAS/src/cpp/Services/WaypointPlanManagerService.cpp',
    }
    contents = {name: path.read_text(encoding='utf-8-sig') for name, path in services.items()}
    need('setSandBoxRequest(taskAutomationRequest->getSandBoxRequest())' in contents['validator'] and
         'sendSharedLmcpObjectBroadcastMessage(taskResponse)' in contents['validator'],
         'Sandbox request/response path changed')
    need('sendSharedLmcpObjectBroadcastMessage(response)' in contents['builder'],
         'Unique planning response path changed')
    need('addSubscriptionAddress(afrl::cmasi::AutomationResponse::Subscription)' in
         contents['waypointManager'] and
         'for (auto mission : automationResponse->getMissionCommandList())' in
         contents['waypointManager'] and
         'sendSharedLmcpObjectBroadcastMessage(_nextMissionCommandToSend)' in
         contents['waypointManager'], 'Automatic waypoint implementation path changed')
    return {name: digest(path) for name, path in services.items()}


def text(node, path):
    value = node.findtext(path)
    need(value is not None, 'Scene XML field missing: ' + path)
    return value.strip()


def point(node):
    need(text(node, 'AltitudeType') == 'MSL', 'Task altitude type differs')
    return [float(text(node, 'Longitude')), float(text(node, 'Latitude'))]


def scene_drafts(scene, contract):
    scene_info = load(scene / 'scene.json')
    need(scene_info['schemaVersion'] == 1 and scene_info['heightDatum'] == contract['taskAltitudeDatum']
         and scene_info['terrainScenario'] and scene_info['durationSeconds'] == 1800,
         'Qualified scene datum or duration differs')
    for row in scene_info['inputs']:
        need(digest(ROOT / row['path']).lower() == row['sha256'].lower(), 'Scene source changed')
    for row in scene_info['files']:
        need(digest(scene / row['path']).lower() == row['sha256'].lower(), 'Scene file changed')
    scenario = ET.parse(scene / 'scenario.xml').getroot()
    configurations = {text(node, 'ID'): node for node in scenario.iter('AirVehicleConfiguration')}
    states = {text(node, 'ID') for node in scenario.iter('AirVehicleState')}
    need({'400', '500', '600'}.issubset(configurations) and {'400', '500', '600'}.issubset(states),
         'Baseline entities missing')
    drafts = []
    for kind, spec in contract['taskTypes'].items():
        task_id, entities = spec['baselineTaskId'], spec['baselineEntityIds']
        need(all(entity in configurations and entity in states for entity in entities),
             'Task entity missing from actual scenario')
        for entity in entities:
            payloads = {node.tag for node in configurations[entity].iter()}
            need({'CameraConfiguration', 'GimbalConfiguration'}.issubset(payloads),
                 'Task entity lacks qualified camera or gimbal')
        xml = ET.parse(scene / ('task-' + task_id + '.xml')).getroot()
        need(xml.tag == spec['lmcpType'].split('.')[-1] and text(xml, 'TaskID') == task_id and
             [node.text.strip() for node in xml.findall('EligibleEntities/int64')] == entities,
             'Real task type, ID or eligibility differs')
        fixed = contract['searchParameters']
        need(text(xml, 'DwellTime') == fixed['dwellTimeMs'] and
             float(text(xml, 'GroundSampleDistance')) == fixed['groundSampleDistanceMetersPerPixel'] and
             float(text(xml, 'RevisitRate')) == fixed['revisitRateSeconds'] and
             text(xml, 'DesiredWavelengthBands/WavelengthBand') == fixed['wavelengthBand'] and
             text(xml, 'Required').lower() == str(fixed['required']).lower() and
             int(text(xml, 'Priority')) == fixed['priority'] and not list(xml.find('ViewAngleList')),
             'Real task search parameters differ')
        if kind == 'point':
            need(float(text(xml, 'StandoffDistance')) == fixed['standoffDistanceMeters'],
                 'Point standoff differs')
            geometry = {'type': 'Point', 'coordinates': point(xml.find('SearchLocation/Location3D'))}
        elif kind == 'line':
            geometry = {'type': 'LineString', 'coordinates':
                        [point(node) for node in xml.findall('PointList/Location3D')]}
        else:
            rect = xml.find('SearchArea/Rectangle')
            need(rect is not None, 'Baseline area is not a rectangle')
            geometry = {'type': 'Rectangle', 'center': point(rect.find('CenterPoint/Location3D')),
                        'widthMeters': float(text(rect, 'Width')),
                        'heightMeters': float(text(rect, 'Height')),
                        'rotationDegrees': float(text(rect, 'Rotation'))}
        request = ET.parse(scene / ('request-' + task_id + '.xml')).getroot()
        need(request.tag == 'AutomationRequest' and
             [node.text.strip() for node in request.findall('EntityList/int64')] == entities and
             [node.text.strip() for node in request.findall('TaskList/int64')] == [task_id] and
             text(request, 'OperatingRegion') == fixed['operatingRegionId'] and
             text(request, 'RedoAllTasks').lower() == str(fixed['redoAllTasks']).lower() and
             not text(request, 'TaskRelationships'), 'Real request differs from fixed template')
        draft = dict(schemaVersion=1, contractId=contract['contractId'],
                     runId=contract['sourceSceneRunId'], segmentId=contract['sourceSegment'] + '-1',
                     draftId='sample-' + task_id, revision='1', taskId=task_id, kind=kind,
                     candidateEntityIds=entities, geometry=geometry,
                     parameters=contract['searchParameters'])
        validate_draft(draft, contract)
        drafts.append(draft)
    need(len(drafts) == contract['limits']['draftCount'], 'Draft count differs')
    return scene_info, drafts


def reject_cases(drafts, contract):
    variants = []
    point_draft = next(row for row in drafts if row['kind'] == 'point')
    line_draft = next(row for row in drafts if row['kind'] == 'line')
    area_draft = next(row for row in drafts if row['kind'] == 'area')
    for name, source, change in (
        ('nonzero-dwell', point_draft, lambda row: row['parameters'].update(dwellTimeMs='1')),
        ('wrong-entity', point_draft, lambda row: row.update(candidateEntityIds=['400'])),
        ('coordinate-order', point_draft, lambda row: row['geometry'].update(coordinates=[45.323, -120.7645])),
        ('duplicate-line-point', line_draft, lambda row: row['geometry']['coordinates'].insert(
            1, row['geometry']['coordinates'][0])),
        ('rectangle-outside-terrain', area_draft, lambda row: row['geometry'].update(center=[-119.9, 45.3])),
        ('editable-altitude', point_draft, lambda row: row['geometry'].update(altitudeMeters=100)),
        ('numeric-task-id', point_draft, lambda row: row.update(taskId=3001)),
    ):
        invalid = copy.deepcopy(source)
        change(invalid)
        try:
            validate_draft(invalid, contract)
        except ValueError as error:
            variants.append(dict(case=name, status='rejected', reason=str(error)))
        else:
            raise AssertionError('Invalid draft accepted: ' + name)
    return variants


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    need(re.fullmatch(r'g6-b01-[a-z0-9-]+', args.run_id), 'Invalid B01 run ID')
    run = ROOT / 'out/runs' / args.run_id
    need(not run.exists(), 'B01 run ID already exists')
    run.mkdir(parents=True)
    record = dict(task='G6-B01', runId=args.run_id, status='running', executionQualified=False)
    try:
        pointer, manifest = release.resolve()
        contract_path = ROOT / 'config/g6-task-contract-v1.json'
        contract = load(contract_path)
        need(contract['schemaVersion'] == 1 and contract['contractId'] == 'g6-b01-cmasi-search-v1',
             'Task contract version differs')
        source_run = contract['sourceSceneRunId']
        production = load(ROOT / 'out/runs' / source_run.removesuffix('-session') / 'production-result.json')
        need(production['status'] == 'passed' and production['sessionRunId'] == source_run and
             production['pointerSHA256'] == digest(ROOT / 'out/artifacts/g6-control/current.json') and
             production['runtimeSHA256'] == digest(ROOT / 'out/runs' / source_run / 'runtime-result.json'),
             'Real G6-A production run differs')
        scene = ROOT / 'out/runs' / source_run / contract['sourceSegment'] / 'scene'
        model_hashes = assert_mdm()
        service_hashes = assert_planning_chain()
        scene_info, drafts = scene_drafts(scene, contract)
        rejected = reject_cases(drafts, contract)
        sources = [contract_path, Path(__file__), ROOT / 'OpenUxAS/mdms/CMASI.xml',
                   ROOT / 'OpenUxAS/mdms/UXTASK.xml',
                   ROOT / 'OpenUxAS/src/cpp/Services/AutomationRequestValidatorService.cpp',
                   ROOT / 'OpenUxAS/src/cpp/Services/PlanBuilderService.cpp',
                   ROOT / 'OpenUxAS/src/cpp/Services/WaypointPlanManagerService.cpp']
        for draft in drafts:
            save(run / 'samples' / (draft['kind'] + '-draft.json'), draft)
        sample_binding = dict(runId=source_run, segmentId=contract['sourceSegment'] + '-1',
                              backendRunId=source_run + '/' + contract['sourceSegment'],
                              streamId='sample-stream-id', revision='1',
                              idempotencyKey='sample-preview-0001')
        save(run / 'samples/preview-request.design.json', dict(schemaVersion=1,
             contractId=contract['contractId'], binding=sample_binding,
             draftIds=[row['draftId'] for row in drafts],
             taskRevisions={row['draftId']: row['revision'] for row in drafts},
             status='illustrative-contract-only'))
        save(run / 'samples/confirm-request.design.json', dict(schemaVersion=1,
             contractId=contract['contractId'], binding={**sample_binding,
             'idempotencyKey': 'sample-confirm-0001'}, planId='sample-plan-0001',
             planVersion='1', planDigest='sha256-of-exact-preview-bytes',
             status='illustrative-contract-only'))
        record.update(status='passed', inputBaselineQualified=True, executionQualified=False,
                      g6PointerSHA256=digest(ROOT / 'out/artifacts/g6-control/current.json'),
                      g6ManifestSHA256=pointer['manifestSHA256'],
                      g5PointerSHA256=manifest['g5PointerSHA256'],
                      sourceSceneRunId=source_run, sceneJSONSHA256=digest(scene / 'scene.json'),
                      sourceSceneId=scene_info['sceneId'], modelSHA256=model_hashes,
                      planningServiceSHA256=service_hashes,
                      taskIds=[row['taskId'] for row in drafts],
                      entityIds=sorted({value for row in drafts for value in row['candidateEntityIds']}),
                      linePointCount=next(len(row['geometry']['coordinates']) for row in drafts if row['kind'] == 'line'),
                      negativeCases=rejected,
                      sources=[dict(path=path.relative_to(ROOT).as_posix(), sha256=digest(path))
                               for path in sources],
                      samples=[dict(path=path.relative_to(run).as_posix(), sha256=digest(path))
                               for path in sorted((run / 'samples').glob('*.json'))])
        save(run / 'acceptance.json', {key: record[key] for key in ('task', 'runId', 'status',
             'inputBaselineQualified', 'executionQualified', 'g6PointerSHA256', 'g6ManifestSHA256',
             'sourceSceneRunId', 'sceneJSONSHA256', 'sourceSceneId', 'taskIds', 'entityIds',
             'linePointCount', 'negativeCases', 'sources', 'samples')})
        return 0
    except Exception as error:
        record.update(status='failed', error=str(error), traceback=traceback.format_exc())
        print(record['traceback'], file=sys.stderr, flush=True)
        return 1
    finally:
        save(run / 'result.json', record)


if __name__ == '__main__':
    sys.exit(main())
