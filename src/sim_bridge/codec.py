"""Strict Sentinel/LMCP ingress; generated classes remain untouched.

The incremental envelope rules match scripts/validation/sentinel.py. The MDM-driven
preflight bounds arrays and nesting before calling generated object unpackers.
"""
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import sys
import xml.etree.ElementTree as ET

START, BODY, CHECK, END = b'+=+=+=+=', b'#@#@#@#@', b'!%!%!%!%', b'?^?^?^?^'
MAX_BODY, MAX_ATTRIBUTES = 1048576, 4096
PRIMITIVES = {'byte': '>B', 'char': '>c', 'int8': '>b', 'uint8': '>B', 'int16': '>h', 'uint16': '>H', 'int32': '>i', 'uint32': '>I',
              'int64': '>q', 'uint64': '>Q', 'real32': '>f', 'real64': '>d', 'bool': '>B'}


class ProtocolError(ValueError):
    pass


def require(value, message):
    if not value:
        raise ProtocolError(message)


class SentinelReader:
    def __init__(self):
        self.buffer = bytearray()
        self.offset = 0

    def marker(self, position, marker):
        available = self.buffer[position:position + len(marker)]
        require(marker.startswith(available), 'Invalid Sentinel marker at ' + str(self.offset + position))
        return len(available) == len(marker)

    def decimal(self, position, delimiter, digits):
        start = position
        while position < len(self.buffer) and 48 <= self.buffer[position] <= 57:
            position += 1
            require(position - start <= digits, 'Sentinel decimal field too long')
        if position == len(self.buffer):
            return None
        require(position > start, 'Missing Sentinel decimal field')
        if not self.marker(position, delimiter):
            return None
        return int(self.buffer[start:position]), position + len(delimiter)

    def feed(self, chunk):
        require(len(chunk) <= 65536, 'Read chunk exceeds 64 KiB')
        self.buffer.extend(chunk)
        frames = []
        while self.buffer:
            if not self.marker(0, START):
                break
            header = self.decimal(len(START), BODY, 7)
            if header is None:
                break
            size, begin = header
            require(27 <= size <= MAX_BODY, 'Sentinel body length outside limits')
            stop = begin + size
            if len(self.buffer) < stop or not self.marker(stop, CHECK):
                break
            footer = self.decimal(stop + len(CHECK), END, 10)
            if footer is None:
                break
            checksum, finish = footer
            body = bytes(self.buffer[begin:stop])
            require(sum(body) == checksum, 'Sentinel checksum mismatch')
            frames.append({'offset': self.offset, 'length': finish, 'body': body, 'wire': bytes(self.buffer[:finish])})
            del self.buffer[:finish]
            self.offset += finish
        require(len(self.buffer) <= MAX_BODY + 80, 'Sentinel buffer limit exceeded')
        return frames

    def eof(self):
        require(not self.buffer, 'Truncated Sentinel frame at EOF')


class Cursor:
    def __init__(self, data, position=0):
        self.data, self.position = data, position

    def read(self, count):
        require(0 <= count <= len(self.data) - self.position, 'Truncated LMCP value')
        begin = self.position
        self.position += count
        return self.data[begin:self.position]

    def value(self, fmt):
        return struct.unpack(fmt, self.read(struct.calcsize(fmt)))[0]


class ModelSchema:
    def __init__(self, root, factory):
        self.factory = factory
        self.structs, self.enums, self.identities, self.enum_values = {}, set(), {}, {}
        lock = json.loads((root / 'config/lmcp-models.json').read_text(encoding='utf-8-sig'))
        for model in lock['models']:
            path = root / 'OpenUxAS/mdms' / model['file']
            require(hashlib.sha256(path.read_bytes()).hexdigest() == model['sha256'].lower(), 'MDM source differs')
            tree = ET.parse(path)
            series = tree.findtext('SeriesName')
            self.enums.update((series, node.get('Name')) for node in tree.findall('EnumList/Enum'))
            for enum in tree.findall('EnumList/Enum'):
                self.enum_values[(series, enum.get('Name'))] = {entry.get('Name') for entry in enum.findall('Entry')}
            for node in tree.findall('StructList/Struct'):
                key = (series, node.get('Name'))
                obj = factory.createObjectByName(*key)
                require(obj is not None, 'Generated type missing: ' + str(key))
                parent = self.type_key(node.get('Extends'), node.get('Series', series)) if node.get('Extends') else None
                fields = [(self.type_key(f.get('Type').removesuffix('[]'), f.get('Series', series)), dict(f.attrib))
                          for f in node.findall('Field')]
                self.structs[key] = {'parent': parent, 'fields': fields, 'descriptor': obj.FULL_LMCP_TYPE_NAME}
                self.identities[(obj.SERIES_NAME_ID, obj.LMCP_TYPE, obj.SERIES_VERSION)] = key

    @staticmethod
    def type_key(name, series):
        return tuple(name.split('/', 1)) if '/' in name else (series, name)

    def fields(self, key):
        definition = self.structs[key]
        return (self.fields(definition['parent']) if definition['parent'] else []) + definition['fields']

    def derived_from(self, actual, expected):
        while actual:
            if actual == expected:
                return True
            actual = self.structs[actual]['parent']
        return False

    def object(self, cursor, expected=None, depth=0):
        require(depth <= 32, 'LMCP nesting limit exceeded')
        valid = cursor.value('>B')
        require(valid in (0, 1), 'Invalid LMCP object flag')
        if not valid:
            return None
        identity = (cursor.value('>q'), cursor.value('>I'), cursor.value('>H'))
        require(identity in self.identities, 'Unknown LMCP series/type/version')
        key = self.identities[identity]
        require(expected is None or self.derived_from(key, expected), 'Nested LMCP type mismatch')
        result = {'_type': self.structs[key]['descriptor']}
        for field_key, field in self.fields(key):
            array = field['Type'].endswith('[]')
            count = cursor.value('>I' if field.get('LargeArray') == 'true' else '>H') if array else 1
            require(count <= int(field.get('MaxArrayLength', 65535)) and count <= 65535, 'LMCP array limit exceeded')
            require(not array or count <= len(cursor.data) - cursor.position, 'Array exceeds remaining frame')
            values = [self.field(cursor, field_key, depth + 1) for _ in range(count)]
            if field.get('Optional') == 'false':
                require(all(value is not None for value in values), 'Required LMCP object is null')
            result[field['Name']] = values if array else values[0]
        if self.derived_from(key, ('CMASI', 'Location3D')):
            require(-90 <= result['Latitude'] <= 90 and -180 <= result['Longitude'] <= 180, 'Invalid geographic location')
        return result

    def field(self, cursor, key, depth):
        kind = key[1]
        if kind in PRIMITIVES:
            value = cursor.value(PRIMITIVES[kind])
            if kind == 'char':
                require(value[0] < 128, 'Unsupported non-ASCII LMCP character')
                return value.decode('ascii')
            if kind.startswith('real'):
                require(math.isfinite(value), 'Non-finite LMCP number')
            if kind == 'bool':
                require(value in (0, 1), 'Invalid LMCP boolean')
                return bool(value)
            return str(value) if kind in ('int64', 'uint64') else value
        if kind == 'string':
            data = cursor.read(cursor.value('>H'))
            try:
                return data.decode('ascii')  # Current generated string contract is ASCII only.
            except UnicodeDecodeError as error:
                raise ProtocolError('Unsupported non-ASCII LMCP business string') from error
        if key in self.enums:
            return cursor.value('>i')
        require(key in self.structs, 'Unknown model field type: ' + str(key))
        return self.object(cursor, key, depth)


@dataclass(frozen=True)
class Decoded:
    descriptor: str
    source_group: str
    source_entity: str
    source_service: str
    address: str
    raw: bytes
    fields: dict

    def metadata(self):
        return {'type': self.descriptor, 'sourceGroup': self.source_group, 'sourceEntity': self.source_entity,
                'sourceService': self.source_service, 'address': self.address,
                'rawSHA256': hashlib.sha256(self.raw).hexdigest(), 'fields': self.fields}


class Decoder:
    def __init__(self, schema):
        self.schema = schema

    def decode(self, frame):
        body = frame['body']
        first = body.find(b'$', 0, MAX_ATTRIBUTES + 1)
        second = body.find(b'$', first + 1, MAX_ATTRIBUTES + 1) if first > 0 else -1
        require(first > 0 and second > first, 'Missing or oversized addressed attributes')
        try:
            address = body[:first].decode('ascii')
            attributes = body[first + 1:second].decode('ascii').split('|')
        except UnicodeDecodeError as error:
            raise ProtocolError('Non-ASCII addressed attributes') from error
        require(len(attributes) == 5 and attributes[0] == 'lmcp', 'Invalid LMCP attributes')
        for value in attributes[3:]:
            require(re.fullmatch(r'[0-9]{1,20}', value) and int(value) < 2**64, 'Invalid routing identity')
        raw = body[second + 1:]
        require(len(raw) >= 27 and raw[:4] == b'LMCP', 'Invalid LMCP header')
        require(struct.unpack_from('>I', raw, 4)[0] + 12 == len(raw), 'LMCP length mismatch')
        require(struct.unpack_from('>I', raw, len(raw) - 4)[0] == sum(raw[:-4]) & 0xffffffff, 'LMCP checksum mismatch')
        cursor = Cursor(raw[:-4], 8)
        values = self.schema.object(cursor)
        require(values is not None and cursor.position == len(raw) - 4, 'LMCP decoded length mismatch')
        require(attributes[1] == values['_type'], 'Attribute type differs from LMCP type')
        # Retain generated decoder compatibility as a second check after bounded preflight.
        series, kind, version = struct.unpack_from('>qIH', raw, 9)
        obj = self.schema.factory.createObject(series, version, kind)
        try:
            require(obj.unpack(raw, 23) == len(raw) - 4, 'Generated decoded length mismatch')
        except Exception as error:
            raise ProtocolError('Generated LMCP decode failed: ' + str(error)) from error
        return Decoded(values['_type'], attributes[2], attributes[3], attributes[4], address, raw, values)


def load_schema(root):
    root = Path(root).resolve()
    sys.path.insert(0, str(root / 'out/generated/lmcp/py'))
    from lmcp.LMCPFactory import LMCPFactory
    return ModelSchema(root, LMCPFactory())


def check_source(message, channel, entity_ids):
    require(channel in ('amase', 'uxas'), 'Unknown input channel')
    if channel == 'amase':
        require(message.source_entity == message.source_service == '0', 'Unexpected AMASE routing source')
    else:
        require(message.source_entity in ('0', '100'), 'Unexpected UxAS routing source')
        require(message.source_entity != '0' or message.source_service == '0', 'Unexpected forwarded AMASE source')
    if message.descriptor in ('afrl.cmasi.AirVehicleState', 'afrl.cmasi.AirVehicleConfiguration', 'afrl.cmasi.SessionStatus'):
        require(message.source_entity == message.source_service == '0', 'Non-AMASE authoritative state')
    if message.descriptor in ('afrl.cmasi.AirVehicleState', 'afrl.cmasi.AirVehicleConfiguration'):
        require(message.fields['ID'] in entity_ids, 'Unexpected business entity')


def envelope(body):
    return START + str(len(body)).encode() + BODY + body + CHECK + str(sum(body)).encode() + END
