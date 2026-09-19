"""G3-T01 input inspection. No build, application launch, or network connection."""
import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import traceback
import xml.etree.ElementTree as ET


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


release = module('g3_release', Path(__file__).parents[1] / 'uxas_release/release.py')
package, runtime = release.package, release.runtime
require, load, save, sha = release.require, release.load, release.save, release.sha
EXAMPLE = 'OpenUxAS/examples/02_Example_WaterwaySearch/'
SCENARIO = EXAMPLE + 'Scenario_WaterwaySearch.xml'
TASK = EXAMPLE + 'MessagesToSend/tasks/1000_LineSearch_LINE_Waterway_Deschutes.xml'
REQUEST = EXAMPLE + 'MessagesToSend/tasks/1001_AutomationRequest_LINE_Waterway_Deschutes.xml'


def scenario_facts(scenario, task, request, uxas, gui, headless):
    """Validate the unchanged example, while exposing known compatibility risks."""
    require(scenario.tag == 'AMASE' and scenario.findtext('ScenarioData/ScenarioDuration') == '785.0', 'Original scenario duration differs')
    events = scenario.findall('ScenarioEventList/*')
    for kind in ('AirVehicleConfiguration', 'AirVehicleState'):
        identities = [e.findtext('ID') for e in events if e.tag == kind]
        require(sorted(identities) == ['400', '500'], 'Scenario entity set differs: ' + kind)
    require(task.tag == 'LineSearchTask' and task.findtext('TaskID') == '1000', 'Task identity differs')
    points = task.findall('PointList/Location3D')
    require(len(points) == 90, 'Full 90-point waterway required')
    require(request.tag == 'AutomationRequest' and [e.text for e in request.findall('EntityList/int64')] == ['400', '500'] and
            [e.text for e in request.findall('TaskList/int64')] == ['1000'], 'Automation request differs')
    grids = [p.findtext('.//SearchTaskAnalysis/GridResolution') for p in (gui, headless)]
    require(grids == ['20', '20'], 'Both modes require original 20 metre grid')
    commands = [dict(vehicleId=e.findtext('VehicleID'), commandId=e.findtext('CommandID'), status=e.findtext('Status'),
                     eventTimeSeconds=e.get('Time'), firstWaypoint=e.findtext('FirstWaypoint'),
                     waypoints=[dict(number=w.findtext('Number'), next=w.findtext('NextWaypoint')) for w in e.findall('WaypointList/Waypoint')])
                for e in events if e.tag == 'MissionCommand']
    require(sorted((c['vehicleId'], c['commandId']) for c in commands) == [('400', '100'), ('500', '100')], 'Original loiter commands differ')
    return dict(durationSeconds=785, entityIds=['400', '500'], taskId='1000', taskPointCount=len(points),
                points=[{field: p.findtext(field) for field in ('Latitude', 'Longitude', 'Altitude')} for p in points],
                events=[dict(type=e.tag, eventTimeSeconds=e.get('Time'), entityId=e.findtext('ID') or e.findtext('VehicleID'),
                             payloadTime=e.findtext('Time')) for e in events],
                originalCommands=commands, gridResolutionMetres=20, uxasEntityId=uxas.get('EntityID'),
                bridges=[dict(b.attrib, subscriptions=[s.get('MessageType') for s in b.findall('SubscribeToMessage')]) for b in uxas.findall('Bridge')],
                injectedMessages=[dict(m.attrib) for m in uxas.findall("Service[@Type='SendMessagesService']/Message")],
                waypointManagers=[dict(s.attrib) for s in uxas.findall("Service[@Type='WaypointPlanManagerService']")],
                desiredWavelengths=[e.text for e in task.findall('DesiredWavelengthBands/WavelengthBand')],
                duplicateTaskElements={k: v for k, v in Counter(e.tag for e in task).items() if v > 1})


def input_files(root):
    paths = ['config/g3-baseline.json', 'scripts/windows/check-g3-baseline.ps1', 'scripts/g3_baseline/check.py',
             'tests/g3_baseline/checks.py', 'scripts/windows/java-common.ps1', 'scripts/windows/uxas-release-common.ps1']
    return [dict(path=p, sha256=sha(root / p)) for p in paths]


def inspect(root, run):
    context = load(run / 'context.json')
    require(re.fullmatch(r'g2-t07-resolve-[\d-]+', context['resolveRunId']), 'Expected read-only qualification identity')
    qualified_run = root / 'out/runs' / context['resolveRunId']
    release.entry_check(qualified_run)
    qualified = load(qualified_run / 'result.json')
    require(qualified['status'] == 'passed' and not qualified.get('cases'), 'Qualification must not run applications')
    provenance = qualified['provenance']
    destination, pointer = release.resolve(root, provenance)
    require(destination == Path(context['qualifiedPackage']), 'Resolved package path differs')
    handoff = package.handoff(root, provenance)
    require(handoff == load(destination / 'handoff.json'), 'Live G3 handoff differs from published handoff')
    amase = module('g3_amase', root / 'scripts/amase/amase.py')
    folder, info, jar = amase.candidate(root, None)
    accepted = info['acceptance']
    require(accepted['status'] == 'passed' and accepted['guiExitCode'] == 0 and accepted['portsReleased'] and
            accepted['manualConfirmation'].strip(), 'AMASE manual acceptance missing')
    automatic_dir = root / 'out/runs' / accepted['validationRunId']
    gui_dir = root / 'out/runs' / accepted['guiRunId']
    automatic, gui_run = load(automatic_dir / 'result.json'), load(gui_dir / 'result.json')
    require(automatic['status'] == 'automatic-passed' and len(automatic['cases']) == 11 and
            all(c['status'] == 'passed' for c in automatic['cases']) and
            automatic['buildRunId'] == accepted['buildRunId'] and automatic['guiRunId'] == accepted['guiRunId'], 'AMASE automatic evidence differs')
    require(gui_run['status'] == 'automatic-passed' and gui_run['buildRunId'] == info['runId'] and
            gui_run['exitCode'] == 0 and gui_run['portReleased'], 'AMASE GUI exit evidence differs')
    amase.evidence(gui_dir, 'gui', jar)
    generation = load(root / 'out/generated/lmcp/generation-info.json')
    require(generation['runId'] == info['lmcp']['runId'] == provenance['packages']['generationRunId'], 'Mixed message generations')
    lock = load(root / 'config/lmcp-models.json')
    for model in lock['models']:
        require(sha(root / 'OpenUxAS/mdms' / model['file']) == model['sha256'], 'Model hash differs')
    baseline = load(root / 'config/g3-baseline.json')
    amase.verify_records(root, baseline['files'])
    sources = [SCENARIO, TASK, REQUEST, EXAMPLE + 'cfg_WaterwaySearch.xml',
               'OpenAMASE/OpenAMASE/config/amase/Plugins.xml', 'OpenAMASE/OpenAMASE/config/amase_headless/Plugins.xml']
    facts = scenario_facts(*(ET.parse(root / p).getroot() for p in sources))
    # Compare model fields to avoid inventing IDs on the CMASI request/response.
    mdm = ET.parse(root / 'OpenUxAS/mdms/CMASI.xml')
    fields = {n: [f.get('Name') for f in mdm.findall(f".//Struct[@Name='{n}']/Field")]
              for n in ('AutomationRequest', 'AutomationResponse')}
    require('RequestID' not in fields['AutomationRequest'] and 'ResponseID' not in fields['AutomationResponse'], 'CMASI correlation contract changed')
    receipt_paths = [qualified_run / 'result.json', qualified_run / 'entry-result.json',
                     automatic_dir / 'result.json', gui_dir / 'result.json', gui_dir / 'events.jsonl',
                     destination / 'build-info.json', destination / 'handoff.json', folder / 'build-info.json',
                     root / 'out/artifacts/lmcp/build-info.json', root / 'out/generated/lmcp/generation-info.json']
    return dict(provenance=provenance, pointer=pointer, handoff=handoff, javaTools=context['javaTools'],
                python=dict(version=sys.version, executable=sys.executable, bits=struct.calcsize('P') * 8),
                scenario=facts, cmasiFields=fields, acceptanceContract=baseline['acceptance'],
                knownRisks=baseline['knownRisks'], frozenInputs=baseline['files'],
                receipts=[dict(path=p.relative_to(root).as_posix(), sha256=sha(p)) for p in receipt_paths],
                amase=dict(buildRunId=info['runId'], acceptance=accepted, artifact=info['artifact'], lmcp=info['lmcp']),
                models=lock['models'], crt=load(destination / 'provenance/crt-versions.json'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    require(re.fullmatch(r'g3-t01-check-[\d-]+', args.run_id), 'Invalid run ID')
    run = root / 'out/runs' / args.run_id
    record = dict(schemaVersion=1, task='G3-T01', runId=args.run_id, status='running', startedAt=runtime.lmcp.stamp(),
                  simulationStarted=False, networkValidationPerformed=False)
    try:
        require(sys.version_info[:3] == (3, 14, 7) and struct.calcsize('P') == 8 and sys.flags.isolated, 'Expected isolated Python 3.14.7 x64')
        record['inputs'] = input_files(root)
        record['gitHead'] = subprocess.check_output(['git', '-C', root, 'rev-parse', 'HEAD'], encoding='utf-8').strip()
        record['gitStatus'] = subprocess.check_output(['git', '-C', root, 'status', '--short'], encoding='utf-8')
        result = inspect(root, run)
        save(run / 'baseline.json', result)
        module('g3_preserve', root / 'scripts/amase/amase.py').verify_records(root, result['frozenInputs'])
        require(record['inputs'] == input_files(root), 'G3 inspection inputs changed')
        record.update(status='passed', baselineSHA256=sha(run / 'baseline.json'), inputsUnchanged=True,
                      checks=['formal-uxas-and-crt', 'amase-artifact-and-historical-acceptance', 'same-generation-seven-models',
                              'frozen-scene-and-source-files', 'scenario-message-flow-and-criteria'])
        return 0
    except Exception as error:
        record.update(status='failed', error=str(error), traceback=traceback.format_exc())
        print('FAILED: ' + str(error), flush=True)
        return 1
    finally:
        record['finishedAt'] = runtime.lmcp.stamp()
        save(run / 'result.json', record)
        print('G3 baseline evidence: ' + str(run), flush=True)


if __name__ == '__main__':
    sys.exit(main())
