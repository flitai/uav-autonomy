"""G5-T01 qualification matrix, using real builds, HTTP and native Edge."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import urlopen

from common import (exclusive_port, inventory, invoke, load, need, npm_arguments, npm_env, process_env,
                    save, sha, verify_files)


def checks(root, run, folder, baseline):
    from manage import build, download, validate_npm_lock
    records=[]
    for port in (8000,8080,5173,9223):
        with exclusive_port(port): pass
    records.append(dict(name='declared-ports-free', status='passed', ports=[8000,8080,5173,9223]))
    python=folder/'geo/Scripts/python.exe'
    invoke([python,'-I','-B','-X','utf8',root/'tests/g5_environment/geo_smoke.py','--output',run/'geo-probe'],run,'geo-probe')
    records.append(dict(name='independent-geospatial-capabilities', status='passed', result=load(run/'geo-probe/result.json')))

    def server_check(project, case, dev=False, browser=True):
        directory=run/case;directory.mkdir()
        dist=project/'dist';port=5173 if dev else 8080
        args=[folder/'node/node.exe',project/'dev-server.mjs',directory] if dev else [folder/'node/node.exe',root/'scripts/g5_environment/serve.mjs',dist,directory,str(port)]
        with (directory/'stdout.log').open('wb') as stdout,(directory/'stderr.log').open('wb') as stderr:
            process=subprocess.Popen(list(map(str,args)),cwd=project if dev else run,env=npm_env(root,folder,project),
                                     stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
            result=dict(name=case,status='running',port=port,pid=process.pid)
            try:
                deadline=time.monotonic()+30
                while time.monotonic()<deadline and not (directory/'ready.json').is_file():
                    need(process.poll() is None,'Resource server exited before ready');time.sleep(.1)
                need((directory/'ready.json').is_file(),'Resource server readiness timed out')
                resources=[]
                for category in ('Workers','ThirdParty','Assets','Widgets'):
                    files=sorted(p for p in (dist/'cesium'/category).rglob('*') if p.is_file())
                    representative=next((p for p in files if p.suffix in ('.js','.wasm','.json','.css')),files[0])
                    relative=representative.relative_to(dist).as_posix()
                    with urlopen(f'http://127.0.0.1:{port}/'+relative,timeout=10) as response: content=response.read()
                    need(hashlib.sha256(content).hexdigest()==sha(representative),'Served resource differs: '+relative)
                    resources.append(relative)
                try: urlopen(f'http://127.0.0.1:{port}/cesium/Assets/absent-g5-file.json',timeout=5)
                except HTTPError as error: need(error.code==404,'Missing resource was not 404')
                else: raise RuntimeError('Missing resource silently accepted')
                if browser:
                    invoke([python,'-I','-B','-X','utf8',root/'tests/g5_environment/browser.py','--url',f'http://127.0.0.1:{port}/',
                            '--output',directory/'edge'],directory,'edge',timeout=180)
                result.update(status='passed',resources=resources,browser=load(directory/'edge/result.json') if browser else None)
            except BaseException as error:
                result.update(status='failed',error=str(error));raise
            finally:
                (directory/'request-stop').touch()
                try: process.wait(timeout=30);result.update(exitCode=process.returncode,forcedTermination=False)
                except subprocess.TimeoutExpired:
                    process.kill();process.wait();result.update(status='failed',forcedTermination=True)
                if process.returncode!=0:result['status']='failed'
                with exclusive_port(port): pass
                result['portReleased']=True;save(directory/'result.json',result)
            need(result['status']=='passed','Resource server did not finish normally')
            records.append(dict(name=case,status='passed',evidence=str(directory.relative_to(run))))

    builds=[]
    for chinese,label in ((False,'normal'),(True,'chinese')):
        case=run/label;case.mkdir()
        # Same public build function; the run directory supplies a unique candidate identity.
        case_identity=run.name+'-'+label
        case_run=root/'out/runs'/case_identity;case_run.mkdir()
        candidate=build(root,case_run,folder,chinese)
        save(case_run/'result.json',dict(status='passed',candidate=candidate))
        project=root/candidate['project'];builds.append((candidate,project))
        records.append(dict(name=label+'-clean-build',status='passed',candidate=candidate))
        server_check(project,label+'-production')
    server_check(builds[0][1],'repeated-production-start',browser=False)
    server_check(builds[1][1],'chinese-development',dev=True)

    candidate,project=builds[0]
    # Every refusal uses an isolated copy or a private held socket, never mutating a formal input.
    faults=run/'faults';faults.mkdir()
    missing=faults/'missing-dependency';missing.mkdir()
    for name in ('package.json','package-lock.json','.npmrc','tsconfig.json','vite.config.mjs'):
        shutil.copy2(project/name,missing/name)
    result=subprocess.run(list(map(str,npm_arguments(folder)+['run','build'])),cwd=missing,env=npm_env(root,folder,missing),
                          capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=60)
    (faults/'missing-dependency.stdout').write_bytes(result.stdout);(faults/'missing-dependency.stderr').write_bytes(result.stderr)
    need(result.returncode!=0,'Missing dependencies accepted')
    records.append(dict(name='missing-dependency-refused',status='passed',exitCode=result.returncode))
    expected=inventory(missing,[missing/'package.json'])
    with (missing/'package.json').open('a',encoding='utf-8') as output:output.write(' ')
    try:verify_files(missing,expected)
    except RuntimeError:pass
    else:raise RuntimeError('Altered source accepted')
    records.append(dict(name='altered-source-refused',status='passed'))
    bad_lock=load(missing/'package-lock.json')
    dependency=next(key for key in bad_lock['packages'] if key)
    bad_lock['packages'][dependency]['resolved']='https://example.invalid/dependency.tgz'
    save(missing/'package-lock.json',bad_lock)
    try:validate_npm_lock(missing)
    except RuntimeError:pass
    else:raise RuntimeError('Untrusted npm origin accepted')
    records.append(dict(name='untrusted-npm-origin-refused',status='passed'))
    (faults/'wrong.zip').write_bytes(b'corrupt isolated cache')
    try:download(dict(url='https://nodejs.org/dist/wrong.zip',filename='wrong.zip',sha256='0'*64),faults,'nodejs.org')
    except RuntimeError:pass
    else:raise RuntimeError('Bad download checksum accepted')
    records.append(dict(name='bad-download-checksum-refused',status='passed'))
    for port,dev in ((8080,False),(5173,True)):
        case=faults/str(port);case.mkdir()
        args=[folder/'node/node.exe',project/'dev-server.mjs',case] if dev else [folder/'node/node.exe',root/'scripts/g5_environment/serve.mjs',project/'dist',case,str(port)]
        with exclusive_port(port) as held:
            held.listen()
            refused=subprocess.run(list(map(str,args)),cwd=project,env=npm_env(root,folder,project),capture_output=True,
                                   creationflags=subprocess.CREATE_NO_WINDOW,timeout=30)
            (case/'stderr.log').write_bytes(refused.stderr)
            need(refused.returncode!=0 and not (case/'ready.json').exists(),'Port conflict not refused')
        with exclusive_port(port):pass
        records.append(dict(name=f'port-{port}-conflict-refused',status='passed',exitCode=refused.returncode))
    for candidate,project in builds:
        manifest=load(root/candidate['path']/'candidate.json')
        verify_files(root,manifest['sources']);verify_files(project/'dist',manifest['files'])
    save(run/'checks.json',dict(status='passed',checks=records))
    return records
