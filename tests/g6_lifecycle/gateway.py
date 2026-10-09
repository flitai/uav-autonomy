"""Restart the owned gateway around a paused replacement preview."""
import argparse
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests/g6_assignment'))
import flow as b05
sys.path.insert(0, str(ROOT / 'scripts/g6_replanning'))
import live

core = b05.core


def need(condition, message):
    if not condition:
        raise RuntimeError(message)


def execute(session, foreign):
    code, state = b05.http(8005, 'GET', '/api/tasks/v2/state')
    need(code == 200 and state['identity']['runId'] == session.parent.parent.name,
         'Gateway case session differs')
    identity = state['identity']
    samples = ROOT / 'out/runs/g6-b01-baseline-20260924-2223/samples'
    geometry = {
        'line': dict(type='LineString', coordinates=[[-120.9923, 45.3171],
                                                     [-120.97, 45.3171]]),
        'point': dict(type='Point', coordinates=[-120.977, 45.323]),
        'area': dict(type='Rectangle', center=[-120.974, 45.325],
                     widthMeters=500, heightMeters=300, rotationDegrees=0)}
    drafts = {}
    for kind in ('line', 'point', 'area'):
        sample = core.release.load(samples / (kind + '-draft.json'))
        code, row = b05.http(8003, 'POST', '/api/tasks/v1/drafts',
            dict(identity, idempotencyKey='g6-b07-gateway-draft-' + kind,
                 kind=kind, geometry=geometry[kind],
                 candidateEntityIds=sample['candidateEntityIds'],
                 altitudeDatum='EPSG:5773'))
        need(code in (200, 201) and row['status'] == 'confirmed',
             'Gateway case draft creation failed')
        drafts[kind] = row['draft']['draft']
    selections = [dict(draftId=drafts[kind]['draftId'],
                       revision=drafts[kind]['revision'], candidateEntityIds=['400'])
                  for kind in ('line', 'point')]
    code, planned = b05.http(8005, 'POST', '/api/tasks/v2/plans',
        dict(identity, idempotencyKey='g6-b07-gateway-initial-plan',
             tasks=selections, taskOrder=['3000', '3001'], relationship='sequence'))
    need(code == 200 and planned['status'] == 'previewed',
         'Gateway case initial plan failed: ' + str(planned))
    review = planned['review']
    code, confirmed = b05.http(8005, 'POST',
        '/api/tasks/v2/plans/' + review['planId'] + '/confirm',
        dict(identity, reviewSHA256=review['reviewSHA256'],
             idempotencyKey='g6-b07-gateway-initial-confirm', acknowledged=True))
    need(code == 200 and confirmed['status'] == 'confirmed',
         'Gateway case initial confirmation failed')
    b05.wait('gateway case initial task active', lambda: [row for row in
        core.observer_rows(session) if row['type'] == 'uxas.messages.task.TaskActive' and
        row.get('taskId') in ('3000', '3001')] or None, 120)
    control = b05.http(8001, 'GET', '/api/control/v1/state')[1]
    code, _ = b05.http(8001, 'POST', '/api/control/v1/operations',
        dict(runId=identity['runId'], segmentId=identity['segmentId'],
             expectedSequence=control['controlSequence'],
             idempotencyKey='g6-b07-gateway-pause', action='pause', multiple=None))
    need(code in (200, 202), 'Gateway case pause failed')
    b05.wait('gateway case paused', lambda: settled(session), 25)
    old_commands = [row['rawSHA256'] for row in core.observer_rows(session)
                    if row['type'] == 'afrl.cmasi.MissionCommand']
    if foreign is not None:
        other = core.release.load(foreign)
        need(other['identity']['runId'] != identity['runId'],
             'Foreign isolation input belongs to this run')
        foreign_key = 'g6-b07-foreign-run-plan'
        code, _ = b05.http(8006, 'POST', '/api/tasks/v3/plans',
            dict(other['identity'], idempotencyKey=foreign_key,
                 change=dict(action='add', draftId=drafts['area']['draftId'])))
        need(code == 409 and not (session.parent / 'task-replanning/lifecycle' /
             (foreign_key + '.json')).exists(),
             'Another run identity reserved a planning operation')
    first_body = dict(identity, idempotencyKey='g6-b07-gateway-old-plan',
                      change=dict(action='add', draftId=drafts['area']['draftId']))
    code, first = b05.http(8006, 'POST', '/api/tasks/v3/plans', first_body)
    need(code == 200 and first['status'] == 'previewed',
         'Gateway case preview failed: ' + str(first))
    marker = session.parent / 'task-replanning/request-gateway-restart'
    marker.touch()
    receipt = session.parent / 'task-replanning/gateway-restart.json'
    b05.wait('owned gateway restart', lambda: receipt if receipt.is_file() else None, 90)
    restart = core.release.load(receipt)
    code, recovered = b05.http(8006, 'GET', '/api/tasks/v4/state')
    need(code == 200 and not recovered['health']['readOnly'] and
         recovered['identity']['streamId'] == restart['newStreamId'] and
         restart['outageReadOnly'] and
         restart['oldStreamId'] != restart['newStreamId'],
         'Gateway restart identity or read-only receipt differs')
    previous = next(row for row in recovered['lifecycle']
                    if row['key'] == first_body['idempotencyKey'])
    need(previous['status'] == 'stale', 'Old preview survived gateway stream change')
    code, _ = b05.http(8006, 'GET', '/api/tasks/v3/plans/' + first['planId'])
    need(code == 409, 'Old preview was restored after gateway restart')
    code, _ = b05.http(8006, 'POST',
        '/api/tasks/v3/plans/' + first['planId'] + '/confirm',
        dict(identity, reviewSHA256=first['review']['reviewSHA256'],
             idempotencyKey='g6-b07-gateway-stale-confirm', acknowledged=True))
    need(code == 409, 'Old preview was confirmed after gateway restart')
    new_body = dict(recovered['identity'], idempotencyKey='g6-b07-gateway-new-plan',
                    change=first_body['change'])
    code, second = b05.http(8006, 'POST', '/api/tasks/v3/plans', new_body)
    need(code == 200 and second['status'] == 'previewed',
         'Fresh stream could not replan: ' + str(second))
    code, canceled = b05.http(8006, 'POST',
        '/api/tasks/v4/operations/' + new_body['idempotencyKey'] + '/cancel',
        dict(recovered['identity'], idempotencyKey='g6-b07-gateway-new-cancel'))
    need(code == 200 and canceled['status'] == 'canceled',
         'Fresh preview cancellation failed')
    current_commands = [row['rawSHA256'] for row in core.observer_rows(session)
                        if row['type'] == 'afrl.cmasi.MissionCommand']
    need(current_commands == old_commands and
         b05.http(8001, 'GET', '/api/control/v1/state')[1]['simulation']['state'] == 2,
         'Gateway recovery changed the paused active mission')
    return dict(task='G6-B07', status='passed', mode='Headless',
                oldStreamId=restart['oldStreamId'],
                newStreamId=restart['newStreamId'], outageReadOnly=True,
                oldPreviewStale=True, oldConfirmationRejected=True,
                foreignRunRejected=foreign is not None,
                newPreviewId=second['planId'], activeCommandsUnchanged=len(old_commands))


def settled(session):
    try:
        return live.settled_snapshot(session)
    except (ValueError, RuntimeError):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--foreign-operation', type=Path)
    args = parser.parse_args()
    run = ROOT / 'out/runs' / args.run_id
    need(not run.exists(), 'Gateway fault run ID exists')
    run.mkdir(parents=True)
    try:
        result = execute(args.session.resolve(), args.foreign_operation.resolve()
                         if args.foreign_operation else None)
        code = 0
    except Exception as error:
        result = dict(task='G6-B07', status='failed', error=str(error),
                      traceback=traceback.format_exc())
        print(result['traceback'], file=sys.stderr)
        code = 1
    core.release.save(run / 'result.json', result)
    return code


if __name__ == '__main__':
    sys.exit(main())
