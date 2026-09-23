"""One real read-only WebSocket client that deliberately does not consume frames."""
import asyncio
import json
from pathlib import Path
import sys
import time

from websockets.asyncio.client import connect


async def main(path):
    started=time.monotonic()
    async with connect('ws://127.0.0.1:8000/api/v1/stream', max_queue=1) as stream:
        await asyncio.sleep(7)
        await stream.close()
    path.write_text(json.dumps({'status':'passed','readFrames':0,'durationSeconds':time.monotonic()-started}),encoding='utf-8')


if __name__=='__main__':asyncio.run(main(Path(sys.argv[1])))
