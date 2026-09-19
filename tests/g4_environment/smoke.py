"""Dependency/API smoke only; does not claim real backend or gateway acceptance."""
import argparse
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import socket
import struct
import sys
import threading
import time
from urllib.request import urlopen

import fastapi
import pydantic
import uvicorn
import websockets.sync.client


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert sys.version_info[:3] == (3, 14, 7) and struct.calcsize('P') == 8 and sys.prefix != sys.base_prefix
    lock = json.loads((args.root / 'config/g4-python-lock.json').read_text(encoding='utf-8'))
    versions, files = {}, {}
    prefix = Path(sys.prefix).resolve()
    for row in lock['packages']:
        distribution = metadata.distribution(row['name'])
        assert distribution.version == row['version'], row['name']
        versions[row['name']] = distribution.version
        for file in distribution.files:
            path = Path(distribution.locate_file(file)).resolve()
            if path.suffix == '.pyc':
                continue
            assert path.is_relative_to(prefix), str(path)
            assert path.is_file(), str(path)
            files[path.relative_to(prefix).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    for path in (prefix / 'Scripts/python.exe', prefix / 'pyvenv.cfg'):
        files[path.relative_to(prefix).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    class Sample(pydantic.BaseModel):
        entity_id: str
        simulation_time_ms: str
    sample = Sample(entity_id='9223372036854775807', simulation_time_ms='9007199254740993').model_dump()
    app = fastapi.FastAPI()
    @app.get('/smoke')
    async def get():
        return {'status': 'smoke-only', **sample}
    @app.websocket('/smoke')
    async def stream(ws: fastapi.WebSocket):
        await ws.accept()
        await ws.send_json(sample)
        assert await ws.receive_json() == sample
        await ws.send_json({'ack': True})
        await ws.close()
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))  # Explicit test-only ephemeral socket, not a production port fallback.
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, loop='asyncio', http='h11',
                                         ws='websockets-sansio', lifespan='on', log_level='warning'))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]))
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started:
            assert thread.is_alive() and time.monotonic() < deadline, 'Server did not start'
            time.sleep(.02)
        with urlopen(f'http://127.0.0.1:{port}/smoke', timeout=5) as response:
            assert json.load(response) == {'status': 'smoke-only', **sample}
        with websockets.sync.client.connect(f'ws://127.0.0.1:{port}/smoke', open_timeout=5, proxy=None) as ws:
            assert json.loads(ws.recv(timeout=5)) == sample
            ws.send(json.dumps(sample))
            assert json.loads(ws.recv(timeout=5)) == {'ack': True}
    finally:
        server.should_exit = True
        thread.join(15)
        listener.close()
    assert not thread.is_alive(), 'Web server did not exit normally'
    with socket.socket() as check:
        assert check.connect_ex(('127.0.0.1', port)) != 0, 'Listening port remains'
    output = {'status': 'passed', 'python': sys.version, 'versions': versions, 'port': port,
              'checks': ['imports', 'pydantic-v2', 'int64-strings', 'http', 'websocket-roundtrip', 'normal-close'],
              'files': [{'path': path, 'sha256': digest} for path, digest in sorted(files.items())]}
    args.output.write_text(json.dumps(output, indent=2) + '\n', encoding='utf-8')
    print('G4 dependency smoke passed')


if __name__ == '__main__':
    main()
