"""Independently replay B08 coverage and bind it to browser completion evidence."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('b06_audit', ROOT / 'tests/g6_replanning/audit.py')
b06 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b06)


def audit(session, browser):
    page = b06.core.release.load(browser)
    b06.need(page['task'] == 'G6-B08' and page['status'] == 'passed' and
             len(page['receipt']['tasks']) == 3 and len(page['audit']['tasks']) == 3,
             'Browser lifecycle receipt incomplete')
    live = b06.core.release.load(session.parents[1] / 'coverage/live.json')
    replay = b06.replay(session, live['cursor'])
    for key in ('runId', 'cursor', 'simulationTimeMs', 'sampledStates',
                'gridResolutionMeters', 'tasks'):
        b06.need(live[key] == replay[key], 'Coverage event replay differs: ' + key)
    tasks = {row['taskId']: row for row in live['tasks']}
    b06.need(set(tasks) == {'3000', '3001', '3002'} and
             {key: tasks[key]['kind'] for key in tasks} == {
                 '3000': 'LineSearchTask', '3001': 'PointSearchTask',
                 '3002': 'AreaSearchTask'}, 'Coverage tasks differ from browser drafts')
    b06.need(all(row['totalCells'] > 0 and 0 <= row['seenCells'] <= row['totalCells']
                 for row in tasks.values()), 'Coverage cells invalid')
    b06.need(all(row['seenCells'] > 0 for row in tasks.values()) and
             int(tasks['3001']['observationMilliseconds']) > 0,
             'Completed tasks lack coverage/observation evidence')
    control_rows = [b06.core.release.load(path) for path in
                    (session.parent / 'control-operations').glob('*.json')]
    actions = [row['action'] for row in control_rows if row['status'] == 'confirmed']
    b06.need(all(action in actions for action in ('start', 'pause', 'resume', 'rate')),
             'Page control regression lacks confirmed backend operations')
    review = page['review']
    b06.need(review['reviewSHA256'] and review['planId'] and
             len(page['audit']['commands']) >= 1, 'Review/mission audit incomplete')
    return dict(task='G6-B08', status='passed',
                sessionRunId=session.parent.parent.name,
                browserRunId=browser.parent.name, mode=page['mode'],
                reviewedPlanId=review['planId'], reviewSHA256=review['reviewSHA256'],
                commands=page['audit']['commands'],
                taskLifecycle=page['audit']['tasks'],
                controlActions=actions,
                coverage=dict(cursor=live['cursor'], sampledStates=live['sampledStates'],
                              gridResolutionMeters=live['gridResolutionMeters'],
                              tasks=[{key: row[key] for key in
                                      ('taskId', 'kind', 'seenCells', 'totalCells',
                                       'observationMilliseconds')}
                                     for row in live['tasks']]), replayMatches=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--browser', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = audit(args.session.resolve(), args.browser.resolve())
    except Exception as error:
        result = dict(task='G6-B08', status='failed', error=str(error),
                      traceback=traceback.format_exc())
        print(result['traceback'], file=sys.stderr)
    args.output.mkdir(parents=True, exist_ok=False)
    b06.core.release.save(args.output / 'result.json', result)
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
