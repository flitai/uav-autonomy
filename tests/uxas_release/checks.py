"""Isolated source/package failures; these never modify qualified inputs."""
import copy
from pathlib import Path
import shutil


def run(package, root, run, staging, provenance):
    require, sha, save, load = package.require, package.sha, package.save, package.load
    lmcp = package.lmcp
    base = run / 'isolated-faults'; base.mkdir()
    results = []

    def reject(name, action, diagnostic):
        try:
            action()
        except (RuntimeError, OSError) as error:
            require(diagnostic.lower() in str(error).lower(), name + ': unexpected rejection: ' + str(error))
            results.append(dict(name=name, expectedRejection=True, diagnostic=str(error)))
            print(name + ': expected rejection', flush=True)
        else:
            raise RuntimeError(name + ': falsely accepted')

    candidate = package.candidate_args(root, provenance).candidate
    context = load(candidate / 'build-info.json')['context']
    deps = Path(context['dependencies'])
    info = load(deps / 'build-info.json')
    library = next(record for record in info['files'] if record['path'].startswith('lib/') and record['path'].endswith('.lib'))
    missing = base / 'missing-dependency'; missing.mkdir()
    reject('missing-dependency-library', lambda: lmcp.check_records(missing, [library]), 'Required file missing')
    corrupt = base / 'corrupt-dependency'; corrupt.mkdir()
    copied = package.child(corrupt, library['path']); copied.parent.mkdir(parents=True)
    shutil.copyfile(deps / library['path'], copied)
    with copied.open('ab') as stream:
        stream.write(b'T07 isolated corruption')
    reject('corrupt-dependency-library', lambda: lmcp.check_records(corrupt, [library]), 'Input hash mismatch')
    prefix = Path(context['lmcp'])
    lmcp_info = load(prefix / 'build-info.json')
    wrong = copy.deepcopy(lmcp_info); wrong['generationRunId'] = 'unrelated-generation'
    save(base / 'wrong-lmcp-info.json', wrong)
    reject('mixed-lmcp-generation', lambda: lmcp.check_package(root, prefix, wrong, lmcp_info['inputs'],
                                                             provenance['packages']['generationRunId']), 'LMCP metadata identity')
    generated_root = base / 'wrong-generation'
    for relative in ('out/generated/lmcp/generation-info.json', 'out/artifacts/lmcp/build-info.json',
                     'out/artifacts/lmcpgen/build-info.json'):
        target = generated_root / relative; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / relative, target)
    changed = load(generated_root / 'out/generated/lmcp/generation-info.json'); changed['runId'] = 'unrelated-generation'
    save(generated_root / 'out/generated/lmcp/generation-info.json', changed)
    reject('mismatched-generated-source', lambda: lmcp.generation(generated_root), 'G1 parent/generation identity')

    digest = sha(staging / 'build-info.json')
    for kind in ('missing-executable', 'corrupt-executable', 'corrupt-metadata'):
        target = base / kind
        shutil.copytree(staging, target)
        file = target / ('build-info.json' if kind == 'corrupt-metadata' else 'uxas.exe')
        if kind == 'missing-executable':
            file.unlink()
        else:
            with file.open('ab') as stream:
                stream.write(b'T07 isolated corruption')
        expected = 'Required file missing' if kind == 'missing-executable' else (
            'metadata hash mismatch' if kind == 'corrupt-metadata' else 'Input hash mismatch')
        reject(kind, lambda: package.check(target, digest, provenance, allow_candidate=True), expected)
    for kind in ('missing-crt', 'corrupt-crt'):
        target = base / kind; (target / 'provenance').mkdir(parents=True)
        records = load(staging / 'provenance/crt-versions.json')
        copy_crt = target / Path(records[0]['path']).name
        if kind == 'corrupt-crt':
            shutil.copyfile(records[0]['path'], copy_crt)
            with copy_crt.open('ab') as stream:
                stream.write(b'T07 isolated corruption')
        records[0]['path'] = str(copy_crt)
        save(target / 'provenance/crt-versions.json', records)
        reject(kind, lambda: package.runtime_files(target), 'Required file missing' if kind == 'missing-crt' else 'Installed CRT changed')

    # Exercise the actual atomic pointer transaction against a copied qualified package.
    store = base / 'publication'; store.mkdir()
    old = store / 'old-qualified'; shutil.copytree(staging, old)
    old_records = lmcp.files(old); old_info = sha(old / 'build-info.json')
    save(store / 'current.json', dict(path='old-qualified', buildInfoSHA256=old_info))
    previous = (store / 'current.json').read_bytes()
    original_replace = package.os.replace
    def fail_replace(source, destination):
        raise OSError('injected pointer replacement failure')
    try:
        package.os.replace = fail_replace
        reject('publication-before-switch', lambda: package.switch_pointer(store, dict(path='replacement'), 'before'),
               'injected pointer replacement failure')
    finally:
        package.os.replace = original_replace
    require((store / 'current.json').read_bytes() == previous, 'Failed replacement changed the pointer')
    def fail_commit():
        raise RuntimeError('injected commit failure after pointer replacement')
    reject('publication-rollback', lambda: package.switch_pointer(store, dict(path='replacement'), 'fault', fail_commit),
           'injected commit failure')
    require((store / 'current.json').read_bytes() == previous and (store / 'previous-fault.json').read_bytes() == previous,
            'Previous formal pointer was not restored')
    package.check(old, old_info, provenance, allow_candidate=True)
    require(lmcp.files(old) == old_records, 'Previous package changed on publication failure')
    empty = base / 'first-publication'; empty.mkdir()
    reject('first-publication-rollback', lambda: package.switch_pointer(empty, dict(path='replacement'), 'fault', fail_commit),
           'injected commit failure')
    require(not (empty / 'current.json').exists(), 'Failed first publication left a success pointer')
    save(run / 'fault-checks.json', dict(status='passed', scope='isolated copies; production validators/transaction',
                                       checks=results, files=lmcp.files(base), previousPointerPreserved=True, previousPackagePreserved=True))
