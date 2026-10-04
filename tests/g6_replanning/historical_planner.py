"""Diagnostic three-task replanning from a prior B05 moving-aircraft snapshot."""
import argparse
import copy
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
plan_spec = spec_from_file_location('b06_plan', ROOT / 'scripts/g6_replanning/plan.py')
planner = module_from_spec(plan_spec)
plan_spec.loader.exec_module(planner)
probe_spec = spec_from_file_location('b06_probe', ROOT / 'scripts/g6_replanning/isolated_probe.py')
probe = module_from_spec(probe_spec)
probe_spec.loader.exec_module(probe)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    assert args.run_id.startswith('g6-b06-historical-')
    run = ROOT / 'out/runs' / args.run_id
    assert not run.exists()
    run.mkdir(parents=True)
    session = ROOT / 'out/runs/g6-b05-session-headless-20260930-04/segment-001/control-session.json'
    folder = session.parent / 'task-assignment'
    initial = planner.core.release.load(next(folder.joinpath('confirmations').glob('*.json')))
    old = planner.core.release.load(folder / 'plans' / (initial['planId'] + '.json'))
    states = probe.read_states(session.parent / 'observer.jsonl', 30000)
    active = dict(identity=old['review']['identity'], controlSequence='2',
                  simulationTimeMs='30000', uxasProcess={'historical': True},
                  states={vehicle: {key: row[key] for key in
                      ('timeMs', 'rawSHA256', 'xmlBase64', 'latitude', 'longitude')}
                      for vehicle, row in states.items()},
                  commandHashes=[], taskEvents=[], coverageSHA256='historical',
                  coverageCursor=['0', '0'], coverageSummary=[])
    by_kind = {'line': '3100', 'point': '3101', 'area': '3102'}
    tasks = []
    for item in old['spec']['tasks']:
        draft = copy.deepcopy(item['draft'])
        if draft['kind'] == 'line':
            draft['geometry']['coordinates'][1][0] += .0001
            draft['revision'] = str(int(draft['revision']) + 1)
        tasks.append(dict(taskId=by_kind[draft['kind']], oldTaskId=item['taskId'],
                          kind=draft['kind'], draft=draft,
                          candidateEntityIds=item['candidateEntityIds'],
                          revision=draft['revision']))
    spec = dict(identity=active['identity'], activeSnapshot=active,
                tasks=tasks, taskOrder=[by_kind[next(item['kind'] for item in tasks
                    if item['oldTaskId'] == task_id)] for task_id in old['spec']['taskOrder']],
                vehicleIds=old['spec']['vehicleIds'],
                relationship=old['spec']['relationship'],
                sequenceVehicleId=old['spec']['sequenceVehicleId'])
    planner.core.release.save(run / 'input.json', spec)
    original = planner.live.snapshot
    planner.live.snapshot = lambda _: active
    try:
        receipt = planner.execute(session, spec, run, diagnostic=True)
    finally:
        planner.live.snapshot = original
    print(json.dumps({key: receipt.get(key) for key in
        ('status', 'error', 'isolatedPlannerQualified', 'diagnosticOnly')}, ensure_ascii=False))
    return 0 if (receipt['status'] == 'passed' and receipt['diagnosticOnly'] and
                 not receipt['isolatedPlannerQualified']) else 1


if __name__ == '__main__':
    sys.exit(main())
