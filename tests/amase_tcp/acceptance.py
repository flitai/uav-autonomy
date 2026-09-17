"""T05 live GUI/headless acceptance, isolated faults, and manual finalization."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import amase_tcp as c
from sentinel import require


def read_record(path):
    try:
        return c.load(path)
    except (FileNotFoundError,json.JSONDecodeError):
        return None


def wait_for(action, timeout, message):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        result=action()
        if result: return result
        time.sleep(.1)
    raise RuntimeError(message)


def correlate(root, run_id, capture_dir):
    events=c.driver(root).events(root/'out/runs'/run_id)
    entities={}; sessions=set()
    for row in events:
        if row['kind']=='entity': entities.setdefault((row['id'],row['timeMs']),[]).append(row)
        if row['kind']=='session': sessions.add((row['timeMs'],row['state']))
    count=0; states={0:'Stopped',1:'Running',2:'Paused',3:'Reset'}
    for line in (capture_dir/'decoded.jsonl').read_text(encoding='utf-8').splitlines():
        row=json.loads(line)
        if row['type']=='afrl.cmasi.AirVehicleState' and row['id'] in ('400','500'):
            matches=entities.get((row['id'],row['timeMs']),[])
            require(any(all(abs(r[k]-row[k])<1e-9 for k in ('latitude','longitude','altitude')) for r in matches),
                    'Network entity does not match same-run internal event: '+row['id']+'/'+row['timeMs'])
            count+=1
        elif row['type']=='afrl.cmasi.SessionStatus':
            require((row['timeMs'],states.get(row['state'])) in sessions,'Network session missing from same-run events')
            count+=1
    return dict(matchedNetworkStates=count,amaseRunId=run_id)


def file_records(directory):
    return [dict(path=p.relative_to(directory).as_posix(),sha256=c.sha(p)) for p in sorted(directory.rglob('*')) if p.is_file()]


def verify_files(directory, records):
    for entry in records:
        path=(directory/entry['path']).resolve()
        require(path.is_relative_to(directory.resolve()) and c.sha(path)==entry['sha256'],'Acceptance evidence changed: '+entry['path'])


def automatic(op,args):
    d,info,jar,factory=c.provenance(op.root)
    checks=c.module(op.root/'tests/amase_tcp/checks.py','tcp_checks')
    op.record.update(amaseBuildRunId=info['runId'],lmcp=info['lmcp'],cases=[],clients=[])
    protected={str(p.relative_to(op.root)):c.sha(p) for folder in ('out/artifacts/amase','out/artifacts/lmcp')
               for p in (op.root/folder).rglob('*') if p.is_file()}
    children=[]
    # Ensure both PS success and error streams use UTF-8, including errors thrown by an entry script.
    harness=op.run/'invoke.ps1'
    harness.write_text('''param([string]$EntryFile,[string]$PythonExecutable,[string]$Mode,[int]$Port,[string]$AmaseRunId)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$values = @{PythonExecutable=$PythonExecutable}
if ($Mode) { $values.Mode=$Mode; $values.Port=$Port; $values.ValidateRun=$true; $values.EntityPortOffset=if ($Mode -eq 'Headless') {10000} else {0} }
if ($AmaseRunId) { $values.AmaseRunId=$AmaseRunId }
& $EntryFile @values
''',encoding='utf-8')

    def case(name, action):
        print('CASE='+name,flush=True)
        value=action()
        op.record['cases'].append(dict(name=name,status='passed',evidence=value)); op.flush()
        print('PASS='+name,flush=True)
        return value

    def command(project, entry, extra):
        return ['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(harness),
                '-EntryFile',str(project/entry),'-PythonExecutable',sys.executable]+extra

    def start_amase(project,label,mode):
        port=5555 if mode=='Gui' else 5556
        argv=command(project,'scripts/windows/run-amase.ps1',['-Mode',mode,'-Port',str(port)])
        stdout=op.run/(label+'.stdout.log'); stderr=op.run/(label+'.stderr.log')
        with stdout.open('wb') as out,stderr.open('wb') as err:
            process=subprocess.Popen(argv,cwd=op.run,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
        child=dict(process=process,root=project,label=label,command=argv,stdout=stdout)
        children.append(child)
        def started():
            require(process.poll() is None,'AMASE launcher exited before ready: '+label)
            lines=stdout.read_text(encoding='utf-8-sig').splitlines()
            paths=[line.split('=',1)[1] for line in lines if line.startswith('RUN_DIRECTORY=')]
            if not paths: return None
            directory=Path(paths[-1]).resolve()
            require(directory.is_relative_to((project/'out/runs').resolve()),'Runtime directory outside project')
            child['directory']=directory
            record=read_record(directory/'result.json')
            if record and record.get('pid') and record.get('listenerPidVerified')==record['pid']:
                return record
        record=wait_for(started,25,'AMASE did not become ready: '+label)
        child.update(runId=record['runId'],pid=record['pid'])
        c.save(op.run/(label+'.launch.json'),dict(command=argv,workingDirectory=str(op.run),runId=record['runId'],pid=record['pid']))
        return child

    def receive(project,run_id,label,expected=None):
        argv=command(project,'scripts/windows/receive-amase.ps1',['-AmaseRunId',run_id])
        result=subprocess.run(argv,cwd=op.run,capture_output=True,timeout=55,creationflags=subprocess.CREATE_NO_WINDOW)
        (op.run/(label+'.stdout.log')).write_bytes(result.stdout); (op.run/(label+'.stderr.log')).write_bytes(result.stderr)
        output=result.stdout.decode('utf-8-sig'); result.stderr.decode('utf-8-sig')
        paths=[line.split('=',1)[1] for line in output.splitlines() if line.startswith('RUN_DIRECTORY=')]
        require(len(paths)==1,'Client did not report exactly one run directory')
        directory=Path(paths[0]); record=c.load(directory/'result.json')
        if expected:
            require(result.returncode!=0 and record['status']=='failed' and expected in record.get('error',''),'Wrong client failure: '+label)
        else:
            require(result.returncode==0 and record['status']=='passed' and record['socketClosed'],'Client failed: '+label)
            require('36 environment values and execution policies unchanged' in output,'Missing client environment check')
            replay=checks.replay(directory,factory)
            correlation=correlate(project,run_id,directory)
            op.record['clients'].append(dict(root=str(project),runId=record['runId'],amaseRunId=run_id,mode=record['mode'],
                                            replay=replay,correlation=correlation,files=file_records(directory)))
            op.flush()
        return dict(command=argv,workingDirectory=str(op.run),exitCode=result.returncode,runId=record['runId'],
                    status=record['status'],error=record.get('error'))

    def finish_headless(child):
        code=child['process'].wait(timeout=125)
        record=c.load(child['directory']/'result.json')
        require(code==0 and record['status']=='automatic-passed' and record['exitCode']==0 and record['portReleased'],
                'Headless did not finish normally: '+child['label'])
        return dict(runId=record['runId'],exitCode=code,portReleased=True,finalSession=record['validation']['lastSession'])

    try:
        case('protocol-and-receiver-faults',lambda: checks.run_checks(op.run/'synthetic',factory))
        gui=start_amase(op.root,'gui','Gui')
        op.record['guiRunId']=gui['runId']; op.flush()
        case('gui-live-tcp',lambda:receive(op.root,gui['runId'],'gui-client'))
        def gui_ready():
            record=read_record(gui['directory']/'result.json')
            require(gui['process'].poll() is None,'GUI exited before confirmation')
            return record if record and record['status']=='awaiting-manual-confirmation' else None
        wait_for(gui_ready,45,'GUI automatic observation did not finish')
        case('gui-window-and-internal-evidence',lambda:d.evidence(gui['directory'],'gui',jar))
        headless=start_amase(op.root,'headless','Headless')
        case('headless-live-tcp-other-cwd',lambda:receive(op.root,headless['runId'],'headless-client'))
        case('headless-full-scenario-exit',lambda:finish_headless(headless))

        fixture=d.inside(op.root/'out/tmp',op.id+'/project \u4e2d\u6587 space')
        fixture.mkdir(parents=True)
        def copy_fixture():
            t03=c.load(op.root/'out/artifacts/lmcp/build-info.json')
            paths={r['path'] for r in info['inputs']+t03['inputs']+c.task_inputs(op.root)}
            paths.update([str(d.SCENARIO),'out/artifacts/lmcp/build-info.json','out/generated/lmcp/generation-info.json',t03['artifact']['path']])
            paths.update('out/generated/lmcp/'+r['path'] for r in t03['generatedFiles'])
            paths.update(str(p.relative_to(op.root)) for p in (op.root/'out/artifacts/amase').rglob('*') if p.is_file())
            for name in sorted(paths):
                target=d.inside(fixture,name); target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(op.root/name,target)
            for tool in c.load(op.root/'config/windows-java-toolchain.json')['tools']:
                name='.tools/'+tool['installDirectory']; shutil.copytree(op.root/name,fixture/name)
            return dict(root=str(fixture),files=len(paths),rebuilt=False)
        case('unicode-fixture-copy',copy_fixture)
        unicode_run=start_amase(fixture,'unicode','Headless')
        case('unicode-live-tcp',lambda:receive(fixture,unicode_run['runId'],'unicode-client'))
        case('unicode-full-scenario-exit',lambda:finish_headless(unicode_run))
        repeated=start_amase(op.root,'repeat','Headless')
        case('repeat-live-tcp',lambda:receive(op.root,repeated['runId'],'repeat-client'))
        case('repeat-full-scenario-exit',lambda:finish_headless(repeated))

        def corrupt(name,label,expected):
            path=fixture/name; original=path.read_bytes()
            try:
                path.write_bytes(original+b'corrupt')
                return receive(fixture,unicode_run['runId'],label,expected)
            finally:
                path.write_bytes(original)
        case('generated-python-hash-mismatch',lambda:corrupt('out/generated/lmcp/py/afrl/cmasi/AirVehicleState.py','python-hash','Input missing or hash mismatch'))
        case('amase-artifact-hash-mismatch',lambda:corrupt('out/artifacts/amase/OpenAMASE.jar','amase-hash','AMASE artifact hash mismatch'))
        case('lmcp-artifact-hash-mismatch',lambda:corrupt('out/artifacts/lmcp/java/lmcplib.jar','lmcp-hash','T03 JAR hash mismatch'))
        def boundary():
            d.candidate(op.root,None)
            require(protected=={str(p.relative_to(op.root)):c.sha(p) for folder in ('out/artifacts/amase','out/artifacts/lmcp')
                                for p in (op.root/folder).rglob('*') if p.is_file()},'Formal artifacts changed')
            require(c.task_inputs(op.root)==op.record['inputs'],'T05 source changed during validation')
            require(not (op.root/d.PROJECT/'build').exists() and not (op.root/d.PROJECT/'dist').exists(),'Upstream output created')
            for name in ('scripts/validation','tests/amase_tcp','out/generated/lmcp/py'):
                require(not list((op.root/name).rglob('__pycache__')),'Unexpected cache in '+name)
            for port in (5556,19400,19500): d.check_port(port)
            return dict(formalArtifactsUnchanged=True,sourceHashesUnchanged=True,headlessPortsReleased=True,guiRetained=True)
        case('boundaries-and-cleanup',boundary)
        op.record['protectedArtifacts']=protected
        op.finish('awaiting-manual-confirmation')
        print('VALIDATION_RUN_ID='+op.id,flush=True)
        print('GUI_RETAINED='+gui['runId'],flush=True)
    except BaseException:
        for child in children:
            if child['process'].poll() is None and child.get('directory'):
                try:
                    (child['directory']/'request-shutdown').touch()
                    child['process'].wait(timeout=20)
                except subprocess.TimeoutExpired:
                    if child.get('pid') and child['pid'] in d.listener_pid(5555 if child['label']=='gui' else 5556):
                        os.kill(child['pid'],15)
                    child['process'].kill(); child['process'].wait(timeout=5)
                    op.record.setdefault('forcedCleanup',[]).append(child['label'])
        raise


def finalize(op,args):
    require(args.manual_confirmation and args.manual_confirmation.strip(),'Actual GUI confirmation required')
    require(args.validation_run_id and args.validation_run_id.startswith('g1-t05-automatic-'),'Invalid validation run ID')
    d,info,jar,factory=c.provenance(op.root)
    suite_dir=d.inside(op.root/'out/runs',args.validation_run_id)
    suite=c.load(suite_dir/'result.json')
    require(suite['status']=='awaiting-manual-confirmation','Suite is not awaiting confirmation')
    require(len(suite['cases'])==14 and all(i['status']=='passed' for i in suite['cases']),'Automatic cases incomplete')
    require(suite['inputs']==c.task_inputs(op.root),'T05 inputs changed after acceptance')
    require(suite['amaseBuildRunId']==info['runId'] and suite['lmcp']==info['lmcp'],'Acceptance batch mismatch')
    for client in suite['clients']:
        project=Path(client['root']); directory=project/'out/runs'/client['runId']
        require(project.resolve()==op.root or project.resolve().is_relative_to((op.root/'out/tmp').resolve()),'Untrusted fixture path')
        verify_files(directory,client['files'])
    for name,checksum in suite['protectedArtifacts'].items(): require(c.sha(op.root/name)==checksum,'Formal artifact changed')
    gui=d.inside(op.root/'out/runs',suite['guiRunId']); record=c.load(gui/'result.json')
    d.evidence(gui,'gui',jar)
    if record['status']=='awaiting-manual-confirmation':
        require(record['pid'] in d.listener_pid(record['port']),'GUI PID no longer owns port')
        (gui/'request-shutdown').touch()
    def stopped():
        value=read_record(gui/'result.json')
        return value if value and value['status']!='awaiting-manual-confirmation' else None
    record=wait_for(stopped,20,'GUI did not exit normally')
    require(record['status']=='automatic-passed' and record['exitCode']==0 and record['portReleased'],'GUI exit validation failed')
    for port in (5555,5556,9400,9500,19400,19500): d.check_port(port)
    op.record.update(validationRunId=suite['runId'],guiRunId=suite['guiRunId'],manualConfirmation=args.manual_confirmation,
                     guiExitCode=0,portsReleased=True,amaseBuildRunId=info['runId'],lmcp=info['lmcp'])
    suite.update(status='passed',manualConfirmation=args.manual_confirmation,finalizeRunId=op.id,finishedAt=c.stamp())
    c.save(suite_dir/'result.json',suite)
    op.finish('passed')
