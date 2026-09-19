"""Three real browser protocol consumers reconnect throughout injected faults."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import time

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake


async def watch(url, output, run_id):
    output.mkdir()
    results = []
    async def client(index):
        result = {'client': index, 'snapshots': 0, 'deltas': 0, 'disconnects': 0, 'health_frames': 0, 'streams': []}
        state = None
        with (output / ('client-' + str(index) + '.jsonl')).open('w', encoding='utf-8') as log:
            while not (output / 'request-stop').exists():
                try:
                    async with connect(url.replace('http:', 'ws:') + '/api/v1/stream', max_size=8388608,
                                       max_queue=4, open_timeout=3, close_timeout=3) as socket:
                        state, sequence, stream_id = None, None, None
                        refreshed_at = time.monotonic()
                        while not (output / 'request-stop').exists():
                            try: packet = json.loads(await asyncio.wait_for(socket.recv(), .5))
                            except TimeoutError: continue
                            assert packet['run_id'] == run_id
                            if packet['kind'] == 'health':
                                assert state is None and not packet['ready']
                                result['health_frames'] += 1
                                continue
                            if state is None:
                                assert packet['kind'] == 'snapshot' and isinstance(packet['sequence'], str)
                                state, sequence, stream_id = packet['state'], int(packet['sequence']), packet['stream_id']
                                result['snapshots'] += 1
                                if stream_id not in result['streams']: result['streams'].append(stream_id)
                                assert len(result['streams']) <= 256
                                log.write(json.dumps(dict(stream=stream_id, sequence=str(sequence), kind='snapshot')) + '\n'); log.flush()
                            else:
                                assert packet['kind'] == 'delta' and packet['stream_id'] == stream_id
                                assert isinstance(packet['sequence'], str) and int(packet['sequence']) == sequence + 1
                                for change in packet['changes']:
                                    if change['collection'] == 'simulation': state['simulation'] = change['value']
                                    elif change['op'] == 'delete': state[change['collection']].pop(change['id'], None)
                                    else: state[change['collection']][change['id']] = change['value']
                                sequence += 1; result['deltas'] += 1
                            if index == 1 and time.monotonic() - refreshed_at >= 10: break
                            if index == 2: await asyncio.sleep(.15)
                except (ConnectionClosed, OSError, InvalidHandshake):
                    result['disconnects'] += 1
                await asyncio.sleep(.2)
        result['last_state_sha256'] = hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()
        assert result['snapshots'] >= 3 and len(result['streams']) >= 3 and result['deltas'] > 0, result
        results.append(result)
    await asyncio.gather(*(client(index) for index in range(3)))
    (output / 'result.json').write_text(json.dumps({'status':'passed', 'clients':results}, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--url', required=True); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--run-id', required=True); args = parser.parse_args()
    asyncio.run(watch(args.url, args.output, args.run_id))
