"""Exercise B03 draft persistence and real isolated preview in a live session."""
import argparse
import copy
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/g6_planning'))
import isolated_preview

URL = 'http://127.0.0.1:8003/api/tasks/v1'


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def need(value, message):
    if not value:
        raise AssertionError(message)


def http(method, path, body=None, origin=True):
    headers = {'Origin': 'http://127.0.0.1:8080'} if origin else {}
    data = None
    if body is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(body).encode('utf-8')
    try:
        with urlopen(Request(URL + path, data=data, headers=headers, method=method), timeout=70) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    session = args.session.resolve()
    before = isolated_preview.active_evidence(session)
    record = dict(task='G6-B03', status='running', steps=[])
    try:
        code, catalog = http('GET', '/catalog')
        need(code == 200 and catalog['identity']['streamId'] == before['streamId'],
             'Catalog run identity differs')
        identity = catalog['identity']
        source = load(ROOT / 'out/runs/g6-b01-baseline-20260924-2223/samples/point-draft.json')
        fields = dict(identity, kind='point', geometry=source['geometry'],
                      candidateEntityIds=['500'], altitudeDatum=catalog['altitudeDatum'])
        create = dict(fields, idempotencyKey='g6-b03-api-create-point')
        code, saved = http('POST', '/drafts', create)
        need(code == 201 and saved['action'] == 'create' and
             saved['draft']['draft']['revision'] == '1', 'Point draft creation failed')
        draft_id = saved['draft']['draft']['draftId']
        need(http('POST', '/drafts', create) == (201, saved), 'Create idempotency differs')
        record['steps'].append(dict(action='create',draftId=draft_id,revision='1'))
        changed = copy.deepcopy(fields)
        changed['geometry']['coordinates'][0] += .001
        changed.update(expectedRevision='1', idempotencyKey='g6-b03-api-update-point')
        code, updated = http('PUT', '/drafts/' + draft_id, changed)
        need(code == 200 and updated['draft']['draft']['revision'] == '2' and
             updated['draft']['preview'] is None, 'Point draft revision did not advance')
        record['steps'].append(dict(action='update',revision='2'))
        stale = dict(changed, idempotencyKey='g6-b03-api-stale-update')
        need(http('PUT', '/drafts/' + draft_id, stale)[0] == 409, 'Stale draft revision accepted')
        wrong_datum = dict(fields, idempotencyKey='g6-b03-api-wrong-datum', altitudeDatum='EPSG:4979')
        need(http('POST', '/drafts', wrong_datum)[0] == 422, 'Wrong height datum accepted')
        wrong_entity = dict(fields, idempotencyKey='g6-b03-api-wrong-entity', candidateEntityIds=['400'])
        need(http('POST', '/drafts', wrong_entity)[0] == 422, 'Wrong entity accepted')
        wrong_geometry = copy.deepcopy(fields)
        wrong_geometry['geometry']['altitudeMeters'] = 0
        wrong_geometry['idempotencyKey'] = 'g6-b03-api-extra-height'
        need(http('POST', '/drafts', wrong_geometry)[0] == 422, 'Editable height accepted')
        outside = copy.deepcopy(fields)
        outside['geometry']['coordinates'] = [45.323,-120.7645]
        outside['idempotencyKey'] = 'g6-b03-api-swapped-coordinate'
        need(http('POST', '/drafts', outside)[0] == 422, 'Reversed longitude/latitude accepted')
        need(http('POST', '/drafts', dict(fields,idempotencyKey='g6-b03-api-no-origin'),False)[0] == 403,
             'Untrusted Origin accepted')
        record['steps'].append(dict(action='negative-inputs',rejected=6))
        preview_body = dict(identity,idempotencyKey='g6-b03-api-preview-point',expectedRevision='2')
        code, planned = http('POST', '/drafts/' + draft_id + '/preview', preview_body)
        need(code == 200 and planned['action'] == 'preview' and
             planned['draft']['preview']['route']['waypointCount'] >= 2 and
             not planned['draft']['preview']['confirmationEnabled'],
             'Saved point draft did not yield a real preview')
        need(http('POST', '/drafts/' + draft_id + '/preview', preview_body) == (200, planned),
             'Preview idempotency differs')
        operation = load(session.parent / 'task-previews/g6-b03-api-preview-point.json')
        candidate = ROOT / 'out/runs' / (operation['previewRunId'] + '-planner') / 'candidate-task.xml'
        task = ET.parse(candidate).getroot()
        longitude = float(task.findtext('SearchLocation/Location3D/Longitude'))
        latitude = float(task.findtext('SearchLocation/Location3D/Latitude'))
        need(abs(longitude-changed['geometry']['coordinates'][0]) < 1e-10 and
             abs(latitude-changed['geometry']['coordinates'][1]) < 1e-10,
             'Planner task bytes do not match the saved draft revision')
        code, fetched = http('GET', '/drafts/' + draft_id)
        need(code == 200 and fetched == planned['draft'], 'Saved plan was not restored')
        code, listed = http('GET', '/drafts')
        need(code == 200 and len(listed['items']) == 1 and listed['items'][0] == fetched,
             'Draft listing did not restore the plan')
        record['steps'].append(dict(action='preview',planId=planned['draft']['preview']['planId'],
                                    responseSHA256=planned['draft']['preview']['responseSHA256'],
                                    waypointCount=planned['draft']['preview']['route']['waypointCount'],
                                    candidateTask=str(candidate)))
        changed_again = copy.deepcopy(fields)
        changed_again['geometry']['coordinates'][0] += .002
        changed_again.update(expectedRevision='2',idempotencyKey='g6-b03-api-update-after-preview')
        code, invalidated = http('PUT', '/drafts/' + draft_id, changed_again)
        need(code == 200 and invalidated['draft']['draft']['revision'] == '3' and
             invalidated['draft']['preview'] is None, 'Revision change did not invalidate preview')
        record['steps'].append(dict(action='invalidate-plan',revision='3'))
        copy_body = dict(identity,idempotencyKey='g6-b03-api-copy-point',expectedRevision='3')
        code, duplicated = http('POST', '/drafts/' + draft_id + '/copy', copy_body)
        need(code == 201 and duplicated['draft']['draft']['draftId'] != draft_id and
             duplicated['draft']['draft']['revision'] == '1' and
             duplicated['draft']['preview'] is None, 'Draft copy differs')
        copy_id = duplicated['draft']['draft']['draftId']
        delete_body = dict(identity,idempotencyKey='g6-b03-api-delete-copy',expectedRevision='1')
        need(http('DELETE', '/drafts/' + copy_id, delete_body)[0] == 200 and
             http('GET', '/drafts/' + copy_id)[0] == 404, 'Copied draft was not deleted')
        record['steps'].append(dict(action='copy-delete',copyId=copy_id))
        after = isolated_preview.active_evidence(session)
        need(before['uxasProcess'] == after['uxasProcess'] and
             before['streamId'] == after['streamId'] and
             before['forbiddenRows'] == after['forbiddenRows'] and
             before['movingStateCount'] == after['movingStateCount'] == 0,
             'Draft workflow changed active mission execution')
        record.update(status='passed', activeBefore=before,activeAfter=after,
                      draftId=draft_id,planId=planned['draft']['preview']['planId'])
        return 0
    except Exception as error:
        record.update(status='failed',error=str(error))
        print(error,file=sys.stderr)
        return 1
    finally:
        (output / 'result.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__ == '__main__':
    sys.exit(main())
