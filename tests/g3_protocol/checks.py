"""Strict decoding counterexamples derived from actual Java/C++ captured frames."""
import struct


def malformed(wire, packet):
    reader = wire.sentinel.SentinelReader()
    body = reader.feed(packet)[0]['body']
    first, second = body.index(b'$'), body.index(b'$', body.index(b'$')+1)
    prefix, raw = body[:second+1], body[second+1:]

    def raw_frame(value):
        return wire.envelope(prefix + value)

    def repaired(value):
        return value[:-4] + struct.pack('>I', sum(value[:-4]) & 0xffffffff)

    outer_checksum = packet[:packet.index(wire.sentinel.CHECK)+8]+b'0'+wire.sentinel.END
    wrong_length = wire.sentinel.START+str(len(body)+1).encode()+wire.sentinel.BODY+body+wire.sentinel.CHECK+b'0'+wire.sentinel.END
    bad_size = raw[:4]+struct.pack('>I', len(raw))+raw[8:]
    bad_root = raw[:8]+b'\x00'+raw[9:]
    bad_magic = b'FAIL'+raw[4:]
    fields = body[first+1:second].split(b'|'); fields[1] = b'afrl.cmasi.NotTheType'
    return {'outer-checksum': outer_checksum, 'outer-length': wrong_length,
            'oversized-length': wire.sentinel.START+b'1048577'+wire.sentinel.BODY,
            'inner-checksum': raw_frame(raw[:-4]+b'\x00\x00\x00\x00'),
            'inner-length': raw_frame(repaired(bad_size)), 'root-flag': raw_frame(repaired(bad_root)),
            'magic': raw_frame(repaired(bad_magic)),
            'descriptor': wire.envelope(body[:first+1]+b'|'.join(fields)+b'$'+raw),
            'attributes': wire.envelope(b'address$lmcp|too|short$'+raw),
            'trailing-lmcp': raw_frame(repaired(raw[:-4]+b'\x00\x00\x00\x00\x00'))}


def run(wire, factory, samples, directory):
    results = []
    for direction, packet in samples.items():
        expected, tail = wire.decode(packet, factory)
        assert len(expected) == 1 and not tail
        for split in range(1, len(packet)):
            reader = wire.sentinel.SentinelReader()
            frames = reader.feed(packet[:split])+reader.feed(packet[split:])
            reader.eof()
            assert len(frames) == 1 and frames[0]['wire'] == packet
            wire.sentinel.Decoder(factory).decode(frames[0])
        rows, tail = wire.decode(packet+packet, factory)
        assert len(rows) == 2 and not tail
        for end in range(1, len(packet)):
            reader = wire.sentinel.SentinelReader(); reader.feed(packet[:end])
            try:
                reader.eof()
                raise AssertionError('Partial frame accepted at EOF')
            except wire.sentinel.ProtocolError:
                pass
            clean = wire.sentinel.SentinelReader()
            assert len(clean.feed(packet)) == 1
            clean.eof()
        faults = malformed(wire, packet)
        for name, value in faults.items():
            (directory/(direction+'-'+name+'.bin')).write_bytes(value)
            try:
                rows, tail = wire.decode(value, factory)
                if tail:
                    raise wire.sentinel.ProtocolError('Truncated malformed input')
                raise AssertionError('Malformed message accepted: '+name)
            except wire.sentinel.ProtocolError:
                pass
        results.append(dict(direction=direction, status='passed', splitPositions=len(packet)-1,
                            coalescedFrames=2, truncatedPositions=len(packet)-1, malformed=list(faults)))
    return results
