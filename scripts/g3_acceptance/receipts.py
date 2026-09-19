"""Read-only verification of the qualified T01-T06 evidence chain."""
from pathlib import Path
import re


def verify(task):
    load, sha, require = task.amase.load, task.amase.sha, task.amase.require
    records = []

    def receipt(run_id, expected):
        require(re.fullmatch(r'g3-t0[1-6]-[A-Za-z0-9-]+', run_id), 'Invalid prior run identity')
        directory = task.root / 'out/runs' / run_id
        result, entry = load(directory / 'result.json'), load(directory / 'entry-result.json')
        require(result['task'] == expected and result['runId'] == run_id and
                result['status'] == entry['status'] == 'passed', 'Unqualified prior run: ' + run_id)
        require(all(entry[k] for k in ('environmentRestored', 'locationRestored', 'encodingRestored', 'persistentPathUnchanged')),
                'Prior environment restoration failed')
        records.append(dict(task=expected, runId=run_id, resultSHA256=sha(directory / 'result.json'),
                            entrySHA256=sha(directory / 'entry-result.json')))
        return directory, result

    receipt(task.context['baselineRunId'], 'G3-T01')
    for expected, run_id in task.stage_policy['historicalRuns'].items():
        directory, result = receipt(run_id, expected)
        # These are immutable historical runs; their former binaries are not
        # misrepresented as the current post-T05 AMASE. Runtime inputs remain checked.
        task.amase.verify_records(task.root, result['inputs'])
        for case in result['cases']:
            folder = directory / case['name']
            require(load(folder / 'case-result.json') == case, 'Historical case receipt differs')
            task.amase.verify_records(folder, case.get('evidence', case.get('files', [])))
        records[-1]['historicalAmaseBuildRunId'] = result['amaseBuildRunId']

    directory, result = receipt(task.context['stabilityRunId'], 'G3-T06')
    require(result['stabilityValidated'] and result['qualifiedPackagesUnchanged'] and result['inputsUnchanged'], 'T06 incomplete')
    for key in ('artifacts', 'amaseBuildRunId', 'formalUxas', 'configurationSHA256', 'executionConfigurationSHA256'):
        require(result[key] == task.record[key], 'Current identity differs from T06: ' + key)
    task.amase.verify_records(task.root, result['inputs'])
    acceptance = load(directory / 'acceptance.json')
    require(sha(directory / 'acceptance.json') == result['acceptanceSHA256'] and acceptance['status'] == 'passed' and
            acceptance['cases'] == result['cases'], 'T06 acceptance binding differs')
    require([c['name'] for c in result['cases'][:3]] == ['repeat-1', 'repeat-2', 'repeat-3'] and len(result['cases']) == 10,
            'T06 repeated execution matrix missing')
    for row in result['cases']:
        child = task.root / 'out/runs' / row['runId']
        require(sha(child / 'result.json') == row['resultSHA256'], 'T06 child receipt changed')
        case = load(child / 'result.json')['cases'][0]
        require(sha(child / case['name'] / 'case-result.json') == row['caseSHA256'] and
                load(child / case['name'] / 'case-result.json') == case, 'T06 child case changed')
        task.amase.verify_records(child / case['name'], case['evidence'])
        require(row['controllerReaped'] and all(p['reaped'] for p in case['processes']), 'T06 process not reaped')
        if row['status'] == 'passed':
            require(row['actualExecutionValidated'] and case['normalExit'] and case['portsReleased'] and
                    all(p['exitCode'] == 0 and not p['forcedTermination'] for p in case['processes']), 'T06 normal case failed')
        else:
            require(row['status'] == case['status'] == 'failed' and row['expectedFailureVerified'] and row['rawFailurePreserved'],
                    'T06 fault falsely accepted')
    for filename, key in [('source-faults.json', 'sourceFaultsSHA256'), ('disconnect-check.json', 'disconnectCheckSHA256'),
                          ('isolation-checks.json', 'isolationChecksSHA256')]:
        require(sha(directory / filename) == acceptance[key], 'T06 auxiliary receipt changed')
    for row in result['sourceFaults']:
        path = directory / 'isolated-sources' / row['name'] / 'result.json'
        require(row['expectedRejectionVerified'] and load(path)['status'] == 'failed' and sha(path) == row['resultSHA256'],
                'T06 source fault receipt changed')
    before, after = load(directory / 'preservation-before.json'), load(directory / 'preservation-after.json')
    require(before == after and result['recovery']['status'] == 'passed', 'T06 recovery/preservation missing')
    task.amase.verify_records(task.root, after)
    records[-1]['acceptanceSHA256'] = result['acceptanceSHA256']
    prior = result['completionReference']
    directory, completed = receipt(prior['runId'], 'G3-T05')
    require(sha(directory / 'result.json') == prior['resultSHA256'] and sha(directory / 'entry-result.json') == prior['entrySHA256'],
            'T05 parent binding changed')
    task.amase.verify_records(task.root, completed['inputs'])
    require(completed['taskCompletionValidated'] and completed['coverageValidated'] and completed['inputsUnchanged'], 'T05 incomplete')
    for case in completed['cases']:
        require(case['status'] == 'passed' and case['normalExit'] and case['portsReleased'], 'T05 failed mode')
        require(load(directory / case['name'] / 'case-result.json') == case, 'T05 case changed')
        task.amase.verify_records(directory / case['name'], case['evidence'])
    return sorted(records, key=lambda r:r['task'])


def validate_confirmation(ready, request, ready_sha, review_sha):
    def need(value, message):
        if not value: raise RuntimeError(message)
    need(request['runId'] == ready['runId'] and request['nonce'] == ready['nonce'], 'Confirmation run/nonce mismatch')
    need(request['controllerPid'] == ready['controllerPid'] and request['javaPid'] == ready['javaPid'] and
         request['uxasPid'] == ready['uxasPid'], 'Confirmation process mismatch')
    need(request['readySHA256'] == ready_sha and request['reviewSHA256'] == review_sha == ready['reviewSHA256'],
         'Confirmation evidence changed')
    need(request['manualGuiAcceptance'] is True and request['confirmationSource'] == 'user' and
         isinstance(request['confirmationText'], str) and request['confirmationText'].strip(), 'Explicit current user confirmation required')
    need(request['requestedAtEpochSeconds'] >= ready['readyAtEpochSeconds'], 'Confirmation predates current GUI review')
    return True
