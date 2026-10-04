"""Check replacement input boundaries against qualified saved B05 task evidence."""
import argparse
import copy
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
spec = spec_from_file_location('b06_server', ROOT / 'apps/g6_replanning/server.py')
module = module_from_spec(spec)
spec.loader.exec_module(module)


def check():
    session = ROOT / 'out/runs/g6-b05-session-headless-20260930-04/segment-001/control-session.json'
    folder = session.parent / 'task-assignment'
    confirmation = next(folder.joinpath('confirmations').glob('*.json'))
    initial = module.core.release.load(confirmation)
    old = module.core.release.load(folder / 'plans' / (initial['planId'] + '.json'))
    assert initial['status'] == 'completed'
    active = dict(identity=old['review']['identity'], taskEvents=[dict(
        type='uxas.messages.task.TaskActive', taskId='3000', rawSHA256='fixture', timeMs='30000')])
    with tempfile.TemporaryDirectory(prefix='g6-b06-contract-') as directory:
        store = object.__new__(module.ReplanningStore)
        store.session_file = session
        store.contract = module.core.release.load(ROOT / 'config/g6-task-contract-v1.json')
        store.assignment_contract = module.core.release.load(
            ROOT / 'config/g6-assignment-contract-v1.json')
        store.switches = Path(directory)
        store.initial = lambda: (dict(initial, status='executing'), old)
        actual_snapshot = module.live.settled_snapshot
        module.live.settled_snapshot = lambda path: active
        try:
            line = next(task for task in old['spec']['tasks'] if task['kind'] == 'line')
            revised = copy.deepcopy(line['draft']['geometry'])
            revised['coordinates'][1][0] += .0001
            body = dict(**active['identity'], idempotencyKey='b06-contract-revise-001',
                        change=dict(action='revise', taskId='3000', geometry=revised))
            result = store.validate(body)
            assert {task['taskId'] for task in result['tasks']} == {'3100', '3101', '3102'}
            changed = next(task for task in result['tasks'] if task['taskId'] == '3100')
            assert changed['revision'] == str(int(line['revision']) + 1)
            assert changed['draft']['geometry'] == revised
            rejected = 0
            wrong = copy.deepcopy(body)
            wrong['streamId'] = 'stale-stream'
            try:
                store.validate(wrong)
            except ValueError:
                rejected += 1
            wrong = copy.deepcopy(body)
            wrong['change']['geometry']['coordinates'][0] = [-123, 45.3]
            try:
                store.validate(wrong)
            except ValueError:
                rejected += 1
            assert rejected == 2
            shortened = copy.deepcopy(old)
            shortened['spec']['tasks'] = [task for task in old['spec']['tasks']
                                          if task['kind'] != 'area']
            shortened['spec']['taskOrder'] = ['3000', '3001']
            shortened['review']['tasks'] = [task for task in old['review']['tasks']
                                            if task['kind'] != 'area']
            store.initial = lambda: (dict(initial, status='executing'), shortened)
            area = next(task for task in old['spec']['tasks'] if task['kind'] == 'area')
            add = dict(**active['identity'], idempotencyKey='b06-contract-add-001',
                       change=dict(action='add', draftId=area['draftId']))
            added = store.validate(add)
            assert added['taskOrder'] == ['3100', '3101', '3102']
            assert added['oldTaskIds'] == ['3000', '3001']
            return dict(status='passed', revisedTaskId='3100', addedTaskId='3102',
                        staleAndInvalidRejected=rejected)
        finally:
            module.live.settled_snapshot = actual_snapshot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = check()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    sys.exit(main())
