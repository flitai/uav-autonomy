"""Confirmation identity counterexamples; no synthetic confirmation enters a live run."""
import copy


def verify(receipts):
    ready = dict(runId='g3-t07-current', nonce='current-nonce', controllerPid=1, javaPid=2, uxasPid=3,
                 reviewSHA256='review-hash', readyAtEpochSeconds=20)
    request = dict(runId=ready['runId'], nonce=ready['nonce'], controllerPid=1, javaPid=2, uxasPid=3,
        readySHA256='ready-hash', reviewSHA256='review-hash', manualGuiAcceptance=True,
        confirmationSource='user', confirmationText='current confirmation test fixture', requestedAtEpochSeconds=21)
    receipts.validate_confirmation(ready, request, 'ready-hash', 'review-hash')
    tests = ['matching-fixture']
    for key, value in [('runId','g3-t05-old'), ('nonce','old-nonce'), ('controllerPid',9), ('javaPid',9), ('uxasPid',9),
                       ('readySHA256','wrong'), ('reviewSHA256','wrong'), ('manualGuiAcceptance',False),
                       ('confirmationSource','automatic'), ('confirmationText','  '), ('requestedAtEpochSeconds',19)]:
        changed = copy.deepcopy(request); changed[key] = value
        try: receipts.validate_confirmation(ready, changed, 'ready-hash', 'review-hash')
        except RuntimeError: tests.append('reject-' + key)
        else: raise RuntimeError('Invalid confirmation accepted: ' + key)
    return dict(status='passed', syntheticFixturesOnly=True, tests=tests)
