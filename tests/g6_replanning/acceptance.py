"""Qualify the B06 candidate from two-mode live execution and independent audits."""
import argparse
from pathlib import Path
import socket
import sys
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/g6_release'))
import manage as release


def need(value, message):
    if not value:
        raise RuntimeError(message)


def port_free(number):
    with socket.socket() as client:
        client.settimeout(.3)
        return client.connect_ex(('127.0.0.1', number)) != 0


def case(session_id, flow_id, audit_id, mode, build_id, build_sha):
    session = ROOT / 'out/runs' / session_id
    flow = ROOT / 'out/runs' / flow_id
    audit = ROOT / 'out/runs' / audit_id
    runtime_file = session / 'runtime-result.json'
    flow_file = flow / 'result.json'
    audit_file = audit / 'result.json'
    runtime = release.load(runtime_file)
    result = release.load(flow_file)
    checked = release.load(audit_file)
    need(runtime['status'] == 'passed' and runtime['task'] == 'G6-B06' and
         runtime['scope'] == 'controlled-replanning-candidate' and
         runtime['normalExit'] and
         runtime['b06ViewerBuildRunId'] == build_id and
         runtime['b06ViewerBuildSHA256'].lower() == build_sha.lower() and
         len(runtime['cases']) == 1 and runtime['cases'][0]['mode'] ==
         ('Gui' if mode == 'add' else 'Headless') and
         runtime['cases'][0]['status'] == 'passed' and
         runtime['cases'][0]['transitions'][-1]['phase'] == 'shutdown-finished' and
         runtime['cases'][0]['transitions'][-1]['normalExit'],
         'B06 runtime identity, exit or source differs: ' + session_id)
    need(result['status'] == 'passed' and result['mode'] == mode and
         result['replacementReview']['identity']['runId'] == session_id and
         result['switch']['status'] == 'completed',
         'B06 flow or browser receipt differs: ' + flow_id)
    need(checked['status'] == 'passed' and checked['mode'] == mode and
         set(checked['tasks']) == {'3100', '3101', '3102'} and
         checked['oldTaskCompletionsAfterSwitch'] == 0 and
         checked['oldAssociatedActionsAfterSwitch'] == 0 and
         checked['newAssociatedActionsReceived'] > 0 and
         checked['oldCoverage']['replayMatches'] and
         checked['newCoverage']['replayMatches'] and
         all(row['plannedWaypoints'] == row['observedWaypointIds']
             for row in checked['commands']),
         'Independent B06 command, task or statistics audit differs: ' + audit_id)
    if mode == 'add':
        need(result['browser'] == 'Microsoft Edge' and
             all((flow / name).is_file() and (flow / name).stat().st_size > 10000
                 for name in ('review.png', 'completed.png')),
             'Real Edge screenshots missing')
    return dict(mode=mode, sessionRunId=session_id, flowRunId=flow_id,
                auditRunId=audit_id,
                runtimeSHA256=release.digest(runtime_file),
                flowSHA256=release.digest(flow_file),
                auditSHA256=release.digest(audit_file),
                assignments=[(item['taskId'], item['vehicleId'])
                             for item in result['replacementReview']['plan']['assignments']],
                commands=[(item['vehicleId'], item['plannedWaypoints'])
                          for item in checked['commands']])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--build-run-id', required=True)
    parser.add_argument('--contract-run-id', required=True)
    parser.add_argument('--headless-session', required=True)
    parser.add_argument('--headless-flow', required=True)
    parser.add_argument('--headless-audit', required=True)
    parser.add_argument('--gui-session', required=True)
    parser.add_argument('--gui-browser', required=True)
    parser.add_argument('--gui-audit', required=True)
    args = parser.parse_args()
    run = ROOT / 'out/runs' / args.run_id
    need(not run.exists(), 'B06 acceptance ID exists')
    run.mkdir(parents=True)
    record = dict(task='G6-B06', runId=args.run_id, status='running',
                  replanningQualified=False)
    try:
        build_file = ROOT / 'out/runs' / args.build_run_id / 'result.json'
        build = release.load(build_file)
        need(build['status'] == 'passed' and build['task'] == 'G6-B06' and
             build['viewerQualified'] and
             all(release.digest(ROOT / row['path']).lower() == row['sha256'].lower()
                 for row in build['inputs']), 'B06 build or current source differs')
        build_sha = release.digest(build_file)
        contract_file = ROOT / 'out/runs' / args.contract_run_id / 'result.json'
        contract = release.load(contract_file)
        need(contract['status'] == 'passed' and
             contract['staleAndInvalidRejected'] == 2,
             'B06 contract rejection evidence missing')
        cases = [case(args.headless_session, args.headless_flow,
                      args.headless_audit, 'revise', args.build_run_id, build_sha),
                 case(args.gui_session, args.gui_browser,
                      args.gui_audit, 'add', args.build_run_id, build_sha)]
        ports = (5555, 5556, 8001, 8002, 8003, 8004, 8005, 8006, 8080,
                 9227, 9999, 9400, 9500, 9600, 19400, 19500, 19600)
        need(all(port_free(port) for port in ports), 'A B06 session port is still occupied')
        record.update(status='passed', replanningQualified=True,
                      buildRunId=args.build_run_id, buildSHA256=build_sha,
                      contractRunId=args.contract_run_id,
                      contractSHA256=release.digest(contract_file),
                      cases=cases, portsReleased=list(ports),
                      scope='one paused switch per segment; old coverage archived, new coverage restarted')
        return 0
    except Exception as error:
        record.update(status='failed', error=str(error), traceback=traceback.format_exc())
        print(record['traceback'], file=sys.stderr)
        return 1
    finally:
        release.save(run / 'acceptance.json', record)


if __name__ == '__main__':
    sys.exit(main())
