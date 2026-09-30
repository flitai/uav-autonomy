"""Independent B05 two-mode receipt and source qualification gate."""
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


def session(run_id, mode):
    run = ROOT / 'out/runs' / run_id
    result = release.load(run / 'runtime-result.json')
    need(result['status'] == 'passed' and result['task'] == 'G6-B05' and
         len(result['cases']) == 1 and result['cases'][0]['status'] == 'passed' and
         result['cases'][0]['mode'] == mode,
         'B05 runtime did not pass in '+mode)
    transitions = result['cases'][0]['transitions']
    need(transitions[-1]['phase'] == 'shutdown-finished' and
         transitions[-1]['normalExit'], 'B05 runtime did not exit normally')
    need(not result['cases'][0].get('cleanupErrors') and not result.get('error'),
         'B05 runtime has cleanup errors')
    return dict(runId=run_id, mode=mode, runtimeSHA256=release.digest(run / 'runtime-result.json'),
                normalExit=True)


def flow(run_id, mode, expected_session):
    run = ROOT / 'out/runs' / run_id
    result = release.load(run / 'result.json')
    need(result['status'] == 'passed' and
         result['mode'] == ('Gui' if mode == 'sequence' else mode),
         'B05 '+mode+' flow failed')
    review = result['review']
    planner_run = ROOT / 'out/runs/g6-b05-plan' / review['plannerRunId']
    planner = release.load(planner_run / 'result.json')
    need(planner['status'] == 'passed' and planner['isolatedPlannerQualified'] and
         planner['exitCode'] == 0 and not planner['forcedTermination'] and
         planner['plannerLogSHA256'] == release.digest(planner_run / 'planner.jsonl') and
         planner['responseXmlSHA256'] == release.digest(planner_run / 'response.xml') and
         planner['plan'] == review['plan'], 'Isolated planner source or result changed')
    need(review['identity']['runId'] == expected_session and
         len(result['audit']['tasks']) == 3 and
         {x['vehicleId'] for x in result['audit']['commands']} ==
         ({'400','500'} if mode == 'parallel' else {'400'}),
         'Two-mode assignment or task audit differs')
    if mode == 'parallel':
        need(result['wrongCandidateRejected'] and result['wrongDigestRejected'],
             'Headless qualification rejection evidence missing')
    else:
        need(result['edgeExitCode'] == 0 and
             (run / 'review.png').is_file() and (run / 'completed.png').is_file(),
             'Gui Edge or screenshot evidence missing')
    return dict(runId=run_id, planId=review['planId'],
                plannerRunId=review['plannerRunId'], mode=mode,
                assignment=[(x['taskId'],x['vehicleId']) for x in review['plan']['assignments']],
                taskCompleteSHA256={k:v['completeSHA256'] for k,v in result['audit']['tasks'].items()},
                flowSHA256=release.digest(run / 'result.json'))


def port_free(number):
    with socket.socket() as client:
        client.settimeout(.3)
        return client.connect_ex(('127.0.0.1', number)) != 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--build-run-id', required=True)
    parser.add_argument('--headless-session', required=True)
    parser.add_argument('--headless-flow', required=True)
    parser.add_argument('--gui-session', required=True)
    parser.add_argument('--gui-browser', required=True)
    args = parser.parse_args()
    run = ROOT / 'out/runs' / args.run_id
    need(not run.exists(), 'B05 acceptance ID exists')
    run.mkdir(parents=True)
    record = dict(task='G6-B05', runId=args.run_id, status='running',
                  assignmentQualified=False)
    try:
        build_file = ROOT / 'out/runs' / args.build_run_id / 'result.json'
        build = release.load(build_file)
        need(build['status'] == 'passed' and build['task'] == 'G6-B05' and
             build['viewerQualified'], 'B05 viewer candidate differs')
        need(all(release.digest(ROOT / row['path']).lower() == row['sha256'].lower()
                 for row in build['inputs']), 'B05 source inputs changed')
        headless_session = session(args.headless_session, 'Headless')
        gui_session = session(args.gui_session, 'Gui')
        headless = flow(args.headless_flow, 'parallel', args.headless_session)
        gui = flow(args.gui_browser, 'sequence', args.gui_session)
        ports = (5556, 8001, 8002, 8003, 8004, 8005, 8080, 9999, 10031,
                 19400, 19500, 19600)
        need(all(port_free(port) for port in ports), 'B05 session port was not released')
        record.update(status='passed', assignmentQualified=True,
                      buildRunId=args.build_run_id,
                      buildSHA256=release.digest(build_file),
                      sessions=[headless_session, gui_session],
                      flows=[headless, gui], portsReleased=list(ports),
                      statisticsScope='TaskActive/TaskComplete duration and AMASE flight distance')
        return 0
    except Exception as error:
        record.update(status='failed', error=str(error), traceback=traceback.format_exc())
        print(record['traceback'], file=sys.stderr)
        return 1
    finally:
        release.save(run / 'acceptance.json', record)


if __name__ == '__main__':
    sys.exit(main())
