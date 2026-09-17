"""Validate generated messages in an isolated, file-only Python process."""
import argparse
import ast
import importlib
import json
from pathlib import Path
import struct
import sys


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def validate_frame(data):
    require(len(data) >= 27 and data[:4] == b'LMCP', 'Invalid LMCP header')
    require(struct.unpack_from('>I', data, 4)[0] + 12 == len(data), 'Invalid LMCP frame length')
    checksum = struct.unpack_from('>I', data, len(data) - 4)[0]
    require(checksum == 0 or checksum == sum(data[:-4]) & 0xffffffff, 'Invalid LMCP checksum')


def main():
    parser = argparse.ArgumentParser()
    for name in ('generated', 'models', 'fixture', 'java_new', 'java_old', 'inventory', 'output'):
        parser.add_argument('--' + name.replace('_', '-'), required=True, type=Path)
    args = parser.parse_args()
    generated = args.generated.resolve()
    sys.path.insert(0, str(generated))
    models = json.loads(args.models.read_text(encoding='utf-8'))
    java_inventory = json.loads(args.inventory.read_text(encoding='utf-8'))
    from lmcp import LMCPFactory
    from afrl.cmasi.AirVehicleState import AirVehicleState
    from afrl.cmasi.Location3D import Location3D
    from afrl.cmasi.AltitudeType import AltitudeType
    from uxas.messages.task.TaskActive import TaskActive
    factory = LMCPFactory.LMCPFactory()
    imported = []
    # Standalone LMCPClient connects at import time: syntax-check demos, import libraries only.
    for path in sorted(generated.rglob('*.py')):
        ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
        relative = path.relative_to(generated)
        if relative.parts[0] not in ('afrl', 'uxas', 'lmcp'):
            continue
        parts = list(relative.with_suffix('').parts)
        if parts[-1] == '__init__':
            parts.pop()
        module = importlib.import_module('.'.join(parts))
        require(Path(module.__file__).resolve().is_relative_to(generated), 'Imported an unrelated package')
        imported.append('.'.join(parts))
    instantiated = 0
    for model in models:
        namespace = model['namespace'].replace('/', '.')
        for name in model['structs']:
            cls = getattr(importlib.import_module(namespace + '.' + name), name)
            obj = cls()
            entry = java_inventory[namespace + '.' + name]
            require((obj.SERIES_NAME, obj.SERIES_VERSION, obj.LMCP_TYPE, str(obj.SERIES_NAME_ID)) ==
                    (entry['series'], entry['version'], entry['typeId'], entry['seriesId']), 'Cross-language type inventory differs')
            created = factory.createObject(obj.SERIES_NAME_ID, obj.SERIES_VERSION, obj.LMCP_TYPE)
            require(type(created) is cls, 'Python factory cannot create ' + name)
            instantiated += 1
    p = {}
    for line in args.fixture.read_text(encoding='utf-8').splitlines():
        if line and not line.startswith('#'):
            key, value = line.split('=', 1)
            p[key] = value
    samples = {}
    for label in ('basic', 'wide'):
        state = AirVehicleState()
        state.set_ID(int(p[label + '.id']))
        state.set_Time(int(p['time']))
        state.set_Heading(float(p['heading']))
        state.set_Airspeed(float(p['airspeed']))
        location = Location3D()
        location.set_Latitude(float(p['latitude']))
        location.set_Longitude(float(p['longitude']))
        location.set_Altitude(float(p['altitude']))
        location.set_AltitudeType(AltitudeType.MSL)
        state.set_Location(location)
        if label == 'wide':
            state.get_AssociatedTasks().extend(int(v) for v in p['wide.tasks'].split(','))
        samples[label] = state
    task = TaskActive()
    task.set_TaskID(int(p['task.id']))
    task.set_EntityID(int(p['task.entity']))
    task.set_TimeTaskActivated(int(p['task.time']))
    samples['task'] = task

    def describe(obj):
        result = {'type': obj.FULL_LMCP_TYPE_NAME, 'version': obj.SERIES_VERSION}
        if isinstance(obj, AirVehicleState):
            loc = obj.get_Location()
            require(loc.get_AltitudeType() == AltitudeType.MSL, 'Altitude type differs')
            result.update(ID=str(obj.get_ID()), Time=str(obj.get_Time()), Latitude=loc.get_Latitude(),
                          Longitude=loc.get_Longitude(), Altitude=loc.get_Altitude(), AltitudeType='MSL',
                          Heading=obj.get_Heading(), Airspeed=obj.get_Airspeed(),
                          AssociatedTasks=[str(x) for x in obj.get_AssociatedTasks()])
        else:
            result.update(TaskID=str(obj.get_TaskID()), EntityID=str(obj.get_EntityID()),
                          TimeTaskActivated=str(obj.get_TimeTaskActivated()))
        return result

    args.output.mkdir(parents=True, exist_ok=True)
    java_fields = json.loads((args.java_new / 'fields.json').read_text(encoding='utf-8'))
    checks = []
    for label, expected in samples.items():
        require(describe(expected) == java_fields[label], 'Java/Python fixture fields differ: ' + label)
        for checksum in (False, True):
            name = label + ('-checksum.bin' if checksum else '-zero.bin')
            frame = bytes(LMCPFactory.packMessage(expected, checksum))
            validate_frame(frame)
            require(LMCPFactory.validate(frame), 'Python factory rejects its own checksum')
            java_frame = (args.java_new / name).read_bytes()
            validate_frame(java_frame)
            require(frame == java_frame, 'Java/Python frame differs: ' + name)
            decoded = factory.getObject(bytearray(java_frame))
            require(decoded is not None and describe(decoded) == describe(expected), 'Java to Python fields differ')
            require(bytes(LMCPFactory.packMessage(decoded, checksum)) == java_frame, 'Python re-encoding differs')
            (args.output / name).write_bytes(frame)
            if label != 'task':
                require(frame == (args.java_old / name).read_bytes(), 'Old/new CMASI frame differs: ' + name)
            checks.append({'sample': label, 'checksum': checksum, 'bytes': len(frame), 'fields': describe(decoded)})
    old_task = (args.java_old / 'task-checksum.bin').read_bytes()
    validate_frame(old_task)
    require(struct.unpack_from('>H', old_task, 21)[0] == 7, 'Expected old UXTASK 7')
    require(factory.getObject(bytearray(old_task)) is None, 'New Python unexpectedly accepts UXTASK 7')
    corrupt = bytearray((args.output / 'basic-checksum.bin').read_bytes())
    corrupt[30] ^= 1
    (args.output / 'corrupt.bin').write_bytes(corrupt)
    require(not LMCPFactory.validate(corrupt), 'Python checksum accepted corrupt sample')
    rejected = False
    try:
        validate_frame(corrupt)
    except RuntimeError:
        rejected = True
    require(rejected, 'Independent checksum accepted corrupt sample')
    report = {'status': 'passed', 'python': sys.version, 'executable': sys.executable,
              'importedModules': imported, 'instantiatedStructs': instantiated,
              'samples': checks, 'oldUxtaskVersionRejected': True, 'corruptChecksumRejected': True,
              'demoScripts': 'syntax checked only; LMCPClient has network side effects at import'}
    (args.output / 'result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print('PYTHON_PROBE_OK', instantiated, 'structs;', len(imported), 'modules;', len(checks), 'frames')


if __name__ == '__main__':
    main()
