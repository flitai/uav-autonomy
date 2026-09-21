"""T06 composes qualified T03/T05 sources and the independently built model reader."""
import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
state=module('g5_entities_state_common',ROOT/'scripts/g5_state/common.py')
base=state.base
load,save,sha,need,invoke=base.load,base.save,base.sha,base.need,base.invoke
model_tools=module('g5_entities_model_tools',ROOT/'scripts/g5_models/tools.py')

def sources():
    paths=[]
    for name in ('apps/cesium_entities','scripts/g5_entities','tests/g5_entities'):
        paths += [p for p in (ROOT/name).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    paths += [ROOT/p for p in ('config/g5-entities.json','scripts/g5_models/convert.py','scripts/windows/g5-entities-common.ps1',
        'scripts/windows/build-g5-entities.ps1','scripts/windows/start-g5-entities-session.ps1','tests/windows/g5-entities.tests.ps1')]
    return base.inventory(ROOT,paths)

def qualify(baseline):
    folder,binding,backend,mapdir,service=state.qualify(baseline)
    config=load(ROOT/'config/g5-entities.json');directory,manifest=state.candidate(config['stateBuildRunId'],binding)
    accepted,accepted_manifest=state.candidate(config['stateValidationBuildRunId'],binding)
    receipt_dir=ROOT/'out/runs'/config['stateValidationRunId'];receipt=load(receipt_dir/'acceptance.json')
    for filename in ('result.json','entry-result.json'):need(load(receipt_dir/filename)['status']=='passed','T05 validation entry failed')
    need(sha(receipt_dir/'acceptance.json')==config['stateAcceptanceSHA256'] and receipt['status']=='passed' and receipt['realStateConnectionQualified'],'T05 acceptance differs')
    need(receipt['candidateSHA256']==sha(accepted/'candidate.json'),'T05 accepted candidate differs')
    production=lambda m:{r['path'].split('/dist/',1)[1]:r['sha256'] for r in m['files'] if '/dist/' in r['path']}
    need(production(manifest)==production(accepted_manifest),'T05 normal/Chinese assets differ')
    package,tool_manifest,tool_pointer=model_tools.resolve()
    model=config['model'];need(sha(ROOT/model['path'])==model['sha256'],'Selected model original differs')
    binding.update(state=dict(buildRunId=directory.name,candidateSHA256=sha(directory/'candidate.json'),validationRunId=receipt_dir.name,acceptanceSHA256=sha(receipt_dir/'acceptance.json')),modelTools=tool_pointer)
    return folder,binding,backend,mapdir,service,directory,package

def candidate(identity,binding):
    import re
    need(identity and re.fullmatch(r'g5-t06-build-[a-z0-9-]+',identity),'Explicit T06 build required')
    directory=ROOT/'out/build/g5-entities'/identity;manifest=load(directory/'candidate.json')
    for filename in ('result.json','entry-result.json'):need(load(ROOT/'out/runs'/identity/filename)['status']=='passed','T06 build failed')
    need(manifest['inputs']==sources() and state.t04.stable(manifest['binding'])==state.t04.stable(binding),'T06 sources/bindings changed')
    need(load(ROOT/'out/runs'/identity/'result.json')['candidateSHA256']==sha(directory/'candidate.json'),'T06 candidate receipt differs')
    base.verify_files(ROOT,manifest['inputs']);base.verify_files(directory,manifest['files'])
    return directory,manifest
