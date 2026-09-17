"""Protocol and receiver fault checks. Synthetic peers are never real AMASE evidence."""
import json
from pathlib import Path
import random
import socket
import struct
import threading

import amase_tcp as c
from sentinel import Decoder, SentinelReader, Statistics, MAX_BODY, require


def wrap(raw, name='afrl.cmasi.AirVehicleState'):
    addressed = (name + '$lmcp|' + name + '||0|0$').encode('ascii') + raw
    return b'+=+=+=+=' + str(len(addressed)).encode() + b'#@#@#@#@' + addressed + b'!%!%!%!%' + str(sum(addressed)).encode() + b'?^?^?^?^'


def fix_checksum(raw):
    return raw[:-4] + struct.pack('>I', sum(raw[:-4]) & 0xffffffff)


def rows(data, factory, chunks):
    reader, decoder, output = SentinelReader(), Decoder(factory), []
    start = 0
    for length in chunks:
        output.extend(decoder.decode(f)[0] for f in reader.feed(data[start:start + length]))
        start += length
    require(start == len(data), 'Replay chunks do not cover input')
    reader.eof()
    return output


def replay(directory, factory):
    result = c.load(directory / 'capture-result.json')
    original = (directory / 'capture.bin').read_bytes()
    data = original[:result['verifiedFrameBytes']]
    expected = [json.loads(line) for line in (directory / 'decoded.jsonl').read_text(encoding='utf-8').splitlines()]
    expected = [{k:v for k,v in row.items() if k not in ('index','receivedAt','offset','length')} for row in expected]
    splits = {'one-byte': [1] * len(data), 'coalesced': [len(data)]}
    rng, left, random_sizes = random.Random(20260917), len(data), []
    while left:
        size = min(left, rng.randint(1,4096)); random_sizes.append(size); left -= size
    splits['seeded-random'] = random_sizes
    boundaries = {0, len(data)}
    for line in (directory / 'frames.jsonl').read_text(encoding='utf-8').splitlines():
        frame = json.loads(line)
        for relative in (1,7,8,9,16,17,frame['length']-9,frame['length']-1,frame['length']):
            boundaries.add(min(len(data),frame['offset'] + relative))
    ordered = sorted(boundaries)
    splits['boundary-splits'] = [b-a for a,b in zip(ordered,ordered[1:])]
    for name, chunks in splits.items():
        require(rows(data,factory,chunks) == expected, 'Replay differs: ' + name)
    return dict(status='passed',frames=len(expected),bytes=len(data),patterns=list(splits),captureSha256=c.sha(directory / 'capture.bin'))


def run_checks(directory, factory):
    from afrl.cmasi.AirVehicleState import AirVehicleState
    from afrl.cmasi.Location3D import Location3D
    from afrl.cmasi.SessionStatus import SessionStatus
    directory.mkdir(parents=True)
    cases = []
    def case(name, action, error=None):
        try:
            value = action()
        except (ValueError, RuntimeError, OSError) as caught:
            require(error is not None and error in str(caught), 'Unexpected failure for ' + name + ': ' + str(caught))
            cases.append(dict(name=name,status='passed',expectedFailure=str(caught)))
        else:
            require(error is None, 'Expected failure not raised: ' + name)
            cases.append(dict(name=name,status='passed',evidence=value))

    vehicle = AirVehicleState(); vehicle.ID = 9007199254740993; vehicle.Time = 1234567890123
    vehicle.Location = Location3D(); vehicle.Location.Latitude = 34.25; vehicle.Location.Longitude = -117.5
    vehicle.Location.Altitude = 1234.5; vehicle.Location.AltitudeType = 1
    raw = bytes(factory.packMessage(vehicle,True)); valid = wrap(raw)
    def decode(data): return rows(data,factory,[len(data)])
    def wide():
        decoded = decode(valid)[0]
        require(decoded['id'] == '9007199254740993' and decoded['timeMs'] == '1234567890123','int64 precision lost')
        return dict(id=decoded['id'],timeMs=decoded['timeMs'],source='synthetic')
    case('int64-precision',wide)
    case('outer-marker',lambda:decode(b'x'+valid[1:]),'Invalid Sentinel marker')
    case('outer-checksum',lambda:decode(valid.replace(b'!%!%!%!%',b'!%!%!%!%1',1)),'Sentinel checksum mismatch')
    case('oversize-length',lambda:decode(b'+=+=+=+='+str(MAX_BODY+1).encode()+b'#@#@#@#@'),'outside limits')
    case('decimal-limit',lambda:decode(b'+=+=+=+=12345678'),'decimal field too long')
    case('truncated-frame',lambda:decode(valid[:-1]),'Truncated Sentinel')
    case('inner-checksum',lambda:decode(wrap(raw[:-1]+bytes([raw[-1]^1]))),'LMCP checksum mismatch')
    case('zero-inner-checksum',lambda:decode(wrap(raw[:-4]+b'\0'*4)),'LMCP checksum mismatch')
    case('inner-length',lambda:decode(wrap(raw[:4]+struct.pack('>I',1)+raw[8:])),'LMCP length mismatch')
    case('root-flag',lambda:decode(wrap(raw[:8]+b'\0'+raw[9:])),'Invalid root object')
    case('unknown-version',lambda:decode(wrap(fix_checksum(raw[:21]+b'\xff\xff'+raw[23:]))),'Unknown LMCP')
    case('unknown-series',lambda:decode(wrap(fix_checksum(raw[:9]+b'\xff'*8+raw[17:]))),'Unknown LMCP')
    case('attribute-type',lambda:decode(wrap(raw,'afrl.cmasi.SessionStatus')),'Attribute type differs')
    case('attribute-limit',lambda:decode(wrap(raw,'x'*4100)),'oversized addressed attributes')
    case('body-trailing-bytes',lambda:decode(wrap(fix_checksum(raw[:-4]+b'x'+raw[-4:]))),'LMCP length mismatch')

    def fixture_stream(moving=True, advancing=True, only_one=False):
        packets=[]
        for i in range(12):
            for entity in ((400,) if only_one else (400,500)):
                vehicle.ID=entity; vehicle.Time=i*1000 if advancing else 0
                vehicle.Location.Latitude=34.25+i/1024 if moving else 34.25
                packets.append(wrap(bytes(factory.packMessage(vehicle,True))))
            session=SessionStatus(); session.State=1; session.ScenarioTime=i*1000 if advancing else 0
            packets.append(wrap(bytes(factory.packMessage(session,True)),'afrl.cmasi.SessionStatus'))
        return b''.join(packets)

    def socket_case(name, data, eof=False):
        out=directory/name; out.mkdir()
        stop=threading.Event(); errors=[]
        with socket.socket() as server:
            server.bind(('127.0.0.1',0)); server.listen(1); server.settimeout(2)
            def peer():
                try:
                    with server.accept()[0] as accepted:
                        if data: accepted.sendall(data)
                        if not eof: stop.wait(2)
                except OSError as error:
                    errors.append(str(error))
            worker=threading.Thread(target=peer); worker.start()
            try:
                with c.connect(server.getsockname()[1],.5) as sock:
                    result=c.capture(sock,out,factory,minimum=.05,maximum=.25)
                return dict(status=result['status'],source='synthetic')
            finally:
                stop.set(); worker.join(3)
                require(not worker.is_alive() and not errors, 'Fixture peer did not stop cleanly')
    case('synthetic-loopback-success',lambda:socket_case('success',fixture_stream()))
    case('no-data',lambda:socket_case('no-data',b''),'Receive deadline')
    case('insufficient-entities',lambda:socket_case('insufficient',fixture_stream(only_one=True)),'Receive deadline')
    case('time-stalled',lambda:socket_case('time-stalled',fixture_stream(advancing=False)),'Receive deadline')
    case('position-stalled',lambda:socket_case('position-stalled',fixture_stream(moving=False)),'Receive deadline')
    case('early-eof',lambda:socket_case('early-eof',b'',True),'Early EOF')
    case('partial-eof',lambda:socket_case('partial-eof',valid[:-1],True),'Truncated Sentinel')
    def refused():
        with socket.socket() as reserved:
            reserved.bind(('127.0.0.1',0))
            with c.connect(reserved.getsockname()[1],.2): pass
    case('connection-refused',refused,'Connection deadline')
    def regression():
        stats=Statistics()
        sample=decode(valid)[0]; sample['id']='400'; stats.add(sample)
        stats.add(dict(sample,timeMs='0'))
    case('time-regression',regression,'Source time regressed')
    c.save(directory/'result.json',dict(status='passed',source='synthetic',cases=cases))
    return cases
