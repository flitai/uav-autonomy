"""Counterexamples derived from a real run; not end-to-end message evidence."""
import copy
import json


def check_parser(analyzer, ordinary, services):
    directory, stdout, application, process = ordinary
    config = directory / 'cfg_HelloWorld.xml'
    baseline = analyzer.analyze(stdout, application, process, config, services)
    analyzer.require(baseline['status'] == 'passed', 'Real parser baseline failed')
    messages = baseline['messages']
    cross = [m for m in messages if not m['selfReceived']]
    def subset(predicate):
        return b'\n'.join(stdout[m['byteStart']:m['byteEnd']] for m in messages if predicate(m)) + b'\nUxAS is Shutting Down immediately\n'
    self_only = b'\n'.join(stdout[m['byteStart']:m['byteEnd']].replace(
        ('Received Id[' + m['receiverId'] + ']').encode(), ('Received Id[' + m['senderId'] + ']').encode())
        for m in cross) + b'\nUxAS is Shutting Down immediately\n'
    no_exit = dict(process, exitCode=1)
    early = dict(process, elapsedSeconds=1)
    timed = dict(process, timedOut=True, forcedTermination=True)
    cases = [
        ('startup-only', b'UxAS is Shutting Down immediately', application, process),
        ('self-only', self_only, application, process),
        ('one-direction', subset(lambda m: m['senderId'] == cross[0]['senderId']), application, process),
        ('wrong-text', stdout.replace(b'Hello from #1', b'WRONG TEXT'), application, process),
        ('unknown-sender', stdout.replace(b'Sent Id[', b'Sent Id[999'), application, process),
        ('unknown-receiver', stdout.replace(b'Received Id[', b'Received Id[999'), application, process),
        ('missing-shutdown', stdout, application.replace('ServiceManager is Finished Shutting Down', 'REMOVED'), process),
        ('nonzero-exit', stdout, application, no_exit),
        ('early-exit', stdout, application, early),
        ('forced-exit', stdout, application, timed),
        ('wrong-config', stdout, application.replace(str(config), 'another-run.xml'), process),
        ('wrong-duration', stdout, application.replace('set run duration seconds 10', 'set run duration seconds 9'), process),
        ('incomplete-messages', stdout.replace(b'] Sent Id[', b']\nSent Id['), application, process),
    ]
    results = []
    for name, output, log, execution in cases:
        result = analyzer.analyze(output, log, execution, config, services)
        analyzer.require(result['status'] == 'failed', 'False acceptance: ' + name)
        results.append(dict(name=name, expectedRejection=True, errors=result['errors']))
    # Complete records remain usable alongside an explicitly reported broken fragment.
    fragment = b'*** RECEIVED:: Received Id[broken\n'
    mixed = analyzer.analyze(stdout + fragment, application, copy.deepcopy(process), config, services)
    analyzer.require(mixed['status'] == 'passed' and mixed['unparsedReceivedLines'], 'Broken fragment handling differs')
    results.append(dict(name='reported-fragment-with-real-complete-records', passed=True))
    (directory.parent / 'parser-checks.json').write_text(json.dumps(dict(
        syntheticOnly=True, baselineDirectory=str(directory), checks=results), indent=2) + '\n', encoding='utf-8')
    return results
