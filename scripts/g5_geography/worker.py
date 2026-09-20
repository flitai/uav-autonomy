"""G5-T02 candidate derivation and independent qualification orchestration."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time
import traceback

sys.path.insert(0,str(Path(__file__).resolve().parent))
from digest import full_digest
from pmtiles import Archive, representatives
from sources import fetch, need, save, sha
from terrain import scene_extent
from regional import derive_regional, verify_sources


def load(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def files(folder):
    return [dict(path=p.relative_to(folder).as_posix(),sha256=sha(p)) for p in sorted(folder.rglob('*')) if p.is_file()]


def prepare(root,run):
    config=load(root/'config/g5-terrain.json');lock=load(root/'config/g5-geography-lock.json')
    output=root/'out/geography'/run.name;output.mkdir(parents=True,exist_ok=False)
    cache=root/'out/geography/input-cache'
    regional=load(root/'config/g5-regional-sources.json')
    print('Checking locked USGS/Copernicus sources and conversion resources',flush=True)
    for row in regional['grids']:fetch(row,cache)
    save(output/'regional-source-proof.json',verify_sources(root,regional))
    for row in lock['vectorFiles']:
        name=Path(row['path']).stem;print('Hashing and auditing '+name,flush=True)
        def progress(v):save(run/'progress.json',dict(stage=name,**v))
        digest=full_digest(root/row['path'],progress)
        need(digest['sha256']==row['sha256'] and digest['bytes']==row['bytes'],'PMTiles locked content differs')
        archive=Archive(root/row['path'])
        try:
            result=dict(path=row['path'],digest=digest,header=archive.header,metadata=archive.metadata,
                index=archive.audit(run/(name+'-blob-ends.bin'),progress),samples=representatives(archive))
            save(output/(name+'-validation.json'),result)
        finally:archive.close()
    scene_extent(root,output,config)
    print('Deriving same-source raster, DTED and Cesium heightfield',flush=True)
    terrain=derive_regional(root,output,config,regional)
    manifest=dict(schemaVersion=1,task='G5-T02',runId=run.name,qualification='candidate',stageQualified=False,
                  terrain=terrain,inputs=load(run/'context.json')['inputs'],files=files(output),
                  environment=load(run/'context.json')['environment'],upstream=load(run/'context.json')['upstream'],
                  externalResources=regional['grids'],rawDataReadOnly=True,
                  globalTerrainQualified=False,oldTerrariumUsedForPrimary=False)
    save(output/'manifest.json',manifest)
    return dict(candidate=output.relative_to(root).as_posix(),manifestSHA256=sha(output/'manifest.json'))


def test(root,run,build):
    need(build and Path(build).name==build,'Invalid candidate run ID')
    previous=root/'out/runs'/build;result=load(previous/'result.json')
    need(result['status']==load(previous/'entry-result.json')['status']=='passed','Candidate entry did not pass')
    context=load(run/'context.json')
    need(result['inputs']==context['inputs'],'Geography sources changed; prepare a new candidate')
    def bindings(value):
        copy=json.loads(json.dumps(value))
        for key in ('baselineRunId','baselineSHA256'):copy['backend'].pop(key,None)
        return copy
    need(result['environment']==context['environment'] and bindings(result['upstream'])==bindings(context['upstream']),
         'Candidate backend/tool bindings changed')
    candidate=root/result['outcome']['candidate']
    need(candidate.resolve().is_relative_to(root/'out/geography'),'Unsafe candidate path')
    need(sha(candidate/'manifest.json')==result['outcome']['manifestSHA256'],'Candidate manifest changed')
    manifest=load(candidate/'manifest.json')
    for row in manifest['files']:
        path=(candidate/row['path']).resolve()
        need(path.is_relative_to(candidate) and sha(path)==row['sha256'],'Candidate file changed: '+row['path'])
    spec=importlib.util.spec_from_file_location('g5_geography_validation',root/'tests/g5_geography/validate.py')
    validation=importlib.util.module_from_spec(spec);spec.loader.exec_module(validation)
    checks=validation.validate(root,candidate,run)
    acceptance=dict(schemaVersion=1,status='passed',task='G5-T02',buildRunId=build,validationRunId=run.name,
        candidate=candidate.relative_to(root).as_posix(),manifestSHA256=sha(candidate/'manifest.json'),checks=checks,
        regionalTerrainQualified=True,globalSimulationQualified=False,backendTerrainExecutionQualified=False,stageQualified=False)
    save(run/'acceptance.json',acceptance)
    return dict(acceptance='out/runs/'+run.name+'/acceptance.json',acceptanceSHA256=sha(run/'acceptance.json'),checks=len(checks))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--run-id',required=True)
    parser.add_argument('--action',choices=['prepare','test'],required=True);parser.add_argument('--build-run-id')
    args=parser.parse_args();root=args.root.resolve();run=root/'out/runs'/args.run_id
    result=dict(status='running',startedAt=time.time())
    try:
        result.update(prepare(root,run) if args.action=='prepare' else test(root,run,args.build_run_id));result['status']='passed'
    except BaseException as error:
        result.update(status='failed',error=str(error),traceback=traceback.format_exc());raise
    finally:save(run/'worker-result.json',result)


if __name__=='__main__':main()
