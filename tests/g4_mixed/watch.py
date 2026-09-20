"""Three continuous consumers acknowledge the exact paused final boundary."""
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
        finished = False
        with (output / ('client-' + str(index) + '.jsonl')).open('w', encoding='utf-8') as log:
            while not finished and not (output / 'request-stop').exists():
                try:
                    async with connect(url.replace('http:', 'ws:') + '/api/v1/stream', max_size=8388608,
                                       max_queue=4, open_timeout=3, close_timeout=3) as socket:
                        state, sequence, stream_id = None, None, None
                        refreshed_at = time.monotonic()
                        while not (output / 'request-stop').exists():
                            final_path=output/'expected-final.json'
                            if state is not None and final_path.is_file():
                                target=json.loads(final_path.read_text(encoding='utf-8'))
                                assert target['run_id']==run_id
                                digest=hashlib.sha256(json.dumps(state,sort_keys=True).encode()).hexdigest()
                                if str(sequence)==target['sequence'] and digest==target['state_sha256']:
                                    temporary=output/('final-'+str(index)+'.tmp')
                                    temporary.write_text(json.dumps(target),encoding='utf-8')
                                    temporary.replace(output/('final-'+str(index)+'.json'))
                                    result['final_boundary_acknowledged']=True; finished=True; break
                                # G4 reconnects with a new snapshot, not history
                                # replay. Close the lagging read-only client and
                                # explicitly record its final resynchronization.
                                assert result.get('final_resynchronizations',0)<3, result
                                result['final_resynchronizations']=result.get('final_resynchronizations',0)+1
                                break
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
        assert result.get('final_boundary_acknowledged'), result
        results.append(result)
    await asyncio.gather(*(client(index) for index in range(3)))
    (output / 'result.json').write_text(json.dumps({'status':'passed', 'clients':results}, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--url', required=True); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--run-id', required=True); args = parser.parse_args()
    asyncio.run(watch(args.url, args.output, args.run_id))
