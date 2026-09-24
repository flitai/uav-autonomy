"""Read-only G6-A01 source qualification and Java 11 probe compilation."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def need(ok, message):
    if not ok:
        raise RuntimeError(message)


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    need(args.run_id.startswith('g6-a01-') and all(c.isascii() and (c.isalnum() or c == '-') for c in args.run_id),
         'Invalid G6-A01 run identity')
    need(sys.version_info[:3] == (3, 14, 7) and sys.flags.isolated, 'Expected qualified isolated Python 3.14.7')
    run = ROOT / 'out/runs' / args.run_id
    need(not run.exists(), 'G6-A01 run identity already exists')
    run.mkdir(parents=True)
    record = {'task': 'G6-A01', 'runId': args.run_id, 'status': 'running', 'controlRuntimeQualified': False}
    try:
        pointer_file = ROOT / 'out/artifacts/g5-stage/current.json'
        pointer = load(pointer_file)
        need(pointer['task'] == 'G5-T11' and pointer['stageQualified'], 'G5 formal stage is unavailable')
        package = Path(pointer['package']).resolve()
        need(package.is_relative_to((ROOT / 'out/artifacts/g5-stage').resolve()), 'Formal package escaped workspace')
        need(digest(package / 'manifest.json') == pointer['manifestSHA256'], 'G5 manifest identity differs')
        publication = ROOT / 'out/runs' / pointer['publishRunId']
        need(digest(publication / 'acceptance.json') == pointer['acceptanceSHA256'], 'G5 publication identity differs')
        need(load(publication / 'acceptance.json')['stageQualified'], 'G5 publication not qualified')
        spec = importlib.util.spec_from_file_location('g6_a01_g5_stage', ROOT / 'scripts/g5_stage/common.py')
        stage = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(stage)
        _, manifest = stage.verify_package(pointer['buildRunId'], pointer['manifestSHA256'])
        binding = manifest['parentBinding']['backendTerrain']
        scenario = ROOT / 'out/build/g5-backend' / binding['buildRunId'] / 'small/scenario.xml'
        duration = float(ET.parse(scenario).findtext('./ScenarioData/ScenarioDuration'))
        policy = load(ROOT / 'config/g5-backend-terrain.json')
        need(duration == policy['durationSeconds'] == 1800 and duration > 0, 'Qualified scenario duration differs')
        source_files = [ROOT / name for name in (
            'scripts/g6_control/ControlProbe.java',
            'OpenAMASE/OpenAMASE/src/Amase/avtas/amase/util/SimTimer.java',
            'OpenAMASE/OpenAMASE/src/Amase/avtas/amase/scenario/ScenarioManager.java',
            'OpenAMASE/OpenAMASE/src/Amase/avtas/amase/ui/SimControls.java',
            'scripts/g3_integration/StartupProbe.java')]
        classes = run / 'classes'
        classes.mkdir()
        jars = [ROOT / 'out/artifacts/amase/OpenAMASE.jar', ROOT / 'out/artifacts/lmcp/java/lmcplib.jar']
        need(all(p.is_file() for p in jars), 'Qualified Java dependencies missing')
        javac = ROOT / '.tools/jdk-11.0.32.1+1/bin/javac.exe'
        command = [str(javac), '-encoding', 'UTF-8', '--release', '11', '-cp', os.pathsep.join(map(str, jars)),
                   '-d', str(classes), str(source_files[0])]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
        (run / 'javac.stdout').write_bytes(result.stdout)
        (run / 'javac.stderr').write_bytes(result.stderr)
        need(result.returncode == 0, 'G6 control probe Java 11 compilation failed')
        output = classes / 'validation/g6/ControlProbe.class'
        need(output.is_file(), 'ControlProbe bytecode missing')
        record.update(status='passed', stageManifestSHA256=pointer['manifestSHA256'],
                      publicationSHA256=pointer['acceptanceSHA256'], scenarioDurationSeconds=duration,
                      scenarioSHA256=digest(scenario), javaRelease=11, probeClassSHA256=digest(output),
                      inputs=[{'path': p.relative_to(ROOT).as_posix(), 'sha256': digest(p)} for p in source_files],
                      controlRuntimeQualified=False)
        print('G6_A01_RUN_ID=' + args.run_id + ' STATUS=passed')
        return 0
    except Exception as error:
        record.update(status='failed', error=str(error))
        print('G6_A01_RUN_ID=' + args.run_id + ' STATUS=failed ERROR=' + str(error), file=sys.stderr)
        return 1
    finally:
        (run / 'result.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    sys.exit(main())
