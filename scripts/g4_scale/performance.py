"""Offline resource, update-rate and local observation-to-browser latency audit."""
from collections import defaultdict
from datetime import datetime
import json
import math


def rows(path):
    with path.open(encoding='utf-8-sig') as source:
        for line in source:yield json.loads(line)


def need(value,message):
    if not value:raise ValueError(message)


def quantiles(values):
    values=sorted(values)
    if not values:return None
    return {'count':len(values),'min':values[0],'p50':values[math.ceil(.50*len(values))-1],
            'p95':values[math.ceil(.95*len(values))-1],'p99':values[math.ceil(.99*len(values))-1],'max':values[-1]}


def sample_intervals(values):
    need(len(values)>2 and values[0][0]==0,'Missing initial state snapshot')
    need(all(b[0]>a[0] for a,b in zip(values,values[1:])),'Non-monotonic source samples')
    # AMASE sends its Time=0 scene snapshot when the observer connects.
    # The first dynamic sample belongs to the running clock. Report that
    # startup transition separately from gaps in continuous dynamic sampling.
    dynamic=values[1:]
    maximum=max(b[0]-a[0] for a,b in zip(dynamic,dynamic[1:]))
    need(maximum<=2000,'Source sampling has a gap')
    return {'initialSnapshotToDynamicMilliseconds':str(dynamic[0][0]),
            'maximumDynamicIntervalMilliseconds':str(maximum),
            'dynamicSpanMilliseconds':str(dynamic[-1][0]-dynamic[0][0])}


def inspect(directory,case):
    need(case['durationSeconds']==case['sceneDurationSeconds']==1800 and int(case['lastSimulationMs'])>=1800000,
         'Thirty simulation minutes not reached')
    wall=(datetime.fromisoformat(case['finishedAt'])-datetime.fromisoformat(case['startedAt'])).total_seconds()
    need(1800<=wall<=2700,'Mode wall-clock duration outside automatic budget')
    clock=[];states=defaultdict(list);source_times={}
    for row in rows(directory/'amase.jsonl'):
        if row['type']=='afrl.cmasi.SessionStatus':
            need(row['realTimeMultiple']==1,'Non-unit simulation rate')
            clock.append(row)
        if row['type']=='afrl.cmasi.AirVehicleState':
            states[row['id']].append((int(row['timeMs']),row['monotonicSeconds']))
            source_times[(row['id'],row['timeMs'])]=row['monotonicSeconds']
    need(len(states)==20 and all(len(value)>3000 for value in states.values()),'Missing continuous real entity samples')
    need(max(int(r['timeMs']) for r in clock)>=1800000,'Source clock did not reach duration')
    intervals={entity:sample_intervals(values) for entity,values in states.items()}
    need(all(int(value['dynamicSpanMilliseconds'])>=1797000 for value in intervals.values()),
         'Entity dynamic sampling did not span run')
    samples=list(rows(directory/'resources.jsonl'));need(len(samples)>=330,'Insufficient resource samples')
    processes={}
    for sample in samples:
        health=sample['health'];need(not health['error'],'Unaccepted gateway error')
        m=health['metrics'];need(m['client_queue_peak']<=256 and m['client_bytes_peak']<=8388608,'Unbounded client queue')
        for label,value in sample['processes'].items():
            record=processes.setdefault(label,{'private_bytes':[],'working_set_bytes':[],'cpu_percent_one_core':[]})
            for key in record:
                if key in value:record[key].append(float(value[key]))
    need(max(processes['gateway']['private_bytes'])<=1024**3,'Gateway memory bound exceeded')
    need([row['action'] for row in case['recoveryActions']]==
         ['restart','amase-half-cut','restore','uxas-cut','restore','both-cut','restore','restart'],'Recovery matrix incomplete')
    need(case['observerProxies']['amase']['partialBytes']==7 and
         all(not value['error'] and value['connections']>=5 for value in case['observerProxies'].values()),
         'Half-frame or observer reconnection evidence missing')
    clients=json.loads((directory/'continuous-clients/result.json').read_text())['clients']
    latency={}
    for client in clients:
        need(client['finished_monotonic']-client['started_monotonic']>=1800,'Client did not span thirty minutes')
        values=[];negative=0
        for row in rows(directory/'continuous-clients'/('latency-'+str(client['client'])+'.jsonl')):
            source=source_times.get((row['entity_id'],row['source_time_ms']))
            need(source is not None,'Browser sample has no native source')
            delay=(row['received_monotonic']-source)*1000
            if delay<0:negative+=1
            values.append(delay)
        latency[str(client['client'])]={'milliseconds':quantiles(values),'negative_observer_races':negative,
            'meaning':'Local AMASE observer receive to browser consumer receive; clock-aligned on one host',
            'includes_recovery_and_slow_consumption':True,'gateMilliseconds':None,
            'deltaRatePerWallSecond':client['deltas']/wall}
        need(values and client['final_boundary_acknowledged'],'Incomplete client sampling')
    gateways=case['gatewayInstances']
    need(all(r['status']=='passed' and r['sent_business_frames']==0 for r in gateways),'Gateway affected backend controls')
    return {'status':'passed','wallSeconds':wall,'simulationMilliseconds':case['lastSimulationMs'],
        'sourceRatesHz':{entity:(len(value)-2)/(value[-1][1]-value[1][1]) for entity,value in states.items()},
        'sourceSampleIntervals':intervals,
        'latency':latency,'resources':{label:{key:quantiles(values) for key,values in data.items()} for label,data in processes.items()},
        'resourceSamples':len(samples),'queuePeakMessages':max(s['health']['metrics']['client_queue_peak'] for s in samples),
        'queuePeakBytes':max(s['health']['metrics']['client_bytes_peak'] for s in samples),
        'publishedDeltas':str(sum(int(r['metrics']['published_deltas']) for r in gateways)),
        'slowClientClosures':sum(r['metrics']['slow_clients'] for r in gateways),
        'logBytes':str(sum(p.stat().st_size for p in directory.rglob('*') if p.is_file())),
        'boundsMeaning':'Observed finite-run process bounds plus enforced fixed-capacity gateway queues; no indefinite-duration claim'}
