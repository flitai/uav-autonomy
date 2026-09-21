"""Isolated G4-v1 wire fixture, never connected to AMASE/UxAS."""
import asyncio
from http import HTTPStatus
import importlib.util
import json
from pathlib import Path
import sys
from websockets.asyncio.server import serve

spec=importlib.util.spec_from_file_location('mission_fixture_data',Path(__file__).with_name('fixtures.py'));f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
async def main(directory):
    snapshot=f.snapshot();clients=set();sequence=int(snapshot['sequence'])
    def health():return {k:v for k,v in snapshot.items() if k not in ('kind','state')}|dict(kind='health',status='live',ready=True,freshness=dict(paused=True,stale=False),connections={})
    async def process(connection,request):
        if request.path=='/api/v1/stream':return None
        value=health() if request.path=='/api/v1/health' else snapshot
        return connection.respond(HTTPStatus.OK,json.dumps(value))
    async def client(ws):
        clients.add(ws)
        try:await ws.send(json.dumps(snapshot));await ws.wait_closed()
        finally:clients.remove(ws)
    async with serve(client,'127.0.0.1',8000,process_request=process,max_size=8*1024*1024) as server:
        (directory/'ready.json').write_text(json.dumps(dict(fixture=True,scope='independent G4-v1 regions',port=8000)),encoding='utf-8')
        deleted=False
        while not (directory/'request-stop').exists():
            if not deleted and (directory/'delete-regions').exists():
                changes=[dict(collection='zones',id=k,op='delete') for k in snapshot['state']['zones']]
                snapshot['state']['zones']={};sequence+=1;snapshot['sequence']=str(sequence)
                delta={k:v for k,v in snapshot.items() if k not in ('kind','state')}|dict(kind='delta',changes=changes)
                for ws in list(clients):await ws.send(json.dumps(delta))
                (directory/'delta.json').write_text(json.dumps(delta),encoding='utf-8');deleted=True
            await asyncio.sleep(.1)
        for ws in list(clients):await ws.close(code=1000)
if __name__=='__main__':asyncio.run(main(Path(sys.argv[1])))
