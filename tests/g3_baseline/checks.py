"""In-memory boundary cases for the T01 baseline; never edits qualified inputs."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('g3_check', root / 'scripts/g3_baseline/check.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    paths = [check.SCENARIO, check.TASK, check.REQUEST, check.EXAMPLE + 'cfg_WaterwaySearch.xml',
             'OpenAMASE/OpenAMASE/config/amase/Plugins.xml', 'OpenAMASE/OpenAMASE/config/amase_headless/Plugins.xml']
    original = [ET.parse(root / p).getroot() for p in paths]
    facts = check.scenario_facts(*original)
    assert facts['originalCommands'][0]['commandId'] == facts['originalCommands'][1]['commandId'] == '100'
    assert facts['desiredWavelengths'] == ['AllAny'] and facts['duplicateTaskElements'] == {'ViewAngleList': 2}
    cases = [dict(name='original-and-known-risks', status='passed')]
    transforms = [
        ('shortened-duration', lambda r: setattr(r[0].find('ScenarioData/ScenarioDuration'), 'text', '20'), 'duration'),
        ('missing-live-entity', lambda r: r[0].find('ScenarioEventList').remove(r[0].find('ScenarioEventList/AirVehicleState')), 'entity set'),
        ('duplicate-entity', lambda r: setattr(r[0].findall('ScenarioEventList/AirVehicleConfiguration')[1].find('ID'), 'text', '400'), 'entity set'),
        ('shortened-waterway', lambda r: r[1].find('PointList').remove(r[1].find('PointList/Location3D')), '90-point'),
        ('different-task', lambda r: setattr(r[1].find('TaskID'), 'text', '1001'), 'Task identity'),
        ('wrong-request-entity', lambda r: setattr(r[2].find('EntityList/int64'), 'text', '999'), 'request differs'),
        ('wrong-request-task', lambda r: setattr(r[2].find('TaskList/int64'), 'text', '999'), 'request differs'),
        ('coarse-headless-grid', lambda r: setattr(r[5].find('.//SearchTaskAnalysis/GridResolution'), 'text', '100'), '20 metre'),
        ('wrong-original-command', lambda r: setattr(r[0].find('ScenarioEventList/MissionCommand/CommandID'), 'text', '101'), 'loiter commands'),
    ]
    for name, mutate, message in transforms:
        rows = copy.deepcopy(original)
        mutate(rows)
        try:
            check.scenario_facts(*rows)
        except RuntimeError as error:
            assert message in str(error), (name, str(error))
            cases.append(dict(name=name, status='passed', expectedFailureVerified=True, error=str(error)))
        else:
            raise AssertionError('Invalid baseline accepted: ' + name)
    check.module('g3_amase_verify', root / 'scripts/amase/amase.py').verify_records(root, check.load(root / 'config/g3-baseline.json')['files'])
    result = dict(status='passed', simulationStarted=False, cases=cases)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(status='passed', cases=len(cases))))


if __name__ == '__main__':
    main()
