"""G5-T03 native build/run/acceptance; consumes immutable T02 receipts."""
import argparse
import os
from pathlib import Path
import re
import shutil
import sys
import time
import traceback
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/g5_environment'))
from common import (environment,inventory,invoke,load,module,need,npm_arguments,npm_env,
                    process_env,save,sha,upstream,verify_files)
from manage import validate_npm_lock


def sources(root):
    paths=[]
    for directory in ('scripts/g5_map','tests/g5_map','apps/cesium_viewer'):
        paths.extend(p for p in (root/directory).rglob('*') if p.is_file() and
                     not {'__pycache__','node_modules','dist'}.intersection(p.parts))
    paths.extend(root/p for p in ('config/g5-map.json','scripts/g5_environment/common.py',
        'scripts/g5_environment/manage.py','tests/g5_environment/browser.py','scripts/windows/g5-map-common.ps1',
        'scripts/windows/build-g5-map.ps1','scripts/windows/run-g5-map.ps1','tests/windows/g5-map.tests.ps1'))
    return inventory(root,paths)


def bindings(value):
    import copy
    result=copy.deepcopy(value)
    for key in ('baselineRunId','baselineSHA256'):result['backend'].pop(key,None)
    return result


def geography(root,config,context,full_hash=False,run=None):
    build=config['geographyBuildRunId'];validation=config['geographyValidationRunId']
    need(all(re.fullmatch(r'g5-t02-[a-z0-9-]+',v) for v in (build,validation)),'Invalid geography identity')
    for identity in (build,validation):
        for name in ('result.json','worker-result.json','entry-result.json'):
            need(load(root/'out/runs'/identity/name)['status']=='passed','Unqualified geography entry')
    acceptance=root/'out/runs'/validation/'acceptance.json';candidate=root/'out/geography'/build
    need(sha(acceptance)==config['geographyAcceptanceSHA256'] and sha(candidate/'manifest.json')==config['geographyManifestSHA256'],'T02 receipt digest differs')
    receipt=load(acceptance);manifest=load(candidate/'manifest.json')
    need(receipt['status']=='passed' and receipt['regionalTerrainQualified'] and receipt['buildRunId']==build and
         receipt['validationRunId']==validation and receipt['manifestSHA256']==sha(candidate/'manifest.json') and
         receipt['candidate']==candidate.relative_to(root).as_posix(),'Geography candidate/acceptance differ')
    result=load(root/'out/runs'/validation/'result.json')
    need(result['outcome']['acceptanceSHA256']==sha(acceptance),'Acceptance differs from parent result')
    verify_files(root,manifest['inputs']);verify_files(candidate,manifest['files'])
    need(manifest['environment']==context['environment'] and bindings(manifest['upstream'])==bindings(context['upstream']),'T02 tool/backend binding differs')
    vector=load(candidate/'planet-validation.json');path=root/vector['path'];stat=path.stat();digest=vector['digest']
    need(stat.st_size==digest['bytes'] and str(stat.st_mtime_ns)==digest['modifiedNs'],'Vector file identity differs')
    if full_hash:
        digest_module=module('g5_map_digest',root/'scripts/g5_geography/digest.py')
        current=digest_module.full_digest(path,lambda value:save(run/'hash-progress.json',value))
        need(current['sha256']==digest['sha256'],'Full PMTiles digest differs');save(run/'vector-digest.json',current)
    else:
        # Full digest is repeated at build; each run additionally checks file identity and header.
        # T02 audited every directory. This bounded startup guard is not another full-content digest.
        with path.open('rb') as stream:prefix=stream.read(127)
        need(prefix[:8]==b'PMTiles\x03' and prefix[97:102]==bytes([2,2,1,0,15]),'PMTiles header differs')
    return candidate,manifest,dict(path=str(path),**digest)


def build(root,run,folder,context,chinese=False):
    config=load(root/'config/g5-map.json')
    print('Verifying T02 terrain and full PMTiles digest',flush=True)
    terrain_dir,geodata,vector=geography(root,config,context,True,run)
    directory=root/'out/build/g5-map'/run.name
    if chinese:directory/='中文 空格工程'
    project=directory/'project';project.mkdir(parents=True,exist_ok=False)
    for row in sources(root):
        source=root/row['path']
        if source.is_relative_to(root/'apps/cesium_viewer'):
            target=project/source.relative_to(root/'apps/cesium_viewer');target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    validate_npm_lock(project)
    font_cache=root/'.tools/cache/g5/map-assets';font_cache.mkdir(parents=True,exist_ok=True)
    font_dir=project/'public/fonts';font_dir.mkdir(parents=True,exist_ok=True)
    for item in config['font']['files']:
        path=font_cache/item['filename']
        if not path.exists():
            with urlopen(item['url'],timeout=60) as response:data=response.read(item['bytes']+1)
            import hashlib
            need(len(data)==item['bytes'] and hashlib.sha256(data).hexdigest()==item['sha256'],'Font download differs');path.write_bytes(data)
        need(path.stat().st_size==item['bytes'] and sha(path)==item['sha256'],'Font cache differs');shutil.copy2(path,font_dir/item['filename'])
    env=npm_env(root,folder,project)
    invoke(npm_arguments(folder)+['ci','--offline','--ignore-scripts','--no-audit','--no-fund'],run,'npm-ci',cwd=project,env=env)
    invoke(npm_arguments(folder)+['run','build'],run,'frontend-build',cwd=project,env=env)
    dist=project/'dist';licenses=dist/'licenses';licenses.mkdir()
    for name in ('LICENSE.md','ThirdParty.extra.json','ThirdParty.json'):
        source=project/'node_modules/cesium'/name
        if source.is_file():shutil.copy2(source,licenses/name)
    for name in ('Workers','ThirdParty','Assets','Widgets'):need(any((dist/'cesium'/name).rglob('*')),'Cesium resource missing')
    terrain=geodata['terrain']
    runtime=dict(schemaVersion=1,stage='G5-T03',simulationConnected=False,
        vector=dict(url='/map/planet.pmtiles',bytes=vector['bytes'],sha256=vector['sha256'],attribution='© OpenStreetMap contributors · Protomaps'),
        terrain=dict(bounds=terrain['bounds'],width=terrain['width'],height=terrain['height'],tileSize=config['terrainTileSize'],
            maxLevel=config['terrainMaximumLevel'],regionId=terrain['regionId'],datum=terrain['cesium']['datum'],
            url='/map/terrain',outsideRegion=config['outsideRegion']),font='/fonts/NotoSansCJKsc-Regular.otf',
        satellite=config['satellite'],limits=config['limits'])
    field=terrain_dir/terrain['cesium']['path']
    service=dict(dist=str(dist),project=str(project),vector=vector,heightfield=dict(path=str(field),sha256=sha(field)),runtime=runtime)
    save(directory/'service.json',service)
    manifest=dict(schemaVersion=1,task='G5-T03',buildRunId=run.name,stageQualified=False,
        inputs=context['inputs'],environment=context['environment'],upstream=context['upstream'],
        geography=dict(buildRunId=config['geographyBuildRunId'],validationRunId=config['geographyValidationRunId'],
            manifestSHA256=config['geographyManifestSHA256'],acceptanceSHA256=config['geographyAcceptanceSHA256']),
        project=project.relative_to(root).as_posix(),serviceSHA256=sha(directory/'service.json'),
        files=inventory(dist,[p for p in dist.rglob('*') if p.is_file()]),packageLockSHA256=sha(project/'package-lock.json'))
    save(directory/'candidate.json',manifest)
    return dict(path=directory.relative_to(root).as_posix(),manifestSHA256=sha(directory/'candidate.json'))


def resolve_candidate(root,identity,context):
    need(identity and re.fullmatch(r'g5-t03-build-[a-z0-9-]+',identity),'Explicit T03 build identity required')
    previous=root/'out/runs'/identity;result=load(previous/'result.json')
    need(result['status']==load(previous/'entry-result.json')['status']=='passed','Map build did not pass')
    reference=result['candidate'];directory=(root/reference['path']).resolve()
    need(directory.is_relative_to(root/'out/build/g5-map') and sha(directory/'candidate.json')==reference['manifestSHA256'],'Candidate manifest differs')
    manifest=load(directory/'candidate.json')
    need(manifest['inputs']==context['inputs'] and manifest['environment']==context['environment'] and
        bindings(manifest['upstream'])==bindings(context['upstream']),'Map sources/tool/backend changed; rebuild')
    verify_files(root,manifest['inputs']);need(sha(directory/'service.json')==manifest['serviceSHA256'],'Service configuration differs')
    service=load(directory/'service.json');project=(root/manifest['project']).resolve()
    need(project.is_relative_to(directory) and Path(service['dist']).resolve()==project/'dist','Unsafe candidate project')
    verify_files(project/'dist',manifest['files'])
    geography(root,load(root/'config/g5-map.json'),context)
    need(sha(Path(service['heightfield']['path']))==service['heightfield']['sha256'],'Runtime terrain changed')
    return directory,manifest,service


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--action',choices=['build','serve','test'],required=True)
    parser.add_argument('--run-id',required=True);parser.add_argument('--baseline-run-id',required=True)
    parser.add_argument('--build-run-id');parser.add_argument('--chinese-path',action='store_true');parser.add_argument('--development',action='store_true')
    args=parser.parse_args();root=ROOT;run=root/'out/runs'/args.run_id
    need(re.fullmatch(r'g5-t03-[a-z0-9-]+',args.run_id) and run.is_dir() and not (run/'result.json').exists(),'Fresh entry-owned run required')
    record=dict(task='G5-T03',runId=args.run_id,action=args.action,status='running',startedAt=time.time(),stageQualified=False,simulationStarted=False)
    before=dict(os.environ);cwd=Path.cwd()
    try:
        record['inputs']=sources(root);folder,_=environment(root);record['environment']=load(root/'.tools/g5/current.json')
        record['upstream']=upstream(root,args.baseline_run_id);save(run/'context.json',record)
        if args.action=='build':record['candidate']=build(root,run,folder,record,args.chinese_path)
        else:
            directory,manifest,service=resolve_candidate(root,args.build_run_id,record)
            if args.action=='serve':
                print('G5_STOP_FILE='+str(run/'request-stop'),flush=True)
                invoke([folder/'node/node.exe',root/'scripts/g5_map/server.mjs',directory/'service.json',run,
                    'development' if args.development else 'production'],run,'server',timeout=None)
                need(load(run/'server-result.json')['status']=='passed','Map server failed to stop normally')
            else:
                validation=module('g5_map_validation',root/'tests/g5_map/checks.py')
                record['acceptance']=validation.checks(root,run,folder,directory,manifest,record)
        verify_files(root,record['inputs']);need(record['environment']==load(root/'.tools/g5/current.json'),'Environment pointer changed')
        record['status']='passed';return 0
    except BaseException as error:
        record.update(status='failed',error=str(error),traceback=traceback.format_exc());print(record['traceback'],flush=True);return 1
    finally:
        record.update(finishedAt=time.time(),environmentUnchanged=before==dict(os.environ),locationUnchanged=cwd==Path.cwd())
        if not record['environmentUnchanged'] or not record['locationUnchanged']:record['status']='failed'
        save(run/'result.json',record);print('G5_T03_EVIDENCE='+str(run),flush=True)


if __name__=='__main__':sys.exit(main())
