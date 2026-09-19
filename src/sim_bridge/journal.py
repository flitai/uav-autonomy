"""Bounded, read-only consumption of one run's committed UxAS message log.

SQLite XML is semantic evidence, never a replacement for captured wire bytes.
No read transaction is held while decoding, persisting, or delivering messages.
"""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import xml.etree.ElementTree as ET
from xml.dom import minidom

from .codec import Decoder, MAX_BODY, check_source, require


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def xml_object(node, schema, expected=None, depth=0):
    require(depth <= 32, 'XML nesting exceeds limit')
    key = (node.get('Series'), node.tag)
    require(key in schema.structs and (expected is None or schema.derived_from(key, expected)), 'Unknown XML object')
    fields = schema.fields(key)
    names = [n.tag for n in node]
    required = {f['Name'] for _, f in fields if f.get('Optional') != 'true'}
    require(len(names) == len(set(names)) and required.issubset(names) and set(names).issubset({f['Name'] for _, f in fields}),
            'Missing, repeated or unknown XML fields: ' + str(key) + ': ' + str([n.tag for n in node]))
    for kind, field in fields:
        item = node.find(field['Name'])
        if item is None:
            continue  # The C++ writer omits null optional objects.
        array = field['Type'].endswith('[]')
        objects = kind in schema.structs
        if array:
            require(len(item) <= min(int(field.get('MaxArrayLength', 65535)), 65535), 'XML array exceeds limit')
            values = list(item)
        elif objects:
            require(len(item) <= 1 and (len(item) == 1 or field.get('Optional') != 'false'), 'Invalid XML object field')
            values = list(item)
        else:
            require(not len(item), 'Invalid XML scalar')
            values = [item]
        for value in values:
            if objects:
                xml_object(value, schema, kind, depth + 1)
            else:
                require(not len(value), 'Invalid XML scalar nesting')
                if array:
                    require(value.tag == kind[1], 'Invalid XML array element')
                if kind[1] != 'string':
                    require(bool(value.text and value.text.strip()), 'Empty XML scalar')
                if kind[1] == 'bool':
                    require(value.text.strip().lower() in ('true', 'false'), 'Invalid XML boolean')
                if kind in schema.enums:
                    require(value.text.strip() in schema.enum_values[kind], 'Unknown XML enum value')


class Journal:
    batch_size = 128

    def __init__(self, binding_path, run_id, schema, entity_ids):
        self.binding_path = Path(binding_path).resolve()
        self.binding_bytes = self.binding_path.read_bytes()
        self.binding = json.loads(self.binding_bytes)
        require(self.binding['run_id'] == run_id, 'Journal run identity differs')
        self.run_id, self.schema, self.entity_ids = run_id, schema, set(entity_ids)
        self.directory = Path(self.binding['log_directory']).resolve()
        require(self.directory.is_dir(), 'Journal directory missing')
        self.identities, self.first_hashes, self.closed, self.highest = {}, {}, {}, {}
        for item in self.binding.get('journal_anchors', []):
            self.identities[item['file']] = tuple(item['identity'])
            self.first_hashes[item['file']] = item['first_sha256']
            self.highest[item['file']] = int(item['row_id'])
        self.decoder = Decoder(schema)

    def connect(self, path):
        require(self.binding_path.read_bytes() == self.binding_bytes, 'Journal binding changed')
        require(path.is_file() and path.resolve().parent == self.directory, 'Journal source missing or outside run')
        stat = path.stat()
        identity = (stat.st_dev, stat.st_ino, getattr(stat, 'st_birthtime_ns', 0))
        require(self.identities.setdefault(path.name, identity) == identity, 'Journal file replaced')
        connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=0.25)
        connection.execute('PRAGMA query_only=ON')
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 4 * MAX_BODY)
        return connection

    def boundary(self):
        paths = []
        for path in self.directory.glob('messageLog_*.db3'):
            match = re.fullmatch(r'messageLog_([1-9][0-9]*)_(-?[0-9]+)\.db3', path.name)
            require(match is not None, 'Unknown journal shard name')
            paths.append((int(match[1]), path))
        paths.sort()
        require(paths and [n for n, _ in paths] == list(range(1, len(paths) + 1)), 'Missing or duplicate journal shard')
        require(set(self.identities).issubset({p.name for _, p in paths}), 'Previously observed journal shard missing')
        boundary = []
        for number, path in paths:
            connection = self.connect(path)
            try:
                require([r[1] for r in connection.execute('PRAGMA table_info(msg)')] ==
                        ['id', 'time_ms', 'descriptor', 'groupID', 'entityID', 'serviceID', 'xml'], 'Journal schema differs')
                first = connection.execute('SELECT * FROM msg ORDER BY id LIMIT 1').fetchone()
                last = connection.execute('SELECT id FROM msg ORDER BY id DESC LIMIT 1').fetchone()
            finally:
                connection.close()
            require(first is not None and first[0] == 1, 'Journal is empty or initial rows missing')
            fingerprint = digest(first)
            require(self.first_hashes.setdefault(path.name, fingerprint) == fingerprint, 'Journal initial row changed')
            require(last[0] >= self.highest.get(path.name, 0), 'Journal shard was truncated')
            self.highest[path.name] = last[0]
            if path.name in self.closed:
                require(last[0] == self.closed[path.name], 'Closed journal shard changed')
            if number < len(paths):
                self.closed[path.name] = last[0]
            boundary.append({'shard': str(number), 'file': path.name, 'row_id': str(last[0]), 'first_sha256': fingerprint})
        return boundary

    def anchors(self):
        return [dict(item, identity=list(self.identities[item['file']])) for item in self.boundary()]

    def decode(self, row, shard):
        row_id, time_ms, descriptor, group, entity, service, xml = row
        require(isinstance(xml, str) and len(xml.encode('ascii')) <= 4 * MAX_BODY, 'Invalid or oversized journal XML')
        require('<!DOCTYPE' not in xml.upper() and '<!ENTITY' not in xml.upper(), 'XML declarations forbidden')
        node = ET.fromstring(xml)
        xml_object(node, self.schema)
        from lmcp.LMCPFactory import packMessage
        with minidom.parseString(xml) as document:
            obj = self.schema.factory.createObjectByName(node.get('Series'), node.tag)
            obj.unpackFromXMLNode(document.documentElement, self.schema.factory)
        require(obj is not None, 'Journal XML decode failed')
        raw = bytes(packMessage(obj, True))
        require(len(raw) <= MAX_BODY, 'Journal message exceeds LMCP limit')
        attrs = (descriptor + '$lmcp|' + descriptor + '|' + group + '|' + str(entity) + '|' + str(service) + '$').encode('ascii')
        message = self.decoder.decode({'body': attrs + raw})
        check_source(message, 'uxas', self.entity_ids)
        return {'run_id': self.run_id, 'event_id': {'shard': str(shard), 'row_id': str(row_id)},
                'origin': 'uxas_committed_log', 'source_time_ms': str(time_ms), 'xml_sha256': hashlib.sha256(xml.encode()).hexdigest(),
                'message': message.metadata()}

    def read(self, boundary, cursor=(0, 0)):
        cursor = tuple(map(int, cursor))
        require(cursor <= (int(boundary[-1]['shard']), int(boundary[-1]['row_id'])), 'Journal truncated behind cursor')
        for item in boundary:
            shard, finish = int(item['shard']), int(item['row_id'])
            if shard < cursor[0]:
                continue
            position = cursor[1] if shard == cursor[0] else 0
            require(position <= finish, 'Journal shard is behind its consumed cursor')
            path = self.directory / item['file']
            while position < finish:
                connection = self.connect(path)
                try:
                    rows = connection.execute('SELECT * FROM msg WHERE id > ? AND id <= ? ORDER BY id LIMIT ?',
                                              (position, finish, self.batch_size)).fetchall()
                finally:
                    connection.close()
                require(rows, 'Journal boundary is incomplete')
                for row in rows:
                    require(row[0] == position + 1, 'Missing journal row')
                    event = self.decode(row, shard)
                    position = row[0]
                    yield event


class EventStore:
    """Durable normalized record, unique by run/shard/row; no history in RAM."""
    def __init__(self, path, binding):
        self.run_id = binding['run_id']
        self.connection = sqlite3.connect(path, timeout=1)
        self.connection.execute('PRAGMA journal_mode=WAL')
        self.connection.execute('PRAGMA synchronous=FULL')
        self.connection.execute('CREATE TABLE IF NOT EXISTS metadata (id INTEGER PRIMARY KEY, binding TEXT NOT NULL)')
        self.connection.execute('CREATE TABLE IF NOT EXISTS events (shard INTEGER, row_id INTEGER, sha256 TEXT NOT NULL, '
                                'event TEXT NOT NULL, PRIMARY KEY(shard,row_id))')
        existing = self.connection.execute('SELECT binding FROM metadata WHERE id=1').fetchone()
        require(existing is None or existing[0] == canonical(binding), 'Event store belongs to another run/source')
        self.connection.execute('INSERT OR IGNORE INTO metadata VALUES(1,?)', (canonical(binding),))
        self.connection.commit()

    def append(self, event):
        require(event['run_id'] == self.run_id, 'Event store input belongs to another run')
        key = (int(event['event_id']['shard']), int(event['event_id']['row_id']))
        data, checksum = canonical(event), digest(event)
        previous = self.connection.execute('SELECT sha256,event FROM events WHERE shard=? AND row_id=?', key).fetchone()
        require(previous is None or (previous[0] == checksum and previous[1] == data), 'Committed event changed on reread')
        if previous is not None:
            return False
        with self.connection:
            self.connection.execute('INSERT INTO events VALUES(?,?,?,?)', (*key, checksum, data))
        return True

    def records(self):
        for checksum, data in self.connection.execute('SELECT sha256,event FROM events ORDER BY shard,row_id'):
            event = json.loads(data)
            require(digest(event) == checksum, 'Normalized record is corrupt')
            yield event

    def boundaries(self):
        return {int(shard): int(row) for shard, row in self.connection.execute(
            'SELECT shard,MAX(row_id) FROM events GROUP BY shard')}

    def close(self):
        self.connection.close()
