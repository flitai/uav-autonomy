"""Local read-only HTTP/WebSocket service. Runtime ownership stays outside it."""
import argparse
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import sys
from typing import Annotated, Literal

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / 'src'))
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
import uvicorn
from sim_bridge.codec import ProtocolError
from sim_bridge.gateway import Gateway


class Snapshot(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    schema_version: Literal[1]
    run_id: str
    stream_id: str
    sequence: Annotated[str, Field(pattern=r'^[0-9]+$')]
    kind: Literal['snapshot']
    source_time_ms: str | None
    state: dict


def application(gateway):
    @asynccontextmanager
    async def lifespan(app):
        gateway.start()
        try:
            yield
        finally:
            await asyncio.to_thread(gateway.stop)

    app = FastAPI(title='G4 simulation observer', version='1', lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.get('/api/v1/health')
    def health():
        return gateway.health()

    @app.get('/api/v1/snapshot', response_model=Snapshot)
    def snapshot():
        try:
            return gateway.publication.snapshot()
        except ProtocolError:
            return JSONResponse(gateway.health(), status_code=503)

    @app.get('/', response_class=HTMLResponse)
    def diagnostic():
        return (Path(__file__).parent / 'diagnostic.html').read_text(encoding='utf-8')

    @app.websocket('/api/v1/stream')
    async def stream(websocket: WebSocket):
        await websocket.accept()
        mailbox = None
        receiver = None
        try:
            try:
                initial, mailbox = gateway.publication.subscribe()
            except ProtocolError:
                await websocket.send_json(gateway.health())
                await websocket.close(code=1013, reason='Snapshot not available; reconnect')
                return
            await asyncio.wait_for(websocket.send_text(Snapshot.model_validate(initial).model_dump_json()), timeout=5)
            # A reader exists solely to detect disconnects and reject client
            # business payloads. There is no task/control injection path.
            async def receive():
                incoming = await websocket.receive()
                if incoming['type'] == 'websocket.receive':
                    await websocket.close(code=1008, reason='Read-only stream')
            receiver = asyncio.create_task(receive())
            while not receiver.done():
                message = await asyncio.to_thread(mailbox.get)
                if mailbox.closed:
                    await websocket.close(code=1013, reason='Resynchronize with a new snapshot')
                    break
                if message is not None:
                    await asyncio.wait_for(websocket.send_text(message), timeout=5)
        except (WebSocketDisconnect, RuntimeError, TimeoutError):
            pass
        finally:
            if receiver is not None:
                receiver.cancel()
                await asyncio.gather(receiver, return_exceptions=True)
            if mailbox is not None:
                gateway.publication.unsubscribe(mailbox)

    return app


async def run(args):
    config = json.loads((args.root / 'config/g4-gateway.json').read_text(encoding='utf-8-sig'))
    gateway = Gateway(args.root, args.manifest, args.manifest_sha256, args.output, config)
    server = uvicorn.Server(uvicorn.Config(application(gateway), host=config['host'], port=config['port'],
                                         access_log=False, ws='websockets', ws_max_size=4096,
                                         ws_max_queue=4, timeout_graceful_shutdown=10))
    async def stop_requested():
        while not server.should_exit:
            if (args.output / 'request-stop').exists():
                server.should_exit = True
                return
            await asyncio.sleep(0.1)
    watcher = asyncio.create_task(stop_requested())
    try:
        await server.serve()
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)
    return 0 if gateway.error is None else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    return asyncio.run(run(parser.parse_args()))


if __name__ == '__main__':
    sys.exit(main())
