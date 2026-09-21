"""Compose immutable T03 map and T04 terrain qualifications with T05 inputs."""
import importlib.util
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
t04=module('g5_state_backend_common',ROOT/'scripts/g5_backend/common.py')
base=t04.base
load,save,sha,need,invoke=base.load,base.save,base.sha,base.need,base.invoke

def sources(root):
    paths=[]
    for folder in ('apps/cesium_state','scripts/g5_state','tests/g5_state'):
        paths += [p for p in (root/folder).rglob('*') if p.is_file() and not {'__pycache__','dist'}.intersection(p.parts)]
    paths += [root/p for p in ('config/g5-state.json','scripts/windows/g5-state-common.ps1','scripts/windows/build-g5-state.ps1',
        'scripts/windows/run-g5-state.ps1','scripts/windows/start-g5-state-session.ps1','tests/windows/g5-state.tests.ps1','scripts/g4_stage/runtime.py',
        'scripts/g4_stage/entry.py','scripts/g4_recovery/host.py','tests/g5_environment/browser.py')]
    return base.inventory(root,sorted(paths))

def qualify(baseline):
    folder,geography,binding=t04.qualify(ROOT,baseline)
    config=load(ROOT/'config/g5-state.json');accepted=ROOT/'out/runs'/config['backendValidationRunId']
    receipt=load(accepted/'acceptance.json');need(sha(accepted/'acceptance.json')==config['backendAcceptanceSHA256'],'T04 acceptance differs')
    need(receipt['status']=='passed' and receipt['backendTerrainExecutionQualified'],'T04 not qualified')
    for filename in ('result.json','entry-result.json'):need(load(accepted/filename)['status']=='passed','T04 entry not passed')
    manager=module('g5_state_backend_manager',ROOT/'scripts/g5_backend/manage.py')
    backend,manifest=manager.candidate(config['backendBuildRunId'],binding)
    need(receipt['candidateSHA256']==sha(backend/'candidate.json') and t04.stable(receipt['binding'])==t04.stable(binding),'T04 binding differs')
    maps=module('g5_state_map_manager',ROOT/'scripts/g5_map/manage.py')
    mapid=binding['map']['buildRunId']
    mapdir,mapmanifest,service=maps.resolve_candidate(ROOT,mapid,dict(environment=binding['environment'],upstream=binding['upstream'],inputs=maps.sources(ROOT)))
    binding['backendTerrain']=dict(buildRunId=backend.name,validationRunId=accepted.name,acceptanceSHA256=sha(accepted/'acceptance.json'),candidateSHA256=sha(backend/'candidate.json'))
    return folder,binding,backend,mapdir,service

def candidate(identity,binding):
    import re
    need(identity and re.fullmatch(r'g5-t05-build-[a-z0-9-]+',identity),'Explicit T05 build identity required')
    run=ROOT/'out/runs'/identity
    need(load(run/'result.json')['status']==load(run/'entry-result.json')['status']=='passed','T05 build did not pass')
    directory=ROOT/'out/build/g5-state'/identity;manifest=load(directory/'candidate.json')
    need(load(run/'result.json')['candidateSHA256']==sha(directory/'candidate.json'),'Candidate receipt differs')
    need(manifest['inputs']==sources(ROOT) and t04.stable(manifest['binding'])==t04.stable(binding),'T05 inputs or qualification changed; rebuild')
    base.verify_files(ROOT,manifest['inputs']);base.verify_files(directory,manifest['files'])
    return directory,manifest
