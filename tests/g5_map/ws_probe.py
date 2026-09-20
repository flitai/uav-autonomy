"""Assert the map proxy preserves uint64 strings and WebSocket close 1013."""
import asyncio
import json
from pathlib import Path
import sys
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed


async def main(url,output):
    async with connect(url) as socket:
        message=json.loads(await socket.recv())
        assert message=={'fixture':True,'sequence':'9223372036854775807'}
        try:await socket.recv()
        except ConnectionClosed as error:assert error.rcvd.code==1013
        else:raise AssertionError('Missing recovery close')
    Path(output).write_text(json.dumps(dict(status='passed',fixture=True,closeCode=1013,message=message),indent=2)+'\n')


if __name__=='__main__':asyncio.run(main(sys.argv[1],sys.argv[2]))
