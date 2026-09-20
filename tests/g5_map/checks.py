"""Independent T03 service, browser, corruption, proxy and lifecycle matrix."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import copy
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/g5_environment'))
from common import exclusive_port,invoke,load,need,process_env,save,sha


def request(url,headers=None,method='GET'):
    try:response=urlopen(Request(url,headers=headers or {},method=method),timeout=20)
    except HTTPError as error:response=error
    with response:
        data=response.read(5*1024*1024)
        need(len(data)<5*1024*1024,'Response exceeded test bound')
        return response.status,dict(response.headers),data


@contextmanager
def running(command,directory):
    directory.mkdir(parents=True,exist_ok=False)
    record=dict(status='running',arguments=list(map(str,command)),cwd=str(directory),normalExit=False)
    with (directory/'stdout.log').open('wb') as stdout,(directory/'stderr.log').open('wb') as stderr:
        process=subprocess.Popen(list(map(str,command)),cwd=directory,env=process_env(),stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline=time.monotonic()+30
            while not (directory/'ready.json').exists():
                need(process.poll() is None,'Service exited before ready: '+str(directory));need(time.monotonic()<deadline,'Service readiness timeout');time.sleep(.1)
            record['ready']=load(directory/'ready.json');yield process
            record['status']='passed'
        finally:
            (directory/'request-stop').touch()
            try:process.wait(timeout=20);record.update(exitCode=process.returncode,normalExit=process.returncode==0,forcedTermination=False)
            except subprocess.TimeoutExpired:process.kill();process.wait();record.update(status='failed',forcedTermination=True)
            if process.returncode!=0:record['status']='failed'
            save(directory/'lifecycle.json',record)
        need(record['status']=='passed','Service lifecycle failed: '+str(directory))


def http_checks(service):
    base='http://127.0.0.1:8080';vector=service['vector'];size=vector['bytes'];etag='"'+vector['sha256']+'"'
    status,headers,body=request(base+'/map/planet.pmtiles',method='HEAD')
    need(status==200 and int(headers['Content-Length'])==size and headers['ETag']==etag and not body,'Range HEAD differs')
    cases=['bytes=0-126','bytes=127-15680','bytes=-16',f'bytes={size-32}-']
    for header in cases:
        status,headers,data=request(base+'/map/planet.pmtiles',{'Range':header,'If-Range':etag})
        need(status==206,'Range status differs');begin=int(headers['Content-Range'].split(' ')[1].split('-')[0])
        with Path(vector['path']).open('rb') as stream:stream.seek(begin);expected=stream.read(len(data))
        need(data==expected and int(headers['Content-Length'])==len(data),'Range bytes differ from raw input')
    for value in ('','bytes=0-','bytes=0-4194304','bytes=8-4','bytes=0-1,5-6',f'bytes={size}-'):
        status,_,body=request(base+'/map/planet.pmtiles',{'Range':value} if value else {})
        need(status==416 and len(body)<500,'Unbounded/malformed range accepted')
    need(request(base+'/map/planet.pmtiles',{'Range':'bytes=0-15','If-Range':'"wrong"'})[0]==412,'Stale vector version accepted')
    def concurrent(index):return request(base+'/map/planet.pmtiles',{'Range':f'bytes={index*1000}-{index*1000+499}'})[0]
    with ThreadPoolExecutor(max_workers=8) as pool:need(all(code==206 for code in pool.map(concurrent,range(24))),'Concurrent ranges failed')
    for path in ('/missing.js','/map/missing','/%2e%2e/config/g5-map.json','/api/v1/control'):
        need(request(base+path)[0]==404,'Missing/traversal/unknown route accepted')
    need(request(base+'/api/v1/health',method='POST')[0]==405,'Mutation method accepted')
    need(request(base+'/map/terrain/15/0/0.f32')[0]==400,'Excessive terrain zoom accepted')
    for x in range(1330,1405):need(request(base+f'/map/terrain/12/{x}/1012.f32')[0]==200,'Terrain cache stress failed')
    a=request(base+'/map/terrain/12/1342/1012.f32');b=request(base+'/map/terrain/12/1343/1012.f32')
    need(a[0]==b[0]==200 and len(a[2])==len(b[2])==16900,'Terrain payload layout differs')
    for y in range(65):need(a[2][(y*65+64)*4:(y*65+65)*4]==b[2][y*65*4:(y*65+1)*4],'HTTP terrain boundary differs')
    metrics=json.loads(request(base+'/map/health')[2])['metrics']
    need(metrics['peakTerrainCacheBytes']<=64*65*65*4 and metrics['maxRangeBytes']<=4194304,'Resource cache/range is unbounded')
    return dict(status='passed',rangeCases=4,concurrentRequests=24,rejectedRanges=6,sharedTerrainPosts=65,metrics=metrics)


def checks(root,run,folder,directory,manifest,context):
    config=load(directory/'service.json');node=folder/'node/node.exe'
    browser_python=root/load(root/'.tools/g4/current.json')['path']/'Scripts/python.exe'
    records=[]
    for port in (8000,8080,5173,9223):exclusive_port(port).close()
    unit=run/'unit';unit.mkdir()
    invoke([folder/'geo/Scripts/python.exe','-I','-B','-X','utf8',root/'tests/g5_map/fixtures.py',unit/'fixtures'],run,'fixture-data')
    invoke([node,root/'tests/g5_map/unit.mjs',root,config['project'],unit],run,'independent-unit')
    records.append(dict(name='independent-formats-terrain-cache',result=load(unit/'unit-result.json')))
    server=root/'scripts/g5_map/server.mjs'
    def browser(label,url='http://127.0.0.1:8080/',flags=()):
        output=run/label;invoke([browser_python,'-I','-B','-X','utf8',root/'tests/g5_map/map_browser.py','--url',url,'--output',output,*flags],run,label,timeout=240)
        result=load(output/'result.json');need(result['status']=='passed' and result['exitCode']==0 and not result['forcedTermination'],'Browser did not pass/exit normally')
        records.append(dict(name=label,evidence=output.relative_to(root).as_posix(),renderer=result.get('initial',{}).get('renderer')))
    production=run/'生产 服务';fixture=run/'proxy-fixture'
    with running([node,root/'tests/g5_map/proxy_fixture.mjs',fixture],fixture) as gateway:
        with running([node,server,directory/'service.json',production,'production'],production) as process:
            records.append(dict(name='HTTP-Range-cache-terrain',result=http_checks(config)))
            need(request('http://127.0.0.1:8080/api/v1/health')[0]==200,'Gateway health proxy failed')
            status,_,data=request('http://127.0.0.1:8080/api/v1/snapshot?probe=1')
            need(status==503 and json.loads(data)['entity_id']=='9223372036854775807' and json.loads(data)['request'].endswith('?probe=1'),'Proxy status/body/query differs')
            invoke([browser_python,'-I','-B','-X','utf8',root/'tests/g5_map/ws_probe.py','ws://127.0.0.1:8080/api/v1/stream',run/'ws-result.json'],run,'websocket-proxy')
            records.append(dict(name='HTTP-WebSocket-proxy',result=load(run/'ws-result.json')))
            conflict=run/'production-conflict';conflict.mkdir()
            invoke([node,server,directory/'service.json',conflict,'production'],run,'production-conflict',expected=1)
            need('EADDRINUSE' in (run/'production-conflict.stderr').read_text(),'Wrong port conflict rejection')
            browser('browser-offline')
            browser('browser-online',flags=['--online'])
            need(gateway.poll() is None and process.poll() is None and request('http://127.0.0.1:8080/api/v1/health')[0]==200,'Browser failure affected upstream/service')
            save(run/'server-metrics.json',json.loads(request('http://127.0.0.1:8080/map/health')[2]))
        # A second clean start verifies lifecycle and gateway-unavailable behavior separately below.
    restart=run/'restart'
    with running([node,server,directory/'service.json',restart,'production'],restart):
        need(request('http://127.0.0.1:8080/api/v1/health')[0]==503,'Absent gateway not reported')
        browser('browser-restart',flags=['--quick'])
    development=run/'开发 服务'
    with running([node,server,directory/'service.json',development,'development'],development):
        conflict=run/'development-conflict';conflict.mkdir()
        invoke([node,server,directory/'service.json',conflict,'development'],run,'development-conflict',expected=1)
        need('EADDRINUSE' in (run/'development-conflict.stderr').read_text(),'Wrong development port rejection')
        browser('browser-development','http://127.0.0.1:5173/',flags=['--quick'])
    for name,change,diagnostic in [
        ('missing-height',lambda c:c['heightfield'].update(path=str(run/'missing.f32')),'ENOENT'),
        ('wrong-height-hash',lambda c:c['heightfield'].update(sha256='0'*64),'Heightfield digest differs'),
        ('wrong-vector-identity',lambda c:c['vector'].update(bytes=1),'Vector identity differs')]:
        broken=copy.deepcopy(config);change(broken);path=run/(name+'.json');save(path,broken);output=run/name;output.mkdir()
        invoke([node,server,path,output,'production'],run,name,expected=1)
        need(diagnostic in (run/(name+'.stderr')).read_text(),'Wrong corruption rejection: '+name)
    broken=copy.deepcopy(config);broken['runtime']['font']='/fonts/missing.otf';path=run/'missing-font.json';save(path,broken);output=run/'missing-font-server'
    with running([node,server,path,output,'production'],output):browser('browser-missing-font',flags=['--expect-failure'])
    records.append(dict(name='resource-corruption-and-missing-rejection',cases=4))
    for port in (8000,8080,5173,9223):exclusive_port(port).close()
    records.append(dict(name='ports-conflicts-restarts-normal-exit',ports=[8000,8080,5173,9223],passed=True))
    acceptance=dict(schemaVersion=1,task='G5-T03',status='passed',buildRunId=manifest['buildRunId'],validationRunId=run.name,
        candidate=directory.relative_to(root).as_posix(),manifestSHA256=sha(directory/'candidate.json'),
        geography=manifest['geography'],checks=records,mapResourcesQualified=True,simulationDisplayQualified=False,stageQualified=False)
    save(run/'acceptance.json',acceptance)
    return dict(path=(run/'acceptance.json').relative_to(root).as_posix(),sha256=sha(run/'acceptance.json'),checks=len(records))
