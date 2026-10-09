"""Confirm observer and replay origins cannot write task operations."""
import argparse
import json
from pathlib import Path
import sys
import traceback
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/g6_release'))
import manage as release


def need(condition, message):
    if not condition:
        raise RuntimeError(message)


def execute(session):
    with urlopen('http://127.0.0.1:8006/api/tasks/v4/state', timeout=3) as response:
        state = json.load(response)
    key = 'g6-b07-observer-write'
    body = dict(state['identity'], idempotencyKey=key,
                change=dict(action='add', draftId='0' * 32))
    rejected = {}
    for label, origin in (('observer', 'http://127.0.0.1:8000'),
                          ('replay', 'http://127.0.0.1:8090')):
        request = Request('http://127.0.0.1:8006/api/tasks/v3/plans',
                          data=json.dumps(body).encode(), method='POST',
                          headers={'Origin': origin,
                                   'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=3) as response:
                status = response.status
        except HTTPError as error:
            status = error.code
        need(status == 403, label + ' origin could write a task')
        rejected[label] = status
    need(not (session.parent / 'task-replanning/lifecycle' / (key + '.json')).exists(),
         'Observer origin created an operation record')
    return dict(task='G6-B07', status='passed', rejected=rejected,
                operationCreated=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    run = ROOT / 'out/runs' / args.run_id
    need(not run.exists(), 'Origin run ID exists')
    run.mkdir(parents=True)
    try:
        result = execute(args.session.resolve())
        code = 0
    except Exception as error:
        result = dict(task='G6-B07', status='failed', error=str(error),
                      traceback=traceback.format_exc())
        print(result['traceback'], file=sys.stderr)
        code = 1
    release.save(run / 'result.json', result)
    return code


if __name__ == '__main__':
    sys.exit(main())
