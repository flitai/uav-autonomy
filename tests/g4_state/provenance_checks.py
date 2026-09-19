"""Reject mismatched G4 source revisions without changing released artifacts."""
from copy import deepcopy


def verify(environment, root, baseline_id):
    policy = environment.load(root / 'config/g4-baseline.json')
    environment.require(bool(policy.get('uxasRevision')), 'Expected independently qualified logger revision')
    checks = []

    def reject(name, changed):
        try:
            environment.verify_handoff(root, baseline_id, changed)
        except RuntimeError:
            checks.append(name)
        else:
            raise AssertionError('Invalid provenance accepted: ' + name)

    changed = deepcopy(policy); changed['uxasRevision']['parentFormalUxas']['buildRunId'] = 'different'
    reject('wrong-parent-package', changed)
    changed = deepcopy(policy); changed['uxasRevision']['formalUxas']['buildRunId'] = 'different'
    reject('wrong-current-package', changed)
    changed = deepcopy(policy); changed['uxasRevision']['sources'][0]['sha256'] = '0' * 64
    reject('wrong-repaired-source', changed)
    changed = deepcopy(policy); changed['uxasRevision']['receipts'][0]['sha256'] = '0' * 64
    reject('wrong-rebuild-receipt', changed)
    changed = deepcopy(policy); changed['uxasRevision']['uxasSHA256'] = '0' * 64
    reject('wrong-rebuilt-binary', changed)
    changed = deepcopy(policy); changed.pop('uxasRevision')
    reject('unregistered-package-replacement', changed)
    try:
        environment.verify_handoff(root, 'g3-t01-check-20260919-224451-856', policy)
    except RuntimeError:
        checks.append('stale-qualification-receipt')
    else:
        raise AssertionError('Old package qualification accepted')
    return {'status': 'passed', 'checks': checks, 'formalArtifactsMutated': False}
