"""Exercise cancellation, planner deadline, key replay and segment reset."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests/g6_assignment'))
import flow as b05
sys.path.insert(0, str(ROOT / 'scripts/g6_replanning'))
import live

core = b05.core


def need(value, message):
    if not value:
        raise RuntimeError(message)


def wait(label, predicate, seconds=80):
    return b05.wait(label, predicate, seconds)


def execute(session):
    code, state = b05.http(8005, 'GET', '/api/tasks/v2/state')
    need(code == 200 and state['identity']['runId'] == session.parent.parent.name,
         'B07 session identity differs')
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
            dict(identity, idempotencyKey='g6-b07-fault-draft-' + kind,
                 kind=kind, geometry=geometry[kind],
                 candidateEntityIds=sample['candidateEntityIds'],
                 altitudeDatum='EPSG:5773'))
        need(code in (200, 201) and row['status'] == 'confirmed',
             'B07 draft creation failed')
        drafts[kind] = row['draft']['draft']
    selections = [dict(draftId=drafts[kind]['draftId'],
                       revision=drafts[kind]['revision'], candidateEntityIds=['400'])
                  for kind in ('line', 'point')]
    code, planned = b05.http(8005, 'POST', '/api/tasks/v2/plans',
        dict(identity, idempotencyKey='g6-b07-fault-initial-plan', tasks=selections,
             taskOrder=['3000', '3001'], relationship='sequence'))
    need(code == 200 and planned['status'] == 'previewed',
         'B07 initial plan failed: ' + str(planned))
    review = planned['review']
    code, initial = b05.http(8005, 'POST',
        '/api/tasks/v2/plans/' + review['planId'] + '/confirm',
        dict(identity, reviewSHA256=review['reviewSHA256'],
             idempotencyKey='g6-b07-fault-initial-confirm', acknowledged=True))
    need(code == 200 and initial['status'] == 'confirmed',
         'B07 initial confirmation failed')
    wait('initial B07 task active', lambda: [row for row in core.observer_rows(session)
         if row['type'] == 'uxas.messages.task.TaskActive' and
         row.get('taskId') in ('3000', '3001')] or None, 120)
    control = b05.http(8001, 'GET', '/api/control/v1/state')[1]
    code, _ = b05.http(8001, 'POST', '/api/control/v1/operations',
        dict(runId=identity['runId'], segmentId=identity['segmentId'],
             expectedSequence=control['controlSequence'],
             idempotencyKey='g6-b07-fault-pause', action='pause', multiple=None))
    need(code in (200, 202), 'B07 pause failed')
    paused = wait('B07 paused snapshot', lambda: try_snapshot(session), 25)
    old_commands = [row['rawSHA256'] for row in core.observer_rows(session)
                    if row['type'] == 'afrl.cmasi.MissionCommand']
    for label, task_id in (('int64', '9223372036854775807'),
                           ('unsafe-json-number', 9007199254740993)):
        invalid_key = 'g6-b07-invalid-task-' + label
        code, _ = b05.http(8006, 'POST', '/api/tasks/v3/plans',
            dict(identity, idempotencyKey=invalid_key,
                 change=dict(action='revise', taskId=task_id,
                             geometry=dict(type='LineString',
                                 coordinates=[[-120.9923, 45.3171],
                                              [-120.965, 45.3171]]))))
        need(code == 409 and not (session.parent / 'task-replanning/lifecycle' /
             (invalid_key + '.json')).exists(),
             'Oversized or numeric task ID reserved a planning operation')
    body = dict(identity, idempotencyKey='g6-b07-fault-cancel-plan',
                change=dict(action='add', draftId=drafts['area']['draftId']))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(b05.http, 8006, 'POST', '/api/tasks/v3/plans', body)
        pending = wait('durable pending plan', lambda: pending_or_none(body['idempotencyKey']), 15)
        need(pending['status'] == 'pending', 'Plan did not persist pending before execution')
        code, canceled = b05.http(8006, 'POST',
            '/api/tasks/v4/operations/' + body['idempotencyKey'] + '/cancel',
            dict(identity, idempotencyKey='g6-b07-fault-cancel-key'))
        need(code == 200 and canceled['status'] == 'canceled',
             'In-flight planning cancellation failed')
        first_code, first_result = future.result(timeout=120)
    need(first_code == 409 and first_result['status'] == 'canceled' and
         first_result.get('lateResult') == 'previewed',
         'Late canceled planner result was promoted')
    code, replayed = b05.http(8006, 'POST', '/api/tasks/v3/plans', body)
    need(code == 409 and replayed == first_result,
         'Canceled key replay created another plan')
    different = dict(body, change=dict(action='revise', taskId='3000',
        geometry=dict(type='LineString', coordinates=[[-120.9923, 45.3171],
                                                       [-120.965, 45.3171]])))
    code, _ = b05.http(8006, 'POST', '/api/tasks/v3/plans', different)
    need(code == 409, 'Reused key accepted different input')
    internal = [core.release.load(path) for path in
        (session.parent / 'task-replanning/operations').glob('b07-*.json')]
    canceled_plans = [row['planId'] for row in internal if row['status'] == 'previewed']
    need(len(canceled_plans) == 1, 'Canceled isolated plan evidence missing')
    code, _ = b05.http(8006, 'GET', '/api/tasks/v3/plans/' + canceled_plans[0])
    need(code == 409, 'Canceled plan was restored for confirmation')
    timed_body = dict(body, idempotencyKey='g6-b07-fault-deadline-plan')
    code, timed = b05.http(8006, 'POST', '/api/tasks/v3/plans', timed_body)
    need(code == 409 and timed['status'] == 'timed-out' and
         timed['lateResult'] == 'previewed',
         'Planner result after deadline was promoted')
    code, same = b05.http(8006, 'POST', '/api/tasks/v3/plans', timed_body)
    need(code == 409 and same == timed, 'Timed-out key replay changed outcome')
    current_commands = [row['rawSHA256'] for row in core.observer_rows(session)
                        if row['type'] == 'afrl.cmasi.MissionCommand']
    need(current_commands == old_commands and
         b05.http(8001, 'GET', '/api/control/v1/state')[1]['simulation']['state'] == 2,
         'Cancel or deadline changed activity while paused')
    control = b05.http(8001, 'GET', '/api/control/v1/state')[1]
    code, reset = b05.http(8001, 'POST', '/api/control/v1/operations',
        dict(runId=identity['runId'], segmentId=identity['segmentId'],
             expectedSequence=control['controlSequence'],
             idempotencyKey='g6-b07-fault-reset', action='reset', multiple=None))
    need(code in (200, 202), 'B07 reset failed: ' + str(reset))
    second = session.parents[1] / 'segment-002/control-session.json'
    wait('new segment after reset', lambda: new_segment_ready(second, identity), 90)
    new_state = b05.http(8006, 'GET', '/api/tasks/v4/state')[1]
    need(not new_state['lifecycle'] and
         new_state['identity']['backendRunId'] != identity['backendRunId'] and
         new_state['identity']['streamId'] != identity['streamId'],
         'Reset reused lifecycle or backend identity')
    code, history = b05.http(8006, 'GET',
        '/api/tasks/v4/history/' + session.parent.name + '/' + body['idempotencyKey'])
    need(code == 200 and history['stale'] and history['status'] == 'canceled',
         'Old segment operation was not queryable as history')
    code, _ = b05.http(8006, 'POST', '/api/tasks/v3/plans', body)
    need(code == 409, 'Old segment planning body entered the new segment')
    return dict(task='G6-B07', status='passed', mode='Headless',
                oldSegment=identity['segmentId'], newSegment=new_state['identity']['segmentId'],
                canceledKey=body['idempotencyKey'], timedOutKey=timed_body['idempotencyKey'],
                canceledLateResult=first_result['lateResult'],
                timedOutLateResult=timed['lateResult'],
                oldCommandsUnaffected=len(old_commands),
                oldHistoryStale=True, newLifecycleEmpty=True,
                oversizedTaskIdsRejected=True,
                pausedAtMs=paused['simulationTimeMs'])


def pending_or_none(key):
    code, value = b05.http(8006, 'GET', '/api/tasks/v4/operations/' + key)
    return value if code == 200 and value['status'] == 'pending' else None


def try_snapshot(session):
    try:
        return live.settled_snapshot(session)
    except (ValueError, RuntimeError):
        return None


def new_segment_ready(second, old_identity):
    if not second.is_file():
        return None
    try:
        code, state = b05.http(8006, 'GET', '/api/tasks/v4/state')
        return second if code == 200 and state['identity']['segmentId'] != \
            old_identity['segmentId'] else None
    except (OSError, ValueError):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    run = ROOT / 'out/runs' / args.run_id
    need(not run.exists(), 'B07 fault run ID exists')
    run.mkdir(parents=True)
    try:
        result = execute(args.session.resolve())
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
