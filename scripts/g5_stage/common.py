"""G5 stage package and immutable T09/T10 evidence bindings."""
import importlib.util
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[2]

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value

coverage = module('g5_stage_coverage', ROOT/'scripts/g5_coverage/common.py')
base = coverage.base
load, save, sha, need = base.load, base.save, base.sha, base.need

def sources():
    paths = [p for folder in ('scripts/g5_stage', 'tests/g5_stage')
             for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    paths += [ROOT/p for p in ('scripts/windows/cesium-stage.ps1',
                               'tests/windows/cesium-stage.tests.ps1')]
    return base.inventory(ROOT, paths)

def parents(baseline_id, build_id, full_id, scale_id):
    folder, binding, backend, mapdir, service, previous = coverage.qualify(baseline_id)
    candidate, candidate_manifest = coverage.candidate(build_id, binding)
    accepted = {}
    for task, run_id in (('G5-T09', full_id), ('G5-T10', scale_id)):
        run = ROOT/'out/runs'/run_id
        receipt = load(run/'acceptance.json')
        need(receipt['task'] == task and receipt['status'] == 'passed' and
             receipt['buildRunId'] == build_id and
             receipt['candidateSHA256'] == sha(candidate/'candidate.json') and
             receipt['binding'] == binding, task+' source binding differs')
        field = 'fullSimulationDisplayQualified' if task == 'G5-T09' else 'scaleDisplayQualified'
        need(receipt[field] and not receipt['stageQualified'], task+' qualification differs')
        for filename in ('result.json', 'entry-result.json', 'runtime-result.json'):
            need(load(run/filename)['status'] == 'passed', task+' '+filename+' failed')
        need(load(run/'result.json')['acceptanceSHA256'].lower() == sha(run/'acceptance.json'),
             task+' acceptance receipt differs')
        base.verify_files(ROOT, [dict(row, sha256=row['sha256'].lower()) for row in receipt['inputs']])
        accepted[task] = dict(runId=run_id, acceptanceSHA256=sha(run/'acceptance.json'))
    need(load(ROOT/'out/runs'/scale_id/'acceptance.json')['fullRunId'] == full_id,
         'T10 did not bind T09')
    return dict(folder=folder, binding=binding, backend=backend,
                candidate=candidate, candidateSHA256=sha(candidate/'candidate.json'),
                parents=accepted, service=load(candidate/'service.json'))

def package_dir(build_id):
    need(build_id.startswith('cesium-stage-build-') and '/' not in build_id and '\\' not in build_id,
         'Explicit stage build identity required')
    return ROOT/'out/build/g5-stage'/build_id/'package'

def verify_package(build_id, expected=None, full_vector=False):
    package = package_dir(build_id)
    manifest = load(package/'manifest.json')
    need(manifest['task'] == 'G5-T11' and manifest['buildRunId'] == build_id,
         'Stage manifest identity differs')
    if expected is not None:
        need(sha(package/'manifest.json') == expected, 'Stage manifest digest differs')
    files = {p.relative_to(package).as_posix() for p in package.rglob('*') if p.is_file()}
    listed = {row['path'] for row in manifest['files']}
    need(files == listed | {'vector/planet.pmtiles', 'manifest.json'},
         'Stage package file set differs')
    base.verify_files(package, manifest['files'])
    vector = package/'vector/planet.pmtiles'
    original = Path(manifest['vector']['sourcePath'])
    a, b = vector.stat(), original.stat()
    need(a.st_size == b.st_size == manifest['vector']['bytes'] and
         a.st_mtime_ns == b.st_mtime_ns == manifest['vector']['modifiedNs'] and
         os.path.samefile(vector, original), 'Stage vector hardlink identity differs')
    if full_vector:need(sha(vector) == manifest['vector']['sha256'], 'Stage vector full digest differs')
    return package, manifest

def service_for(package, target):
    config = load(package/'config.json')
    config.update(dist=str(package/'dist'), project=str(package),
                  vector=dict(config['vector'], path=str(package/'vector/planet.pmtiles')),
                  heightfield=dict(config['heightfield'], path=str(package/'terrain/cesium-heightfield.f32')))
    save(target, config)
    return config
