"""T07 independently composes the qualified entity viewer and terrain grid."""
import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
entities=module('g5_missions_entities_common',ROOT/'scripts/g5_entities/common.py')
base=entities.base
load,save,sha,need,invoke=base.load,base.save,base.sha,base.need,base.invoke

def sources():
    paths=[]
    for name in ('apps/cesium_missions','scripts/g5_missions','tests/g5_missions'):
        paths += [p for p in (ROOT/name).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    paths += [ROOT/p for p in ('config/g5-missions.json','scripts/windows/g5-missions-common.ps1','scripts/windows/build-g5-missions.ps1','scripts/windows/start-g5-missions-session.ps1','tests/windows/g5-missions.tests.ps1')]
    return base.inventory(ROOT,paths)

def qualify(baseline):
    folder,binding,backend,mapdir,service,state_candidate,tools=entities.qualify(baseline)
    config=load(ROOT/'config/g5-missions.json');directory,manifest=entities.candidate(config['entityBuildRunId'],binding)
    accepted,accepted_manifest=entities.candidate(config['entityValidationBuildRunId'],binding)
    receipt_dir=ROOT/'out/runs'/config['entityValidationRunId'];receipt=load(receipt_dir/'acceptance.json')
    for filename in ('result.json','entry-result.json'):need(load(receipt_dir/filename)['status']=='passed','T06 validation entry failed')
    need(sha(receipt_dir/'acceptance.json')==config['entityAcceptanceSHA256'] and receipt['status']=='passed' and receipt['entityDisplayQualified'],'T06 acceptance differs')
    need(receipt['candidateSHA256']==sha(accepted/'candidate.json'),'T06 accepted candidate differs')
    production=lambda m:{r['path'].split('/dist/',1)[1]:r['sha256'] for r in m['files'] if '/dist/' in r['path']}
    need(production(manifest)==production(accepted_manifest),'T06 normal/Chinese assets differ')
    binding.update(entities=dict(buildRunId=directory.name,candidateSHA256=sha(directory/'candidate.json'),validationRunId=receipt_dir.name,acceptanceSHA256=sha(receipt_dir/'acceptance.json')))
    return folder,binding,backend,mapdir,service,directory

def candidate(identity,binding):
    import re
    need(identity and re.fullmatch(r'g5-t07-build-[a-z0-9-]+',identity),'Explicit T07 build required')
    directory=ROOT/'out/build/g5-missions'/identity;manifest=load(directory/'candidate.json')
    for filename in ('result.json','entry-result.json'):need(load(ROOT/'out/runs'/identity/filename)['status']=='passed','T07 build failed')
    need(manifest['inputs']==sources() and entities.state.t04.stable(manifest['binding'])==entities.state.t04.stable(binding),'T07 sources/bindings changed')
    need(load(ROOT/'out/runs'/identity/'result.json')['candidateSHA256']==sha(directory/'candidate.json'),'T07 candidate receipt differs')
    base.verify_files(ROOT,manifest['inputs']);base.verify_files(directory,manifest['files'])
    return directory,manifest
