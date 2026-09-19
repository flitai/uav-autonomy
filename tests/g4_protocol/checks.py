"""Protocol checks use real qualified G3 frames plus isolated malformed derivatives."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value


def verify(root, directory):
    sys.path.insert(0, str(root / 'src'))
    from sim_bridge import codec
    schema = codec.load_schema(root)
    decoder = codec.Decoder(schema)
    source = root / 'out/runs/g3-t07-test-20260919-173116-474/headless'
    samples = {}
    counts = {}
    for name in ('amase', 'observer'):
        reader = codec.SentinelReader(); total = 0
        with (source / (name + '.bin')).open('rb') as stream:
            while chunk := stream.read(65536):
                for frame in reader.feed(chunk):
                    obj = decoder.decode(frame)
                    codec.check_source(obj, 'uxas' if name == 'observer' else name, {'400', '500'})
                    total += 1
                    if obj.descriptor == 'afrl.cmasi.AirVehicleState':
                        assert isinstance(obj.fields['ID'], str) and isinstance(obj.fields['Time'], str)
                        samples.setdefault('state', frame['wire'])
                    if obj.descriptor == 'afrl.cmasi.MissionCommand':
                        samples.setdefault('command', frame['wire'])
        reader.eof(); counts[name] = total
    legacy = load('g4_legacy_wire', root / 'scripts/g3_protocol/wire.py')
    negative = load('g4_legacy_faults', root / 'tests/g3_protocol/checks.py')
    failures = []
    for kind, packet in samples.items():
        for split in range(1, len(packet)):
            reader = codec.SentinelReader()
            frames = reader.feed(packet[:split]) + reader.feed(packet[split:])
            reader.eof()
            assert len(frames) == 1 and frames[0]['wire'] == packet
        reader = codec.SentinelReader()
        assert len(reader.feed(packet + packet)) == 2
        for label, raw in negative.malformed(legacy, packet).items():
            try:
                reader = codec.SentinelReader()
                for frame in reader.feed(raw):
                    decoder.decode(frame)
                reader.eof()
            except codec.ProtocolError:
                failures.append(kind + ':' + label)
            else:
                raise AssertionError('Invalid frame accepted: ' + label)
        reader = codec.SentinelReader(); reader.feed(packet[:-1])
        try:
            reader.eof()
        except codec.ProtocolError:
            pass
        else:
            raise AssertionError('Truncated EOF accepted')
    # Repaired outer and inner checksums cannot legitimize an unknown root type.
    frame = codec.SentinelReader().feed(samples['state'])[0]
    decoded = decoder.decode(frame)
    prefix = frame['body'][:-len(decoded.raw)]
    raw = bytearray(decoded.raw)
    struct.pack_into('>I', raw, 17, 4294967295)
    struct.pack_into('>I', raw, len(raw) - 4, sum(raw[:-4]) & 0xffffffff)
    try:
        decoder.decode(codec.SentinelReader().feed(codec.envelope(prefix + raw))[0])
    except codec.ProtocolError:
        failures.append('unknown-type-with-valid-checksums')
    else:
        raise AssertionError('Unknown LMCP type accepted')
    from afrl.cmasi.AirVehicleState import AirVehicleState
    from afrl.cmasi.Location3D import Location3D
    from lmcp import LMCPFactory
    obj = AirVehicleState(); obj.ID = 2**63 - 1; obj.Time = 2**53 + 1; obj.Location = Location3D()
    def encoded(obj):
        raw = LMCPFactory.packMessage(obj, True)
        body = (obj.FULL_LMCP_TYPE_NAME + '$lmcp|' + obj.FULL_LMCP_TYPE_NAME + '||0|0$').encode() + raw
        return codec.SentinelReader().feed(codec.envelope(body))[0]
    values = decoder.decode(encoded(obj)).fields
    assert values['ID'] == str(2**63 - 1) and values['Time'] == str(2**53 + 1)
    for value in (float('nan'), float('inf'), 91):
        obj.Location.Latitude = value
        try:
            decoder.decode(encoded(obj))
        except codec.ProtocolError:
            failures.append('invalid-latitude-' + str(value))
        else:
            raise AssertionError('Invalid latitude accepted')
    obj.Location.Latitude = 0
    message = decoder.decode(encoded(obj))
    try:
        codec.check_source(message, 'amase', {'400', '500'})
    except codec.ProtocolError:
        failures.append('unknown-business-entity')
    else:
        raise AssertionError('Unconfigured entity accepted')
    result = {'status': 'passed', 'historicalFrames': counts, 'modelTypes': len(schema.structs),
              'sampleSHA256': {k: hashlib.sha256(v).hexdigest() for k, v in samples.items()},
              'negativeChecks': failures, 'allSplitPositions': {k: len(v)-1 for k,v in samples.items()},
              'int64Strings': True, 'liveNetworkValidated': False}
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'checks.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[2]
    print(verify(root, root / 'out/tmp/g4-protocol-diagnostic'))
