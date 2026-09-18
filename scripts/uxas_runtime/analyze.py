"""Validate real HelloWorld logs; synthetic fixtures are never runtime evidence."""
import re
import xml.etree.ElementTree as ET


def require(value, message):
    if not value:
        raise RuntimeError(message)


def configuration(data):
    root = ET.fromstring(data)
    require(root.tag == 'UxAS' and root.attrib == {
        'EntityID': '100', 'FormatVersion': '1.0', 'EntityType': 'None', 'RunDuration_s': '10.0'},
        'Original HelloWorld root configuration differs')
    services = list(root)
    expected = [dict(Type='HelloWorld', StringToSend='Hello from #1', SendPeriod_ms='1000'),
                dict(Type='HelloWorld', StringToSend='Hello from #2', SendPeriod_ms='5001')]
    require(len(services) == 2 and all(s.tag == 'Service' and s.attrib == e
                                    for s, e in zip(services, expected)), 'Original HelloWorld services differ')
    return expected


MESSAGE = re.compile(rb'\*\*\* RECEIVED:: Received Id\[([0-9]+)\] Sent Id\[([0-9]+)\] Message\[([^\]\r\n]*)\] \*\*\*')


def analyze(stdout, application, process, config_path, services):
    """Return diagnostics even when validation fails, including raw byte offsets."""
    result = dict(status='failed', errors=[], messages=[], unparsedReceivedLines=[])
    errors = result['errors']
    def check(value, message):
        if not value:
            errors.append(message)

    check(process.get('exitCode') == 0 and not process.get('timedOut') and
          not process.get('forcedTermination') and process.get('reaped'), 'Process did not exit normally with code 0')
    check(10 <= process.get('elapsedSeconds', 0) < 30, 'Process duration outside original run and timeout bounds')
    check('UxAS_Main loaded base XML configuration from [' + str(config_path) + ']' in application,
          'Exact run configuration was not loaded')
    check('ConfigurationManager::setEntityFromXmlNode set run duration seconds 10' in application,
          'Original 10 second duration was not applied')
    ids = re.findall(r'ServiceManager::createService successfully created HelloWorld service ID ([0-9]+)', application)
    started = re.findall(r'ServiceManager::instantiateConfigureInitializeStartService successfully initialized and started HelloWorld service ID ([0-9]+)', application)
    check(len(ids) == 2 and len(set(ids)) == 2 and started == ids, 'Two distinct configured services did not start')
    mapping = dict(zip(ids, [s['StringToSend'] for s in services])) if len(ids) == 2 else {}
    result['services'] = [dict(id=i, text=t) for i, t in mapping.items()]
    valid_spans = []
    directions = {}
    self_count = 0
    for match in MESSAGE.finditer(stdout):
        receiver, sender, message = (v.decode('utf-8', errors='strict') for v in match.groups())
        valid_spans.append(match.span())
        valid = receiver in mapping and sender in mapping and mapping.get(sender) == message
        check(valid, 'Unknown service ID or wrong sender text in complete receive record')
        own = receiver == sender
        self_count += int(own)
        if valid and not own:
            key = sender + '->' + receiver
            directions[key] = directions.get(key, 0) + 1
        result['messages'].append(dict(receiverId=receiver, senderId=sender, message=message,
                                       byteStart=match.start(), byteEnd=match.end(), selfReceived=own, valid=valid))
    offset = 0
    for line in stdout.splitlines(keepends=True):
        tokens = [offset + m.start() for m in re.finditer(b'RECEIVED', line)]
        if any(not any(a <= token < b for a, b in valid_spans) for token in tokens):
            result['unparsedReceivedLines'].append(dict(byteStart=offset, byteEnd=offset + len(line),
                                                        text=line.decode('utf-8', errors='replace')))
        offset += len(line)
    check(len(mapping) == 2 and all(directions.get(a + '->' + b, 0) >= 1
                                  for a in mapping for b in mapping if a != b), 'Missing cross-service receive direction')
    result.update(directions=directions, selfReceivedCount=self_count)
    ordered = ['UxAS_Main running ServiceManager',
               'ServiceManager has started Terminating Services',
               'ServiceManager::runUntil all services terminated after [',
               'ServiceManager::runUntil found base class terminated after [',
               'ServiceManager is Finished Shutting Down']
    positions = [application.find(value) for value in ordered]
    check(all(p >= 0 for p in positions) and positions == sorted(positions), 'Normal service shutdown evidence missing or out of order')
    start = re.search(r'(?m)^([0-9]+) INFO:.*UxAS_Main running ServiceManager', application)
    stop = re.search(r'(?m)^([0-9]+) INFO:.*ServiceManager has started Terminating Services', application)
    duration = int(stop[1]) - int(start[1]) if start and stop else None
    result['serviceRunInterval'] = dict(startSourceMilliseconds=start[1] if start else None,
                                       stopSourceMilliseconds=stop[1] if stop else None, durationMilliseconds=duration)
    check(duration is not None and 10000 <= duration < 30000, 'ServiceManager did not run for the configured 10 seconds')
    check('(run duration exit)' in application and 'UxAS is Shutting Down immediately' in stdout.decode('utf-8'),
          'Run duration exit or main shutdown evidence missing')
    check(not re.search(r'services remain after|aborted effort to terminate|failed to destroy message send timer', application),
          'Incomplete service or timer shutdown')
    check(not re.search(r'(?m)^\d+ ERROR:', application), 'Application error in normal HelloWorld run')
    if not errors:
        result['status'] = 'passed'
    return result
