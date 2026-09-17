"""Strict incremental reader for the Sentinel framing emitted by AMASE's Java factory."""
import math
import struct

START = b'+=+=+=+='
BODY = b'#@#@#@#@'
CHECK = b'!%!%!%!%'
END = b'?^?^?^?^'
MAX_BODY = 1024 * 1024
MAX_ATTRIBUTES = 4096


class ProtocolError(ValueError):
    pass


def require(value, message):
    if not value:
        raise ProtocolError(message)


class SentinelReader:
    def __init__(self):
        self.buffer = bytearray()
        self.offset = 0

    def _marker(self, position, marker):
        available = self.buffer[position:position + len(marker)]
        require(marker.startswith(available), 'Invalid Sentinel marker at ' + str(self.offset + position))
        return len(available) == len(marker)

    def _decimal(self, position, delimiter, digits):
        start = position
        while position < len(self.buffer) and 48 <= self.buffer[position] <= 57:
            position += 1
            require(position - start <= digits, 'Sentinel decimal field too long')
        if position == len(self.buffer):
            return None
        require(position > start, 'Missing Sentinel decimal field')
        if not self._marker(position, delimiter):
            return None
        return int(self.buffer[start:position]), position + len(delimiter)

    def feed(self, chunk):
        # The socket reader limits each chunk to 64 KiB; replay can submit many complete frames.
        frames = []
        for start in range(0, len(chunk), 65536):
            self.buffer.extend(chunk[start:start + 65536])
            while self.buffer:
                if not self._marker(0, START):
                    break
                header = self._decimal(len(START), BODY, 7)
                if header is None:
                    break
                size, body_start = header
                require(27 <= size <= MAX_BODY, 'Sentinel body length outside limits')
                body_end = body_start + size
                if len(self.buffer) < body_end:
                    break
                if not self._marker(body_end, CHECK):
                    break
                footer = self._decimal(body_end + len(CHECK), END, 10)
                if footer is None:
                    break
                checksum, stop = footer
                addressed = bytes(self.buffer[body_start:body_end])
                require(checksum == sum(addressed), 'Sentinel checksum mismatch')
                frames.append(dict(offset=self.offset, length=stop, wire=bytes(self.buffer[:stop]), body=addressed))
                del self.buffer[:stop]
                self.offset += stop
            require(len(self.buffer) <= MAX_BODY + 80, 'Sentinel buffer limit exceeded')
        return frames

    def eof(self):
        require(not self.buffer, 'Truncated Sentinel frame at EOF')


class Decoder:
    def __init__(self, factory_module):
        self.factory = factory_module.LMCPFactory()

    def decode(self, frame):
        body = frame['body']
        first = body.find(b'$', 0, MAX_ATTRIBUTES + 1)
        second = body.find(b'$', first + 1, MAX_ATTRIBUTES + 1) if first >= 0 else -1
        require(first > 0 and second > first, 'Missing or oversized addressed attributes')
        try:
            address = body[:first].decode('ascii')
            attributes = body[first + 1:second].decode('ascii')
        except UnicodeDecodeError as error:
            raise ProtocolError('Non-ASCII addressed attributes') from error
        fields = attributes.split('|')
        require(len(fields) == 5 and fields[0] == 'lmcp', 'Invalid LMCP attributes')
        raw = body[second + 1:]
        require(len(raw) >= 27 and raw[:4] == b'LMCP', 'Invalid LMCP header')
        size = struct.unpack_from('>I', raw, 4)[0]
        require(size >= 15 and len(raw) == size + 12, 'LMCP length mismatch')
        require(raw[8] == 1, 'Invalid root object flag')
        require(struct.unpack_from('>I', raw, len(raw) - 4)[0] == sum(raw[:-4]) & 0xffffffff,
                'LMCP checksum mismatch')
        series, kind, version = struct.unpack_from('>qIH', raw, 9)
        try:
            obj = self.factory.createObject(series, version, kind)
            require(obj is not None, 'Unknown LMCP series/type/version')
            consumed = obj.unpack(raw, 23)
            require(consumed == len(raw) - 4, 'LMCP decoded length mismatch')
            require(fields[1] == obj.FULL_LMCP_TYPE_NAME, 'Attribute type differs from LMCP type')
            row = dict(type=obj.FULL_LMCP_TYPE_NAME, series=obj.SERIES_NAME, version=version, typeId=kind,
                       address=address, attributes=attributes,
                       sourceGroup=fields[2], sourceEntity=fields[3], sourceService=fields[4])
            if row['type'] == 'afrl.cmasi.AirVehicleState':
                p = obj.Location
                require(p is not None, 'Missing state location')
                require(all(math.isfinite(v) for v in (p.Latitude, p.Longitude, p.Altitude)), 'Non-finite location')
                require(-90 <= p.Latitude <= 90 and -180 <= p.Longitude <= 180, 'Location outside geographic range')
                row.update(id=str(obj.ID), timeMs=str(obj.Time), latitude=p.Latitude, longitude=p.Longitude,
                           altitude=p.Altitude, altitudeType=p.AltitudeType)
            elif row['type'] == 'afrl.cmasi.SessionStatus':
                row.update(timeMs=str(obj.ScenarioTime), startTimeMs=str(obj.StartTime), state=obj.State,
                           realTimeMultiple=obj.RealTimeMultiple)
            return row, raw
        except ProtocolError:
            raise
        except Exception as error:
            raise ProtocolError('LMCP decode failed: ' + str(error)) from error


class Statistics:
    def __init__(self):
        self.types = {}
        self.entities = {}
        self.session = dict(count=0)

    @staticmethod
    def advance(item, row, entity=False):
        if item['count']:
            require(int(row['timeMs']) >= int(item['last']['timeMs']), 'Source time regressed')
        else:
            item['first'] = row
        item['last'] = row
        item['count'] += 1
        if entity:
            item['moved'] = item.get('moved', False) or any(row[k] != item['first'][k] for k in ('latitude', 'longitude'))

    def add(self, row):
        name = row['type']
        self.types[name] = self.types.get(name, 0) + 1
        if name == 'afrl.cmasi.AirVehicleState' and row['id'] in ('400', '500'):
            self.advance(self.entities.setdefault(row['id'], dict(count=0)), row, True)
        elif name == 'afrl.cmasi.SessionStatus':
            self.advance(self.session, row)

    def complete(self):
        items = [self.entities.get(key, dict(count=0)) for key in ('400', '500')] + [self.session]
        return (all(i['count'] >= 10 and int(i['last']['timeMs']) > int(i['first']['timeMs']) for i in items)
                and all(i.get('moved') for i in items[:2]))

    def summary(self):
        return dict(types=self.types, entities=self.entities, session=self.session)
