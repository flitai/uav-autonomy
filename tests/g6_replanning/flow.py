"""Exercise B06 paused live-state revision or task addition on a real backend."""
import argparse
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


def execute(session, mode, run):
    code, state = b05.http(8005, 'GET', '/api/tasks/v2/state')
    need(code == 200 and state['identity']['runId'] == session.parent.parent.name,
         'Initial B05 state identity differs')
    identity = state['identity']
    scene = ROOT / 'out/runs/g6-b01-baseline-20260924-2223/samples'
    geometry = {
        'line': dict(type='LineString', coordinates=[[-120.9923, 45.3171],
                                                     [-120.97, 45.3171]]),
        'point': dict(type='Point', coordinates=[-120.7645, 45.323] if mode == 'revise'
                      else [-120.977, 45.323]),
        'area': dict(type='Rectangle', center=[-120.979, 45.323] if mode == 'revise'
                     else [-120.974, 45.325], widthMeters=500, heightMeters=300,
                     rotationDegrees=0)}
    drafts = {}
    for kind in ('line', 'point', 'area'):
        sample = core.release.load(scene / (kind + '-draft.json'))
        body = dict(identity, idempotencyKey='g6-b06-create-' + kind + '-' + mode,
                    kind=kind, geometry=geometry[kind],
                    candidateEntityIds=sample['candidateEntityIds'], altitudeDatum='EPSG:5773')
        code, created = b05.http(8003, 'POST', '/api/tasks/v1/drafts', body)
        need(code in (200, 201) and created['status'] == 'confirmed',
             'Initial draft save failed: ' + str(created))
        drafts[kind] = created['draft']['draft']
    kinds = ('line', 'point', 'area') if mode == 'revise' else ('line', 'point')
    selections = []
    for kind in kinds:
        eligible = ['400'] if mode == 'add' or kind == 'area' else ['400', '500', '600']
        draft = drafts[kind]
        selections.append(dict(draftId=draft['draftId'], revision=draft['revision'],
                               candidateEntityIds=eligible))
    relationship = 'parallel' if mode == 'revise' else 'sequence'
    code, planned = b05.http(8005, 'POST', '/api/tasks/v2/plans',
        dict(identity, idempotencyKey='g6-b06-initial-plan-' + mode,
             tasks=selections, taskOrder=[drafts[kind]['taskId'] for kind in kinds],
             relationship=relationship))
    need(code == 200 and planned['status'] == 'previewed',
         'Initial B05 planning failed: ' + str(planned))
    initial_review = planned['review']
    need(initial_review['confirmationAllowed'], 'Initial plan exceeds scene duration')
    initial_key = 'g6-b06-initial-confirm-' + mode
    code, confirmed = b05.http(8005, 'POST',
        '/api/tasks/v2/plans/' + initial_review['planId'] + '/confirm',
        dict(identity, reviewSHA256=initial_review['reviewSHA256'],
             idempotencyKey=initial_key, acknowledged=True))
    need(code == 200 and confirmed['status'] == 'confirmed',
         'Initial B05 confirmation failed: ' + str(confirmed))
    old_ids = {task['taskId'] for task in initial_review['tasks']}
    def active():
        rows = core.observer_rows(session)
        current = [row for row in rows if row['type'] == 'uxas.messages.task.TaskActive'
                   and row.get('taskId') in old_ids]
        completed = [row for row in rows if row['type'] == 'uxas.messages.task.TaskComplete'
                     and row.get('taskId') in old_ids]
        need(not completed, 'An old task completed before replanning pause')
        return current if current else None
    first_active = b05.wait('initial task execution', active, 120)
    control = b05.http(8001, 'GET', '/api/control/v1/state')[1]
    code, pause = b05.http(8001, 'POST', '/api/control/v1/operations', dict(
        runId=identity['runId'], segmentId=identity['segmentId'],
        expectedSequence=control['controlSequence'],
        idempotencyKey='g6-b06-pause-' + mode, action='pause', multiple=None))
    need(code in (200, 202), 'Pause request rejected: ' + str(pause))
    b05.wait('backend paused', lambda: (lambda row: row if row['simulation'] and
        row['simulation']['state'] == 2 else None)(b05.http(8001, 'GET',
        '/api/control/v1/state')[1]), 20)
    paused = b05.wait('paused state and coverage synchronized',
                      lambda: try_snapshot(session), 20)
    code, b06_state = b05.http(8006, 'GET', '/api/tasks/v3/state')
    need(code == 200 and b06_state['status'] == 'paused',
         'B06 service did not expose paused execution')
    change = dict(action='revise', taskId='3000', geometry=dict(type='LineString',
        coordinates=[[-120.9923, 45.3171], [-120.965, 45.3171]])) if mode == 'revise' else \
        dict(action='add', draftId=drafts['area']['draftId'])
    bad = dict(identity, idempotencyKey='g6-b06-bad-stream-' + mode, change=change)
    bad['streamId'] = 'stale-stream'
    code, _ = b05.http(8006, 'POST', '/api/tasks/v3/plans', bad)
    need(code == 409, 'Stale stream was accepted')
    code, previewed = b05.http(8006, 'POST', '/api/tasks/v3/plans',
        dict(identity, idempotencyKey='g6-b06-plan-' + mode, change=change))
    need(code == 200 and previewed['status'] == 'previewed',
         'Live-state replanning failed: ' + str(previewed))
    review = previewed['review']
    need(review['confirmationAllowed'] and
         {row['taskId'] for row in review['tasks']} ==
         ({'3100', '3101', '3102'} if mode == 'revise' else {'3100', '3101', '3102'}),
         'Replacement review is incomplete')
    need(b05.http(8001, 'GET', '/api/control/v1/state')[1]['simulation']['state'] == 2,
         'Preview resumed active simulation')
    after_preview = live.settled_snapshot(session)
    live.unchanged(paused, after_preview)
    code, _ = b05.http(8006, 'POST',
        '/api/tasks/v3/plans/' + review['planId'] + '/confirm',
        dict(identity, idempotencyKey='g6-b06-wrong-review-' + mode,
             reviewSHA256='0' * 64, acknowledged=True))
    need(code == 409, 'Wrong review digest was accepted')
    switch_key = 'g6-b06-switch-' + mode
    code, switched = b05.http(8006, 'POST',
        '/api/tasks/v3/plans/' + review['planId'] + '/confirm',
        dict(identity, idempotencyKey=switch_key,
             reviewSHA256=review['reviewSHA256'], acknowledged=True))
    need(code == 200 and switched['status'] == 'switched',
         'Replacement cutover failed: ' + str(switched))
    archive = session.parent / 'task-replanning' / (switch_key + '-old-coverage.json')
    need(archive.is_file() and switched['oldCoverageSHA256'] == core.release.digest(archive),
         'Old version coverage archive is missing')
    old_coverage = core.release.load(archive)
    need({item['taskId'] for item in old_coverage['tasks']} == old_ids,
         'Archived coverage task set differs')
    code, repeated = b05.http(8006, 'POST',
        '/api/tasks/v3/plans/' + review['planId'] + '/confirm',
        dict(identity, idempotencyKey=switch_key,
             reviewSHA256=review['reviewSHA256'], acknowledged=True))
    need(code == 200 and repeated['key'] == switch_key,
         'Idempotent confirmation query failed')
    control = b05.http(8001, 'GET', '/api/control/v1/state')[1]
    code, rate = b05.http(8001, 'POST', '/api/control/v1/operations', dict(
        runId=identity['runId'], segmentId=identity['segmentId'],
        expectedSequence=control['controlSequence'],
        idempotencyKey='g6-b06-rate-' + mode, action='rate', multiple='10'))
    need(code in (200, 202), 'Post-cutover rate request failed: ' + str(rate))
    def completed():
        code, value = b05.http(8006, 'GET', '/api/tasks/v3/confirmations/' + switch_key)
        need(code == 200, 'Replacement operation query failed')
        return value if value['status'] == 'completed' else None
    final = b05.wait('replacement task completion', completed, 300)
    rows = core.observer_rows(session)
    before = switched['observerRowCountBeforeSwitch']
    late = [row for row in rows[before:] if row['type'] == 'uxas.messages.task.TaskComplete'
            and row.get('taskId') in old_ids]
    need(not late and not final['lateOldCompletionSHA256'],
         'Old task completed after replacement switch')
    new_ids = {item['taskId'] for item in review['tasks']}
    for task_id in new_ids:
        start = [row for row in rows if row['type'] == 'uxas.messages.task.TaskActive'
                 and row.get('taskId') == task_id]
        done = [row for row in rows if row['type'] == 'uxas.messages.task.TaskComplete'
                and row.get('taskId') == task_id]
        need(len(start) == len(done) == 1, 'Replacement task lifecycle differs: ' + task_id)
    current_coverage = b05.wait('replacement coverage version', lambda:
        coverage_with_tasks(session, new_ids), 20)
    return dict(task='G6-B06', status='passed', mode=mode,
                initialReview=initial_review, replacementReview=review,
                initialActiveSHA256=[row['rawSHA256'] for row in first_active],
                pausedAtMs=paused['simulationTimeMs'], switch=final,
                oldCoverageSHA256=core.release.digest(archive),
                newCoverageTaskIds=sorted(new_ids),
                newCoverageCursor=current_coverage['cursor'],
                oldTaskCompletionsAfterSwitch=0)


def try_snapshot(session):
    try:
        return live.settled_snapshot(session)
    except (ValueError, RuntimeError):
        return None


def coverage_with_tasks(session, expected):
    path = session.parents[1] / 'coverage/live.json'
    if not path.is_file():
        return None
    value = core.release.load(path)
    return value if (value.get('status') == 'live' and
                     {row['taskId'] for row in value['tasks']} == expected) else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--mode', choices=('revise', 'add'), required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    run = ROOT / 'out/runs' / args.run_id
    need(not run.exists(), 'B06 flow run ID exists')
    run.mkdir(parents=True)
    try:
        result = execute(args.session.resolve(), args.mode, run)
        core.release.save(run / 'result.json', result)
        return 0
    except Exception as error:
        result = dict(task='G6-B06', status='failed', mode=args.mode,
                      error=str(error), traceback=traceback.format_exc())
        core.release.save(run / 'result.json', result)
        print(result['traceback'], file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
