"""G1-T05 receive-only client and acceptance entry; standard library only."""
import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import struct
import sys
import time
import traceback
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sentinel import Decoder, SentinelReader, Statistics, require


def stamp():
    return datetime.now().astimezone().isoformat()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest().upper()


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def driver(root):
    return module(root / 'scripts/amase/amase.py', 't04_driver')


def task_inputs(root):
    folders = ('scripts/validation', 'tests/amase_tcp')
    paths = [p for name in folders for p in (root / name).glob('*.py')]
    paths += [root / p for p in ('scripts/windows/receive-amase.ps1', 'scripts/windows/tcp-common.ps1',
                                'tests/windows/amase-tcp.tests.ps1')]
    return [dict(path=p.relative_to(root).as_posix(), sha256=sha(p)) for p in sorted(paths)]


class Operation:
    def __init__(self, root, action):
        self.root = root.resolve()
        self.id = 'g1-t05-' + action + '-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        self.run = self.root / 'out/runs' / self.id
        self.run.mkdir(parents=True)
        self.record = dict(schemaVersion=1, task='G1-T05', runId=self.id, status='running', startedAt=stamp(),
                           invocationDirectory=str(Path.cwd()), command=sys.argv, python=sys.version,
                           pythonExecutable=sys.executable, inputs=task_inputs(root))
        self.flush()
        print('RUN_DIRECTORY=' + str(self.run), flush=True)

    def flush(self):
        save(self.run / 'result.json', self.record)

    def finish(self, status, error=None):
        self.record.update(status=status, finishedAt=stamp())
        if error is not None:
            self.record['error'] = str(error)
        self.flush()


def provenance(root):
    d = driver(root)
    folder, info, jar = d.candidate(root, None)
    require(info.get('acceptance', {}).get('status') == 'passed', 'T04 acceptance not passed')
    py = (root / 'out/generated/lmcp/py').resolve()
    existing = sys.modules.get('lmcp.LMCPFactory')
    if existing:
        require(Path(existing.__file__).resolve().is_relative_to(py), 'Different generated library already loaded')
    else:
        sys.path.insert(0, str(py))
    from lmcp import LMCPFactory
    for name, imported in list(sys.modules.items()):
        if name.split('.')[0] in ('lmcp', 'afrl', 'uxas') and getattr(imported, '__file__', None):
            require(Path(imported.__file__).resolve().is_relative_to(py), 'Unexpected message module source: ' + name)
    return d, info, jar, LMCPFactory


def runtime(root, run_id, d, info, jar):
    require(re.fullmatch(r'g1-t04-run-\d{8}-\d{6}-\d{6}', run_id or ''), 'Invalid AmaseRunId')
    directory = d.inside(root / 'out/runs', run_id)
    record = load(directory / 'result.json')
    require(record['status'] in ('running', 'awaiting-manual-confirmation'), 'AMASE runtime is not active')
    require(record['buildRunId'] == info['runId'], 'Runtime build batch mismatch')
    require(record['mode'] in ('gui', 'headless'), 'Unknown runtime mode')
    require(Path(record['classpath'][0]['path']).resolve() == (root / 'out/artifacts/amase/OpenAMASE.jar').resolve(),
            'Runtime does not use formal AMASE')
    require(Path(record['classpath'][1]['path']).resolve() == jar.resolve(), 'Runtime LMCP path mismatch')
    for entry in record['classpath']:
        require(sha(Path(entry['path'])) == entry['sha256'], 'Runtime classpath hash mismatch')
    require(sha(Path(record['scenarioSource'])) == record['scenarioSha256'], 'Scenario source changed')
    require(record['pid'] in d.listener_pid(record['port']), 'AMASE PID does not own TCP listener')
    initialized = [r for r in d.events(directory) if r['kind'] == 'initialized']
    require(len(initialized) == 1, 'Missing runtime class-loading evidence')
    for field, expected in (('lmcpSource', jar), ('amaseSource', root / 'out/artifacts/amase/OpenAMASE.jar')):
        actual = Path(unquote(urlparse(initialized[0][field]).path).lstrip('/')).resolve()
        require(actual == expected.resolve(), 'Unexpected loaded source: ' + field)
    return directory, record


def connect(port, timeout=15):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            return socket.create_connection(('127.0.0.1', port), timeout=min(1, max(.01, deadline - time.monotonic())))
        except OSError as error:
            last = error
            time.sleep(min(.1, max(0, deadline - time.monotonic())))
    raise RuntimeError('Connection deadline exceeded: ' + str(last))


def capture(sock, directory, factory, minimum=10, maximum=30):
    """Socket is already connected; fixture tests supply isolated loopback peers."""
    parser, decoder, statistics = SentinelReader(), Decoder(factory), Statistics()
    started = time.monotonic()
    record = dict(connectedAt=stamp(), minObservationSeconds=minimum, receiveTimeoutSeconds=maximum,
                  bytesReceived=0, frames=0, stopReason=None)
    samples = set()
    try:
        with (directory / 'capture.bin').open('wb') as raw_file, \
             (directory / 'chunks.jsonl').open('w', encoding='utf-8') as chunk_file, \
             (directory / 'decoded.jsonl').open('w', encoding='utf-8') as decoded_file, \
             (directory / 'frames.jsonl').open('w', encoding='utf-8') as frame_file:
            while True:
                elapsed = time.monotonic() - started
                if elapsed >= minimum and statistics.complete():
                    record['stopReason'] = 'local-observation-complete'
                    break
                require(elapsed < maximum, 'Receive deadline: insufficient advancing entity/session states')
                sock.settimeout(min(.5, maximum - elapsed))
                try:
                    chunk = sock.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    parser.eof()
                    raise RuntimeError('Early EOF before observation completed')
                received = stamp()
                raw_file.write(chunk)
                chunk_file.write(json.dumps(dict(offset=record['bytesReceived'], length=len(chunk), receivedAt=received,
                                                elapsedSeconds=time.monotonic() - started)) + '\n')
                record['bytesReceived'] += len(chunk)
                for frame in parser.feed(chunk):
                    row, lmcp = decoder.decode(frame)
                    row.update(index=record['frames'], receivedAt=received, offset=frame['offset'], length=frame['length'])
                    statistics.add(row)
                    decoded_file.write(json.dumps(row, ensure_ascii=False) + '\n')
                    frame_file.write(json.dumps(dict(index=record['frames'], offset=frame['offset'], length=frame['length'],
                                                     type=row['type'], sha256=hashlib.sha256(frame['wire']).hexdigest().upper())) + '\n')
                    key = 'entity-' + row['id'] if row['type'] == 'afrl.cmasi.AirVehicleState' else 'session' if row['type'] == 'afrl.cmasi.SessionStatus' else None
                    if key and key not in samples:
                        samples.add(key)
                        (directory / (key + '.sentinel.bin')).write_bytes(frame['wire'])
                        (directory / (key + '.lmcp.bin')).write_bytes(lmcp)
                    record['frames'] += 1
        record['status'] = 'passed'
        return record
    except BaseException as error:
        record.update(status='failed', error=str(error))
        raise
    finally:
        record.update(finishedAt=stamp(), observationSeconds=time.monotonic() - started,
                      verifiedFrameBytes=parser.offset, unconsumedTailBytes=len(parser.buffer), statistics=statistics.summary())
        if (directory / 'capture.bin').exists():
            record['captureSha256'] = sha(directory / 'capture.bin')
        save(directory / 'capture-result.json', record)


def receive(op, run_id):
    d, info, jar, factory = provenance(op.root)
    directory, record = runtime(op.root, run_id, d, info, jar)
    op.record.update(amaseRunId=run_id, mode=record['mode'], pid=record['pid'], host='127.0.0.1', port=record['port'],
                     amaseBuildRunId=info['runId'], lmcp=info['lmcp'], scenarioSha256=record['scenarioSha256'],
                     pythonFactory=str(Path(factory.__file__).resolve()), pythonFactorySha256=sha(Path(factory.__file__)))
    op.flush()
    with connect(record['port']) as sock:
        require(sock.getpeername() == ('127.0.0.1', record['port']), 'Unexpected socket peer')
        op.record['capture'] = capture(sock, op.run, factory)
    op.record['socketClosed'] = True
    op.finish('passed')
    print('RECEIVE_RUN_ID=' + op.id, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('action', choices=('receive', 'automatic', 'finalize'))
    parser.add_argument('--amase-run-id')
    parser.add_argument('--validation-run-id')
    parser.add_argument('--manual-confirmation')
    args = parser.parse_args()
    require(sys.version_info[:3] == (3, 14, 7) and struct.calcsize('P') == 8, 'Validated Python 3.14.7 x64 required')
    op = Operation(args.root.resolve(), args.action)
    try:
        if args.action == 'receive':
            receive(op, args.amase_run_id)
        else:
            checks = module(op.root / 'tests/amase_tcp/acceptance.py', 'tcp_acceptance')
            getattr(checks, args.action)(op, args)
    except BaseException as error:
        op.finish('failed', error)
        traceback.print_exc()
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
