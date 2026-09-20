"""Independent G5-T04 source bindings; immutable G4 and T02/T03 evidence."""
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/g5_environment'))
# Load by file to avoid confusing this module with g5_environment/common.py.
def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value

base = module('g5_backend_environment_common', ROOT / 'scripts/g5_environment/common.py')
load, save, sha, need, invoke = base.load, base.save, base.sha, base.need, base.invoke

def sources(root):
    paths = []
    for directory in ('scripts/g5_backend', 'tests/g5_backend', 'scripts/g3_integration',
                      'scripts/g3_execution', 'scripts/g3_completion', 'scripts/g4_mixed'):
        paths += [p for p in (root / directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    paths += [root / p for p in ('config/g5-backend-terrain.json', 'config/g3-startup.json',
        'scripts/g4_recovery/navigation.py', 'scripts/g5_environment/common.py',
        'scripts/g5_map/manage.py', 'scripts/windows/g5-backend-common.ps1',
        'scripts/windows/prepare-g5-backend.ps1', 'scripts/windows/run-g5-backend.ps1',
        'tests/windows/g5-backend.tests.ps1')]
    return base.inventory(root, sorted(set(paths)))

def qualify(root, baseline_id):
    folder, _ = base.environment(root)
    context = dict(environment=load(root / '.tools/g5/current.json'), upstream=base.upstream(root, baseline_id))
    # g5_map/manage imports the already frozen environment common module.
    sys.modules['common'] = base
    maps = module('g5_backend_map_bindings', root / 'scripts/g5_map/manage.py')
    config = load(root / 'config/g5-backend-terrain.json')
    mapconfig = load(root / 'config/g5-map.json')
    need(all(config[k] == mapconfig[k] for k in ('geographyBuildRunId', 'geographyValidationRunId')), 'Terrain binding differs')
    directory, manifest, _ = maps.resolve_candidate(root, config['mapBuildRunId'], dict(context, inputs=maps.sources(root)))
    receipt_path = root / 'out/runs' / config['mapValidationRunId'] / 'acceptance.json'
    receipt = load(receipt_path)
    need(receipt['status'] == 'passed' and receipt['buildRunId'] == config['mapBuildRunId'] and
         receipt['manifestSHA256'] == sha(directory / 'candidate.json'), 'T03 independent acceptance differs')
    for name in ('result.json', 'entry-result.json'):
        need(load(receipt_path.parent / name)['status'] == 'passed', 'T03 entry not qualified')
    geography = root / 'out/geography' / config['geographyBuildRunId']
    return folder, geography, dict(context, map=dict(buildRunId=config['mapBuildRunId'],
        validationRunId=config['mapValidationRunId'], manifestSHA256=sha(directory / 'candidate.json'),
        acceptanceSHA256=sha(receipt_path)), geography=manifest['geography'])

def stable(binding):
    import copy
    value = copy.deepcopy(binding)
    for key in ('baselineRunId', 'baselineSHA256'):
        value['upstream']['backend'].pop(key, None)
    return value
