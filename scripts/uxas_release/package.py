"""Qualified native package and evidence checks. No application is started here."""
import os
from pathlib import Path
import re
import shutil
from types import SimpleNamespace
import importlib.util
import ctypes

spec = importlib.util.spec_from_file_location('hello_runtime', Path(__file__).parents[1] / 'uxas_runtime/run.py')
runtime = importlib.util.module_from_spec(spec); spec.loader.exec_module(runtime)
lmcp = runtime.lmcp
require, load, save, sha, child = runtime.require, runtime.load, runtime.save, runtime.sha, runtime.child


def inputs(root):
    paths = ['scripts/windows/uxas-release-common.ps1', 'scripts/windows/publish-uxas.ps1',
             'scripts/windows/run-uxas-release.ps1', 'tests/windows/uxas-release.tests.ps1', 'OpenUxAS/LICENSE.md']
    for directory in ('scripts/uxas_release', 'tests/uxas_release'):
        paths.extend(p.relative_to(root).as_posix() for p in (root / directory).rglob('*') if p.is_file())
    return runtime.runtime_inputs(root) + [dict(path=p, sha256=sha(root / p)) for p in sorted(paths)]


def candidate_args(root, provenance):
    return SimpleNamespace(root=root, build_run_id=provenance['buildRunId'],
                           validation_run_id=provenance['validationRunId'],
                           candidate=root / 'out/build/uxas' / provenance['buildRunId'] / 'candidate')


def check_case(directory, case):
    require(load(directory / 'case-result.json') == case, 'Case record differs')
    lmcp.check_records(directory, case['files'])
    process = case['process']
    require(process['reaped'], 'Owned process not reaped')
    if case['status'] == 'passed':
        evidence = load(directory / 'messages.json')
        require(evidence['status'] == 'passed' and not evidence['errors'] and len(evidence['directions']) == 2 and
                process['exitCode'] == 0 and not process['forcedTermination'], 'HelloWorld case not passed')
    else:
        require(case['expectedFailureVerified'], 'Unexpected process failure')


def hello_receipt(root, run_id, provenance):
    require(re.fullmatch(r'g2-t06-test-[\d-]+', run_id), 'Invalid HelloWorld validation ID')
    directory = child(root / 'out/runs', run_id)
    runtime.build.entry_check(directory)
    result, receipt = load(directory / 'result.json'), load(directory / 'acceptance.json')
    require(result['status'] == receipt['status'] == 'passed' and receipt['runId'] == result['runId'] == run_id and
            result['provenance'] == receipt['provenance'] == provenance and result['sourcesUnchanged'] and
            sha(directory / 'acceptance.json') == result['acceptanceSHA256'] and
            result['runtimeInputs'] == receipt['runtimeInputs'] == runtime.runtime_inputs(root), 'HelloWorld qualification differs')
    for case, sealed in zip(result['cases'], receipt['cases'], strict=True):
        require(case['name'] == sealed['name'] and sha(child(directory, case['name']) / 'case-result.json') == sealed['sha256'],
                'HelloWorld case receipt differs')
        check_case(child(directory, case['name']), case)
    require(sha(directory / 'parser-checks.json') == receipt['parserChecks'] and
            sha(directory / 'owned-timeout/process.json') == receipt['timeoutCheck']['processSHA256'], 'HelloWorld counterexample evidence differs')
    return dict(runId=run_id, acceptanceSHA256=sha(directory / 'acceptance.json'))


def handoff(root, provenance):
    amase = runtime.module('amase_handoff', root / 'scripts/amase/amase.py')
    folder, info, jar = amase.candidate(root, None)
    require(info['acceptance']['status'] == 'passed' and info['acceptance']['guiExitCode'] == 0 and
            info['lmcp']['runId'] == provenance['packages']['generationRunId'], 'AMASE/G1 handoff differs')
    generation = load(root / 'out/generated/lmcp/generation-info.json')
    inventory = runtime.build.graph.inventory(root)
    return dict(generationRunId=generation['runId'], models=generation['models'],
                amase=dict(buildRunId=info['runId'], acceptance=info['acceptance'],
                           buildInfoPath=(folder / 'build-info.json').relative_to(root).as_posix(),
                           buildInfoSHA256=sha(folder / 'build-info.json'), artifact=info['artifact'], lmcp=info['lmcp']),
                packages=provenance['packages'], services=inventory['services'],
                bridges=dict(tcp=True, czmq=True, zyre=False, serial=False),
                verifiedExample='HelloWorld internal bus only', g3Started=False,
                pending=['AMASE/UxAS framing and source filtering', 'startup order and WaterwaySearch execution',
                         'external reconnection', 'second-machine deployment and offline demo (G8)'])


def create(root, destination, provenance, hello, run_id):
    require(not destination.exists(), 'Release staging output must be new')
    destination.mkdir(parents=True)
    candidate = candidate_args(root, provenance).candidate
    shutil.copyfile(candidate / 'uxas.exe', destination / 'uxas.exe')
    shutil.copyfile(root / 'OpenUxAS/examples/01_HelloWorld/cfg_HelloWorld.xml', destination / 'cfg_HelloWorld.xml')
    records = destination / 'provenance'; records.mkdir()
    shutil.copyfile(candidate / 'build-info.json', records / 'candidate-build-info.json')
    shutil.copyfile(root / 'out/generated/lmcp/generation-info.json', records / 'generation-info.json')
    validation = child(root / 'out/runs', provenance['validationRunId'])
    # T05 records loaded paths/hashes, not a guaranteed pre-existing version report.
    loaded = load(validation / 'ordinary-loaded-modules.json')
    require(loaded['modules'].get(str(candidate / 'uxas.exe')) == provenance['executableSHA256'],
            'Loaded candidate evidence differs')
    shutil.copyfile(validation / 'ordinary-loaded-modules.json', records / 'loaded-modules.json')
    required = {'msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'ucrtbase.dll'}
    crt = []
    for path, digest in sorted(loaded['modules'].items()):
        if Path(path).name.lower() in required:
            require(sha(Path(path)) == digest, 'Observed CRT changed before packaging')
            crt.append(dict(path=path, sha256=digest, version=file_version(path)))
    require(len(crt) == 4, 'Four actual loaded CRT files required')
    save(records / 'crt-versions.json', crt)
    licenses = destination / 'licenses'; licenses.mkdir()
    shutil.copyfile(root / 'OpenUxAS/LICENSE.md', licenses / 'OpenUxAS-LICENSE.md')
    deps = Path(load(candidate / 'build-info.json')['context']['dependencies'])
    for original in sorted((deps / 'share').glob('*/copyright')):
        shutil.copyfile(original, licenses / (original.parent.name + '-copyright.txt'))
    require(len(list(licenses.iterdir())) > 1, 'Dependency license inventory missing')
    save(destination / 'handoff.json', handoff(root, provenance))
    info = dict(schemaVersion=1, task='G2-T07', status='candidate', releaseRunId=run_id,
                provenance=provenance, helloWorld=hello, releaseInputs=inputs(root),
                configuration='Release-x64-v143-MD-cxx14', runtimeBundled=False, files=lmcp.files(destination))
    save(destination / 'build-info.json', info)
    check(destination, sha(destination / 'build-info.json'), provenance, allow_candidate=True)
    return info


def check(directory, digest, provenance, allow_candidate=False):
    require(sha(directory / 'build-info.json') == digest, 'Release metadata hash mismatch')
    info = load(directory / 'build-info.json')
    require(info['status'] in (('passed', 'candidate') if allow_candidate else ('passed',)) and
            info['provenance'] == provenance and info['configuration'] == 'Release-x64-v143-MD-cxx14' and
            not info['runtimeBundled'], 'Release package identity differs')
    lmcp.check_records(directory, info['files'])
    require(lmcp.files(directory) == info['files'], 'Release file inventory differs')
    require(sha(directory / 'uxas.exe') == provenance['executableSHA256'] and
            sha(directory / 'provenance/candidate-build-info.json') == provenance['candidateInfoSHA256'],
            'Release differs from accepted candidate')
    runtime.analysis.configuration((directory / 'cfg_HelloWorld.xml').read_bytes())
    return info


def runtime_files(directory):
    records = load(directory / 'provenance/crt-versions.json')
    require(len(records) == 4, 'Expected four qualified CRT files')
    for record in records:
        require(sha(Path(record['path'])) == record['sha256'], 'Installed CRT changed: ' + record['path'])
    return records


def file_version(path):
    """Read the fixed Windows version resource of the hash-verified loaded file."""
    api = ctypes.WinDLL('version', use_last_error=True)
    api.GetFileVersionInfoSizeW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32)]
    api.GetFileVersionInfoSizeW.restype = ctypes.c_uint32
    api.GetFileVersionInfoW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    api.GetFileVersionInfoW.restype = ctypes.c_int
    api.VerQueryValueW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p),
                                 ctypes.POINTER(ctypes.c_uint32)]
    api.VerQueryValueW.restype = ctypes.c_int
    ignored = ctypes.c_uint32()
    size = api.GetFileVersionInfoSizeW(str(path), ctypes.byref(ignored))
    require(size, 'Windows version resource missing')
    buffer = ctypes.create_string_buffer(size)
    require(api.GetFileVersionInfoW(str(path), 0, size, buffer), 'Windows version read failed')
    value, length = ctypes.c_void_p(), ctypes.c_uint32()
    require(api.VerQueryValueW(buffer, '\\', ctypes.byref(value), ctypes.byref(length)) and length.value >= 52,
            'Fixed version resource missing')
    fields = ctypes.cast(value, ctypes.POINTER(ctypes.c_uint32 * 13)).contents
    require(fields[0] == 0xFEEF04BD, 'Fixed version signature differs')
    return '.'.join(str(v) for v in (fields[2] >> 16, fields[2] & 65535, fields[3] >> 16, fields[3] & 65535))


def switch_pointer(store, pointer, tag, after_switch=None):
    """Replace one pointer, retaining the prior bytes and rolling back failed commit."""
    target = child(store, 'current.json')
    previous = target.read_bytes() if target.exists() else None
    temporary = child(store, 'next-' + tag + '.json')
    save(temporary, pointer)
    if previous is not None:
        child(store, 'previous-' + tag + '.json').write_bytes(previous)
    switched = False
    try:
        os.replace(temporary, target)
        switched = True
        if after_switch:
            after_switch()
    except BaseException:
        if switched:
            if previous is None:
                target.unlink()
            else:
                rollback = child(store, 'rollback-' + tag + '.json')
                rollback.write_bytes(previous)
                os.replace(rollback, target)
        raise
    return previous
