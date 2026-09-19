"""T02 capture utilities; reuse the qualified G1 strict framing implementation."""
import hashlib
import importlib.util
from pathlib import Path
import struct

spec = importlib.util.spec_from_file_location('g1_sentinel', Path(__file__).parents[1] / 'validation/sentinel.py')
sentinel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sentinel)


def envelope(body):
    return (sentinel.START + str(len(body)).encode() + sentinel.BODY + body + sentinel.CHECK
            + str(sum(body)).encode() + sentinel.END)


def frame(raw, name, source='900', service='1', group='G3Probe'):
    return envelope((name + '$lmcp|' + name + '|' + group + '|' + source + '|' + service + '$').encode() + raw)


def decode(data, factory):
    reader, decoder = sentinel.SentinelReader(), sentinel.Decoder(factory)
    result = []
    for item in reader.feed(data):
        row, raw = decoder.decode(item)
        row.update(offset=item['offset'], length=item['length'], rawSHA256=hashlib.sha256(raw).hexdigest(),
                   wireSHA256=hashlib.sha256(item['wire']).hexdigest())
        obj = factory.LMCPFactory().getObject(bytearray(raw))
        if hasattr(obj, 'ID'):
            row['id'] = str(obj.ID)
        if hasattr(obj, 'CommandID'):
            row.update(commandId=str(obj.CommandID), vehicleId=str(obj.VehicleID))
        if hasattr(obj, 'TaskID'):
            row['taskId'] = str(obj.TaskID)
        if hasattr(obj, 'Key') and hasattr(obj, 'Value'):
            row.update(key=obj.Key, value=obj.Value)
        result.append(row)
    return result, bytes(reader.buffer)


def pub_messages(data):
    position, result = 0, []
    while position + 4 <= len(data):
        length = struct.unpack_from('>I', data, position)[0]
        if position + 4 + length > len(data):
            break
        position += 4
        result.append(data[position:position+length])
        position += length
    return result, data[position:]
