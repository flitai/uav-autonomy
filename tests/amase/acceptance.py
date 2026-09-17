"""Isolated integration cases and gated AMASE publication; standard library only."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time


def driver(root):
    spec = importlib.util.spec_from_file_location('amase_driver', root / 'scripts/amase/amase.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def automatic(op, args):
    d = driver(op.root)
    root = op.root
    _, build_info, lmcp_jar = d.candidate(root, args.build_run_id)
    d.require(args.gui_run_id, 'GuiRunId is required for automatic acceptance')
    gui = d.inside(root / 'out/runs', args.gui_run_id)
    gui_info = d.load(gui / 'result.json')
    d.require(gui_info['buildRunId'] == args.build_run_id and gui_info['status'] == 'awaiting-manual-confirmation', 'GUI batch/status mismatch')
    d.evidence(gui, 'gui', lmcp_jar)
    op.record.update(buildRunId=args.build_run_id, guiRunId=args.gui_run_id, cases=[])
    fixture = d.inside(root / 'out/tmp', op.id + '/project \u4e2d\u6587 space')
    fixture.mkdir(parents=True)
    harness = fixture.parent / 'entry-utf8.ps1'
    harness.write_text('''param([string]$EntryFile,[string]$PythonExecutable,[string]$Mode,[int]$Port,[string]$BuildRunId,[string]$Scenario)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$entryArguments = @{PythonExecutable=$PythonExecutable}
if ($Mode) { $entryArguments.Mode=$Mode; $entryArguments.Port=$Port; $entryArguments.BuildRunId=$BuildRunId; $entryArguments.ValidateRun=$true; $entryArguments.EntityPortOffset=10000 }
if ($Scenario) { $entryArguments.Scenario=$Scenario }
& $EntryFile @entryArguments
''',encoding='utf-8')
    protected = {str(p.relative_to(root)): d.sha(p) for folder in ('out/artifacts/lmcp','out/artifacts/amase')
                 for p in (root / folder).rglob('*') if p.is_file()}
    original_inputs = d.inputs(root)

    def case(name, action):
        print('CASE=' + name, flush=True)
        try:
            value = action()
            op.record['cases'].append(dict(name=name,status='passed',evidence=value))
            d.save(op.run / 'result.json', op.record)
            print('PASS=' + name, flush=True)
            return value
        except Exception as error:
            op.record['cases'].append(dict(name=name,status='failed',error=str(error)))
            raise

    def invoke(project, label, action='run', build_id=None, scenario=None, expected=None, port=5556):
        entry = project / 'scripts/windows' / ('build-amase.ps1' if action == 'build' else 'run-amase.ps1')
        argv = ['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(harness),'-EntryFile',str(entry),'-PythonExecutable',sys.executable]
        if action == 'run':
            argv += ['-Mode','Headless','-Port',str(port),'-BuildRunId',build_id]
            if scenario:
                argv += ['-Scenario',str(scenario)]
        before = set((project / 'out/runs').glob('g1-t04-*'))
        result = subprocess.run(argv,cwd=fixture.parent,capture_output=True,timeout=150,creationflags=subprocess.CREATE_NO_WINDOW)
        (op.run / (label + '.stdout.log')).write_bytes(result.stdout)
        (op.run / (label + '.stderr.log')).write_bytes(result.stderr)
        result.stdout.decode('utf-8')
        result.stderr.decode('utf-8')
        created = set((project / 'out/runs').glob('g1-t04-*')) - before
        d.require(len(created) == 1, 'Expected one new operation record: ' + label)
        record = d.load(created.pop() / 'result.json')
        evidence = dict(command=argv,workingDirectory=str(fixture.parent),exitCode=result.returncode,runId=record['runId'],status=record['status'])
        if expected:
            d.require(result.returncode != 0 and record['status'] == 'failed' and expected in record.get('error',''), 'Wrong failure: ' + label)
            evidence['error'] = record['error']
        else:
            d.require(result.returncode == 0 and record['status'] == ('built' if action == 'build' else 'automatic-passed'), 'Unexpected failure: ' + label)
        d.save(op.run / (label + '.json'), evidence)
        return evidence

    case('headless-other-working-directory', lambda: invoke(root,'headless',build_id=args.build_run_id))

    def copy_fixture():
        paths = {p['path'] for p in original_inputs}
        t03 = d.load(root / 'out/artifacts/lmcp/build-info.json')
        paths.update(p['path'] for p in t03['inputs'])
        paths.update([str(d.SCENARIO), 'out/artifacts/lmcp/build-info.json','out/generated/lmcp/generation-info.json', t03['artifact']['path']])
        paths.update('out/generated/lmcp/' + p['path'] for p in t03['generatedFiles'])
        for name in sorted(paths):
            target = d.inside(fixture, name)
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(root / name,target)
        tools = d.load(root / 'config/windows-java-toolchain.json')
        for tool in tools['tools']:
            name = '.tools/' + tool['installDirectory']
            shutil.copytree(root / name,fixture / name)
        return invoke(fixture,'unicode-build',action='build')

    fixture_build = case('unicode-path-build', copy_fixture)['runId']
    case('unicode-path-headless', lambda: invoke(fixture,'unicode-run',build_id=fixture_build))
    case('repeat-headless', lambda: invoke(fixture,'repeat-run',build_id=fixture_build))
    case('missing-scenario', lambda: invoke(fixture,'missing-scenario',build_id=fixture_build,scenario=fixture / 'absent.xml',expected='Missing scenario'))

    malformed = fixture / 'malformed.xml'
    malformed.write_text('<AMASE><broken>',encoding='utf-8')
    case('malformed-scenario', lambda: invoke(fixture,'malformed-scenario',build_id=fixture_build,scenario=malformed,expected='no element found'))

    def changed_file(name, transform, label, expected, action='run'):
        path = fixture / name
        original = path.read_bytes()
        try:
            transform(path,original)
            return invoke(fixture,label,action=action,build_id=fixture_build,expected=expected)
        finally:
            path.write_bytes(original)

    case('missing-dependency', lambda: changed_file(str(d.PROJECT / d.LIBRARIES[0]),lambda p,b:p.unlink(),'missing-dependency','Input missing'))
    case('lmcp-hash-mismatch', lambda: changed_file('out/artifacts/lmcp/java/lmcplib.jar',lambda p,b:p.write_bytes(b+b'corrupt'),'lmcp-hash','T03 JAR hash mismatch'))
    case('compile-error', lambda: changed_file(str(d.PROJECT / 'src/Core/avtas/app/Application.java'),lambda p,b:p.write_bytes(b+b'\nnot valid Java;\n'),'compile-error','ant-jar failed',action='build'))

    def occupied():
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
            sock.bind(('0.0.0.0',5556))
            sock.listen(1)
            return invoke(fixture,'occupied-port',build_id=fixture_build,expected='Port unavailable')
    case('occupied-port',occupied)

    def boundaries():
        d.verify_records(root,original_inputs)
        d.require(protected == {str(p.relative_to(root)):d.sha(p) for folder in ('out/artifacts/lmcp','out/artifacts/amase')
                              for p in (root / folder).rglob('*') if p.is_file()},'Formal artifacts changed')
        d.require(not (root / d.PROJECT / 'build').exists() and not (root / d.PROJECT / 'dist').exists(),'Upstream build outputs created')
        d.require(not list((root / 'scripts/amase').rglob('__pycache__')),'Unexpected Python cache')
        d.require(gui_info['pid'] in d.listener_pid(gui_info['port']),'GUI no longer owns its port')
        d.check_port(5556)
        d.check_port(19400)
        d.check_port(19500)
        return dict(formalInputsUnchanged=True,formalArtifactsUnchanged=True,headlessPortReleased=True,guiRetained=True)
    case('boundaries-and-cleanup',boundaries)
    op.record['fixture'] = str(fixture)
    op.finish('automatic-passed')
    print('VALIDATION_RUN_ID=' + op.id,flush=True)


def finalize(op,args):
    d = driver(op.root)
    root = op.root
    d.require(args.manual_confirmation and args.manual_confirmation.strip(),'Actual manual confirmation is required')
    folder,info,lmcp_jar = d.candidate(root,args.build_run_id)
    validation_dir = d.inside(root / 'out/runs',args.validation_run_id or 'invalid')
    validation = d.load(validation_dir / 'result.json')
    d.require(validation['status'] == 'automatic-passed' and len(validation['cases']) == 11
              and all(c['status'] == 'passed' for c in validation['cases']), 'Automatic cases not passed')
    d.require(validation['buildRunId'] == args.build_run_id and validation['guiRunId'] == args.gui_run_id,'Acceptance batch mismatch')
    gui = d.inside(root / 'out/runs',args.gui_run_id)
    record = d.load(gui / 'result.json')
    d.require(record['buildRunId'] == args.build_run_id and record['status'] in ('awaiting-manual-confirmation','automatic-passed'),'GUI not eligible')
    d.evidence(gui,'gui',lmcp_jar)
    if record['status'] == 'awaiting-manual-confirmation':
        d.require(record['pid'] in d.listener_pid(record['port']),'GUI PID/port no longer match')
        (gui / 'request-shutdown').touch()
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        record = d.load(gui / 'result.json')
        if record['status'] != 'awaiting-manual-confirmation':
            break
        time.sleep(0.25)
    d.require(record['status'] == 'automatic-passed' and record['exitCode'] == 0 and record.get('portReleased'), 'GUI did not exit normally')
    d.check_port(record['port'])
    for port in record['entityPorts'].values():
        d.check_port(port)
    d.verify_records(root,info['inputs'])
    op.record.update(buildRunId=args.build_run_id,validationRunId=args.validation_run_id,guiRunId=args.gui_run_id,
                     manualConfirmation=args.manual_confirmation,guiExitCode=0,portsReleased=True)
    # Stage a complete directory. Rename only resolved descendants of this workspace's out/.
    staged = d.inside(root / 'out/build/amase',op.id + '/publish')
    shutil.copytree(folder,staged)
    info.update(status='passed',acceptance=dict(status='passed',buildRunId=args.build_run_id,
                validationRunId=args.validation_run_id,guiRunId=args.gui_run_id,manualConfirmation=args.manual_confirmation,
                verifiedAt=d.stamp(),guiExitCode=0,portsReleased=True))
    d.save(staged / 'build-info.json',info)
    published = d.inside(root / 'out/artifacts','amase')
    published.parent.mkdir(parents=True,exist_ok=True)
    backup = d.inside(root / 'out/build/amase',op.id + '/previous-artifacts')
    moved = False
    try:
        if published.exists():
            d.require((published / 'build-info.json').is_file(),'Unrecognized previous artifact directory')
            published.rename(backup)
            moved = True
        staged.rename(published)
    except BaseException:
        if moved and not published.exists():
            backup.rename(published)
        raise
    op.record['publishedDirectory'] = str(published)
    op.finish()
    print('PUBLISHED=' + str(published),flush=True)
