"""Exercise restart reconciliation and the per-segment operation bound."""
import argparse
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import threading
import traceback

ROOT = Path(__file__).resolve().parents[2]
spec = spec_from_file_location('g6_b07_server', ROOT / 'apps/g6_lifecycle/server.py')
server = module_from_spec(spec)
spec.loader.exec_module(server)


def need(condition, message):
    if not condition:
        raise RuntimeError(message)


def store(ledger, switches):
    item = object.__new__(server.LifecycleStore)
    item.ledger = ledger
    item.switches = switches
    item.lifecycle_lock = threading.RLock()
    item.planner_running = False
    item.health = lambda: dict(readOnly=False, identity={})
    return item


def execute(run):
    ledger = run / 'recovery-ledger'
    switches = run / 'recovery-switches'
    ledger.mkdir()
    switches.mkdir()
    server.save(ledger / 'pending-1.json', dict(status='pending'))
    server.save(ledger / 'confirming-1.json', dict(status='confirming'))
    server.save(switches / 'cutover.json', dict(status='pending', phase='new-task-attempted'))
    item = store(ledger, switches)
    item.recover()
    need(item.operation('pending-1')['status'] == 'interrupted' and
         item.operation('confirming-1')['status'] == 'uncertain' and
         server.base.core.release.load(switches / 'cutover.json')['status'] == 'uncertain',
         'Restart reconciliation promoted or resent an unknown result')
    item.recover()
    need(item.operation('pending-1')['status'] == 'interrupted' and
         item.operation('confirming-1')['status'] == 'uncertain',
         'Restart reconciliation changed a terminal record')
    bounded = run / 'bounded-ledger'
    empty_switches = run / 'bounded-switches'
    bounded.mkdir()
    empty_switches.mkdir()
    for number in range(server.MAX_OPERATIONS):
        server.save(bounded / ('case-key-' + str(number) + '.json'),
                    dict(status='canceled', key='case-key-' + str(number)))
    limit = store(bounded, empty_switches)
    try:
        limit.plan(dict(idempotencyKey='one-more-key'))
    except ValueError as error:
        need('limit reached' in str(error), 'Operation bound rejected for another reason')
    else:
        raise RuntimeError('Ninth operation was accepted')
    need(len(limit.records()) == server.MAX_OPERATIONS and
         not (bounded / 'one-more-key.json').exists(),
         'Operation bound changed durable records')
    return dict(task='G6-B07', status='passed',
                pendingAfterRestart='interrupted',
                confirmationAfterRestart='uncertain',
                cutoverAfterRestart='uncertain',
                duplicateRecoveryStable=True,
                maxOperations=server.MAX_OPERATIONS,
                ninthOperationRejected=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    run = ROOT / 'out/runs' / args.run_id
    need(not run.exists(), 'Ledger run ID exists')
    run.mkdir(parents=True)
    try:
        result = execute(run)
        code = 0
    except Exception as error:
        result = dict(task='G6-B07', status='failed', error=str(error),
                      traceback=traceback.format_exc())
        print(result['traceback'], file=sys.stderr)
        code = 1
    server.base.core.release.save(run / 'result.json', result)
    return code


if __name__ == '__main__':
    sys.exit(main())
