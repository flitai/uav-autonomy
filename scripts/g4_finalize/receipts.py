"""Narrow same-version finalization; never convert the visual run to passed."""
from collections import Counter
from datetime import datetime
import importlib.util
from pathlib import Path


ROOT=Path(__file__).resolve().parents[2]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path); value=importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value
package=module('finalization_package',ROOT/'scripts/g4_stage/package.py')
load,save,sha,need=package.load,package.save,package.sha,package.need


def visual(root,confirmation=None):
    policy=load(root/'config/g4-finalization.json')
    directory=root/'out/runs'/policy['visualRunId']; result=load(directory/'result.json'); ready=load(directory/'gui-ready.json')
    need(sha(directory/'result.json')==policy['visualResultSHA256'],'Unrecognized visual run result')
    need(result['status']=='failed' and result['error']=='GUI resumed/reset after reviewed pause','Not the recorded review-time advance')
    need(result['packageSHA256']==policy['packageSHA256'] and len(result['cases'])==1,'Visual package differs')
    case=result['cases'][0]; folder=directory/case['name']; review=folder/'review/review.json'
    need(sha(folder/'case-result.json')==policy['visualCaseSHA256'] and load(folder/'case-result.json')==case,'Visual case differs')
    need(case['normalExit'] and case['portsReleased'] and not case.get('cleanupErrors') and
         all(p['exitCode']==0 and not p['forcedTermination'] and p['reaped'] for p in case['processes']),'Visual GUI did not close normally')
    need(sha(review)==ready['reviewSHA256']==policy['visualReviewSHA256'] and load(review)['status']=='passed' and
         load(review)['taskCount']==20 and ready['pausedSimulationTimeMs']==policy['pausedSimulationTimeMs'],'Reviewed proof differs')
    package.verify_files(root,result['inputs']); package.verify_files(folder,case['evidence'])
    package.verify_files(review.parent,load(review)['files'])
    for filename in ('analysis.xml','coverage-cells.xml','analysis-events.tsv'):
        need(sha(folder/'amase'/filename)==sha(folder/'review/evidence/amase'/filename),'Reviewed analysis changed after resume')
    # The frozen prefix stays valid. No post-review task, command or lifecycle changes are accepted.
    import json
    counts={}; sessions=[]
    for name in ('amase','observer'):
        counter=Counter()
        with (folder/(name+'.jsonl')).open(encoding='utf-8') as stream:
            for line in stream:
                row=json.loads(line)
                if datetime.fromisoformat(row['wallTime']).timestamp()<ready['readyAtEpochSeconds']: continue
                need(row['type'] in ('afrl.cmasi.AirVehicleState','afrl.cmasi.SessionStatus','uxas.messages.uxnative.OnboardStatusReport'),
                     'Post-review task/command/lifecycle event changed')
                counter[row['type']]+=1
                if row['type'] in ('afrl.cmasi.AirVehicleState','afrl.cmasi.SessionStatus'):
                    need(int(policy['pausedSimulationTimeMs'])<=int(row['timeMs'])<=int(policy['postReviewFinalTimeMs']),
                         'Post-review reset or unrecognized advancement')
                if row['type']=='afrl.cmasi.SessionStatus':
                    need(row['realTimeMultiple']==1,'Post-review rate changed')
                    if name=='amase': sessions.append((row['state'],row['timeMs']))
        counts[name]=dict(counter)
    need(sessions==[(1,'786039'),(1,'786569'),(2,'786599')],'Unrecognized post-review session history')
    if confirmation:
        need(confirmation['visualRunId']==policy['visualRunId'] and confirmation['visualResultSHA256']==policy['visualResultSHA256'] and
             confirmation['visualReviewSHA256']==policy['visualReviewSHA256'] and confirmation['packageSHA256']==policy['packageSHA256'],
             'Visual confirmation binding differs')
        need(confirmation['confirmationSource']=='user' and confirmation['confirmationText'].strip() and
             confirmation['confirmedAtEpochSeconds']>=ready['readyAtEpochSeconds'] and confirmation['scope']=='visual-only-same-version',
             'Current user visual confirmation required')
    return dict(policy=policy,postReviewMessageCounts=counts,visualRunStatus='failed',visualNormalExit=True,
                completeControlledRerunRequired=True)
