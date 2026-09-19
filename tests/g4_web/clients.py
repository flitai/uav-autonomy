"""Real HTTP/WebSocket clients reconstruct a common live snapshot boundary."""
import argparse
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed


def request(url, method='GET'):
    try:
        with urlopen(Request(url, method=method), timeout=5) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()


async def verify(url, output):
    sockets, snapshots = [], []
    ws_url = url.replace('http:', 'ws:') + '/api/v1/stream'
    try:
        status, data = request(url + '/api/v1/health'); health = json.loads(data)
        assert status == 200 and health['ready'] and health['status'] == 'live'
        assert set(health['initialization']['dynamic_entity_ids']) == {'400', '500'}
        assert request(url + '/api/v1/snapshot', 'POST')[0] == 405
        status, html = request(url + '/'); assert status == 200 and '仿真状态诊断'.encode() in html
        for index in range(3):
            socket = await connect(ws_url, max_size=8388608, max_queue=256)
            sockets.append(socket)
            snapshot = json.loads(await asyncio.wait_for(socket.recv(), 5))
            assert snapshot['kind'] == 'snapshot' and isinstance(snapshot['sequence'], str)
            snapshots.append(snapshot)
            await asyncio.sleep(0.2)  # Intentionally different join times, not a backend readiness barrier.
        status, data = request(url + '/api/v1/snapshot'); target = json.loads(data)
        assert status == 200 and target['state']['tasks']['1000']['initialized']
        results = []
        for socket, snapshot in zip(sockets, snapshots):
            state = deepcopy(snapshot['state']); sequence = int(snapshot['sequence']); deltas = 0
            assert snapshot['run_id'] == target['run_id'] and snapshot['stream_id'] == target['stream_id']
            while sequence < int(target['sequence']):
                message = json.loads(await asyncio.wait_for(socket.recv(), 5))
                assert message['kind'] == 'delta' and int(message['sequence']) == sequence + 1
                for change in message['changes']:
                    if change['collection'] == 'simulation': state['simulation'] = change['value']
                    elif change['op'] == 'delete': state[change['collection']].pop(change['id'], None)
                    else: state[change['collection']][change['id']] = change['value']
                sequence += 1; deltas += 1
            assert state == target['state'], 'Clients differ at the same sequence'
            results.append({'initial_sequence': snapshot['sequence'], 'target_sequence': str(sequence), 'deltas': deltas})
        await sockets[0].close()
        async with connect(ws_url, max_size=8388608) as refreshed:
            new_snapshot = json.loads(await asyncio.wait_for(refreshed.recv(), 5))
            assert new_snapshot['kind'] == 'snapshot' and int(new_snapshot['sequence']) >= int(target['sequence'])
        async with connect(ws_url, max_size=8388608) as forbidden:
            await forbidden.recv(); await forbidden.send('{"control":"pause"}')
            try:
                while True: await asyncio.wait_for(forbidden.recv(), 5)
            except ConnectionClosed as closed:
                assert closed.rcvd and closed.rcvd.code == 1008
        result = {'status': 'passed', 'run_id': target['run_id'], 'stream_id': target['stream_id'],
                  'clients': results, 'refreshSnapshot': True, 'httpMutationRefused': True, 'websocketMutationRefused': True,
                  'snapshot': target}
        output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print('Three real clients, late join, refresh and read-only refusal passed', flush=True)
    finally:
        await asyncio.gather(*(socket.close() for socket in sockets), return_exceptions=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--url', required=True); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); asyncio.run(verify(args.url, args.output))
