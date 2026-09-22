"""Coverage display qualification is independent of frozen G5-T07 sources."""
import importlib.util
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[2]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
missions=module('coverage_missions_common',ROOT/'scripts/g5_missions/common.py')
base=missions.base
load,save,sha,need,invoke=base.load,base.save,base.sha,base.need,base.invoke

def sources():
    paths=[]
    for name in ('apps/cesium_coverage','scripts/g5_coverage','tests/g5_coverage'):
        paths.extend(p for p in (ROOT/name).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    paths.extend(ROOT/p for p in ('config/g5-coverage.json','scripts/windows/g5-coverage-common.ps1','scripts/windows/build-g5-coverage.ps1','scripts/windows/start-g5-coverage-session.ps1','tests/windows/g5-coverage.tests.ps1'))
    return base.inventory(ROOT,paths)

def qualify(baseline):
    folder,binding,backend,mapdir,service,_=missions.qualify(baseline)
    config=load(ROOT/'config/g5-coverage.json')
    candidate,manifest=missions.candidate(config['missionBuildRunId'],binding)
    tested,tested_manifest=missions.candidate(config['missionValidationBuildRunId'],binding)
    receipt=ROOT/'out/runs'/config['missionValidationRunId'];accepted=load(receipt/'acceptance.json')
    need(sha(receipt/'acceptance.json')==config['missionAcceptanceSHA256'] and accepted['status']=='passed' and accepted['missionDisplayQualified'],'T07 acceptance differs')
    for name in ('result.json','entry-result.json'):need(load(receipt/name)['status']=='passed','T07 validation failed')
    need(accepted['candidateSHA256']==sha(tested/'candidate.json'),'T07 accepted candidate differs')
    production=lambda m:{r['path'].split('/dist/',1)[1]:r['sha256'] for r in m['files'] if '/dist/' in r['path']}
    need(production(manifest)==production(tested_manifest),'T07 normal/Chinese assets differ')
    binding.update(missions=dict(buildRunId=candidate.name,candidateSHA256=sha(candidate/'candidate.json'),validationRunId=receipt.name,acceptanceSHA256=sha(receipt/'acceptance.json')))
    return folder,binding,backend,mapdir,service,candidate

def candidate(identity,binding):
    need(identity and re.fullmatch(r'g5-coverage-build-[a-z0-9-]+',identity),'Explicit coverage build required')
    directory=ROOT/'out/build/g5-coverage'/identity;manifest=load(directory/'candidate.json')
    for name in ('result.json','entry-result.json'):need(load(ROOT/'out/runs'/identity/name)['status']=='passed','Coverage build failed')
    need(manifest['inputs']==sources() and missions.entities.state.t04.stable(manifest['binding'])==missions.entities.state.t04.stable(binding),'Coverage sources/bindings changed')
    need(load(ROOT/'out/runs'/identity/'result.json')['candidateSHA256']==sha(directory/'candidate.json'),'Coverage receipt differs')
    base.verify_files(ROOT,manifest['inputs']);base.verify_files(directory,manifest['files'])
    return directory,manifest
