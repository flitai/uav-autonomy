"""Bind B07 source, live cases, fault receipts and released ports."""
import argparse
from pathlib import Path
import socket
import sys
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/g6_release'))
import manage as release


def need(condition, message):
    if not condition:
        raise RuntimeError(message)


def read(run_id, name='result.json'):
    path = ROOT / 'out/runs' / run_id / name
    return path, release.load(path)


def session(run_id, build_id, build_sha, modes):
    path, runtime = read(run_id, 'runtime-result.json')
    need(runtime['task'] == 'G6-B07' and runtime['status'] == 'passed' and
         runtime['normalExit'] and runtime['b07ViewerBuildRunId'] == build_id and
         runtime['b07ViewerBuildSHA256'].lower() == build_sha.lower() and
         len(runtime['cases']) == len(modes) and
         [case['mode'] for case in runtime['cases']] == modes and
         all(case['status'] == 'passed' and
             case['transitions'][-1]['phase'] == 'shutdown-finished' and
             case['transitions'][-1]['normalExit'] for case in runtime['cases']),
         'B07 session source, normal exit or segment count differs: ' + run_id)
    return dict(runId=run_id, sha256=release.digest(path), segments=len(modes))


def audit(flow_id, audit_id, mode, run_id):
    flow_file, flow = read(flow_id)
    audit_file, checked = read(audit_id)
    need(flow['status'] == 'passed' and flow['mode'] == mode and
         flow['replacementReview']['identity']['runId'] == run_id and
         flow['switch']['status'] == 'completed',
         'B07 live flow or browser differs: ' + flow_id)
    need(checked['status'] == 'passed' and checked['mode'] == mode and
         set(checked['tasks']) == {'3100', '3101', '3102'} and
         checked['oldTaskCompletionsAfterSwitch'] == 0 and
         checked['oldAssociatedActionsAfterSwitch'] == 0 and
         checked['newAssociatedActionsReceived'] > 0 and
         checked['oldCoverage']['replayMatches'] and
         checked['newCoverage']['replayMatches'] and
         all(row['plannedWaypoints'] == row['observedWaypointIds']
             for row in checked['commands']),
         'B07 independent command, lifecycle or coverage audit differs: ' + audit_id)
    if mode == 'refresh-recovery':
        need(flow['browser'] == 'Microsoft Edge' and
             any(step['action'] == 'refresh-and-restore' and
                 step['competingClientRejected'] for step in flow['steps']) and
             all((flow_file.parent / name).is_file() and
                 (flow_file.parent / name).stat().st_size > 10000
                 for name in ('review.png', 'completed.png')),
             'Real Edge refresh, conflict or screenshots missing')
    return dict(flowRunId=flow_id, flowSHA256=release.digest(flow_file),
                auditRunId=audit_id, auditSHA256=release.digest(audit_file),
                newTasks=sorted(checked['tasks']),
                commands=[(row['vehicleId'], row['plannedWaypoints'])
                          for row in checked['commands']])


def free(port):
    with socket.socket() as connection:
        connection.settimeout(.3)
        return connection.connect_ex(('127.0.0.1', port)) != 0


def main():
    parser = argparse.ArgumentParser()
    for name in ('run-id', 'build-run-id', 'headless-session', 'headless-flow',
                 'headless-audit', 'gui-session', 'gui-browser', 'gui-audit',
                 'fault-session', 'fault-run', 'gateway-session', 'gateway-run',
                 'backend-session', 'ledger-run', 'origin-run'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    run = ROOT / 'out/runs' / args.run_id
    need(not run.exists(), 'B07 acceptance run ID exists')
    run.mkdir(parents=True)
    result = dict(task='G6-B07', runId=args.run_id, status='running',
                  lifecycleQualified=False)
    try:
        build_file, build = read(args.build_run_id)
        need(build['task'] == 'G6-B07' and build['status'] == 'passed' and
             build['viewerQualified'] and
             all(release.digest(ROOT / row['path']).lower() == row['sha256'].lower()
                 for row in build['inputs']),
             'B07 build or current source differs')
        build_sha = release.digest(build_file)
        headless = session(args.headless_session, args.build_run_id,
                           build_sha, ['Headless'])
        gui = session(args.gui_session, args.build_run_id,
                      build_sha, ['Gui'])
        fault = session(args.fault_session, args.build_run_id,
                        build_sha, ['Headless', 'Headless'])
        gateway = session(args.gateway_session, args.build_run_id,
                          build_sha, ['Headless'])
        headless['execution'] = audit(args.headless_flow,
                                      args.headless_audit, 'revise',
                                      args.headless_session)
        gui['execution'] = audit(args.gui_browser, args.gui_audit,
                                 'refresh-recovery', args.gui_session)
        restart_file = (ROOT / 'out/runs' / args.headless_session /
                        'segment-001/task-replanning/restart-1.json')
        restart = release.load(restart_file)
        need(restart['recovered'] and restart['oldPid'] != restart['newPid'],
             'Owned task service restart was not recovered')
        _, fault_result = read(args.fault_run)
        need(fault_result['status'] == 'passed' and
             fault_result['oldHistoryStale'] and
             fault_result['newLifecycleEmpty'] and
             fault_result['oversizedTaskIdsRejected'] and
             fault_result['canceledLateResult'] == 'previewed' and
             fault_result['timedOutLateResult'] == 'previewed',
             'Cancel, deadline, reset or oversized ID evidence differs')
        _, gateway_result = read(args.gateway_run)
        need(gateway_result['status'] == 'passed' and
             gateway_result['outageReadOnly'] and
             gateway_result['oldPreviewStale'] and
             gateway_result['oldConfirmationRejected'] and
             gateway_result['foreignRunRejected'] and
             gateway_result['oldStreamId'] != gateway_result['newStreamId'],
             'Gateway restart did not invalidate the old preview')
        backend_file, backend_runtime = read(args.backend_session, 'runtime-result.json')
        backend_receipt = release.load(ROOT / 'out/runs' / args.backend_session /
            'segment-001/task-replanning/backend-exit.json')
        need(backend_runtime['task'] == 'G6-B07' and
             backend_runtime['b07ViewerBuildRunId'] == args.build_run_id and
             backend_runtime['status'] == 'failed' and
             'process-exited' in backend_runtime['error'] and
             backend_receipt['readOnly'] and
             backend_receipt['planningHttpStatus'] == 409,
             'Backend exit negative case was not rejected and recorded')
        _, ledger = read(args.ledger_run)
        need(ledger['status'] == 'passed' and
             ledger['pendingAfterRestart'] == 'interrupted' and
             ledger['confirmationAfterRestart'] == 'uncertain' and
             ledger['cutoverAfterRestart'] == 'uncertain' and
             ledger['ninthOperationRejected'],
             'Durable restart or bounded ledger evidence differs')
        _, origin = read(args.origin_run)
        need(origin['status'] == 'passed' and
             origin['rejected'] == {'observer': 403, 'replay': 403} and
             not origin['operationCreated'],
             'Observer or replay origin gained a task write operation')
        ports = (5555, 5556, 8000, 8001, 8002, 8003, 8004, 8005, 8006,
                 8080, 9227, 9999, 9400, 9500, 9600, 19400, 19500, 19600)
        need(all(free(port) for port in ports),
             'A B07 owned session port is still occupied')
        result.update(status='passed', lifecycleQualified=True,
                      buildRunId=args.build_run_id, buildSHA256=build_sha,
                      cases=dict(headless=headless, gui=gui, fault=fault,
                                 gateway=gateway, backendExitExpectedFailure={
                                     'sessionRunId': args.backend_session,
                                     'runtimeSHA256': release.digest(backend_file),
                                     'planningHttpStatus': 409},
                                 ledgerRunId=args.ledger_run,
                                 originRunId=args.origin_run),
                      faultRunId=args.fault_run,
                      gatewayRunId=args.gateway_run,
                      serviceRestart=restart,
                      portsReleased=list(ports),
                      scope='one paused replacement per segment; no automatic resend of uncertain cutover')
        return 0
    except Exception as error:
        result.update(status='failed', error=str(error), traceback=traceback.format_exc())
        print(result['traceback'], file=sys.stderr)
        return 1
    finally:
        release.save(run / 'acceptance.json', result)


if __name__ == '__main__':
    sys.exit(main())
