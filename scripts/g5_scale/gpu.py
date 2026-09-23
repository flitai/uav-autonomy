"""Sample Windows GPU counters for the owned Edge process tree."""
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import threading
import time

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('g5_scale_native_metrics',ROOT/'scripts/g4_scale/metrics.py')
metrics=importlib.util.module_from_spec(spec);spec.loader.exec_module(metrics)
COMMAND=("$sets=@('\\GPU Process Memory(*)\\Local Usage',"
         "'\\GPU Engine(*)\\Utilization Percentage');"
         "$sample=Get-Counter -Counter $sets -ErrorAction Stop;"
         "$sample.CounterSamples | Select-Object Path,CookedValue | ConvertTo-Json -Compress")


class Observer:
    def __init__(self,owner_pid,path):
        self.owner_pid=owner_pid;self.path=path
        self.stopping=threading.Event();self.error=None;self.count=0;self.positive=0
        self.thread=threading.Thread(target=self.work,name='g5-gpu-counters',daemon=True)
    def start(self):self.thread.start()
    def sample(self):
        parents=metrics.process_parents();owned=metrics.descendants(self.owner_pid,parents)
        result=subprocess.run(['powershell.exe','-NoProfile','-Command',COMMAND],capture_output=True,
                              timeout=20,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:raise RuntimeError('GPU counters failed: '+result.stderr.decode(errors='replace')[-500:])
        values=json.loads(result.stdout.decode('utf-8-sig'))
        if isinstance(values,dict):values=[values]
        local={};engines=[]
        for row in values:
            path=row['Path'].lower();match=re.search(r'pid_(\d+)',path)
            if not match or int(match.group(1)) not in owned:continue
            value=float(row['CookedValue'])
            if 'gpu process memory' in path and path.endswith('\\local usage'):
                local[path]=value
            elif 'gpu engine' in path and path.endswith('\\utilization percentage'):
                engines.append(value)
        record=dict(monotonicSeconds=time.monotonic(),ownedPids=sorted(owned),
                    localBytes=str(round(sum(local.values()))),
                    engineUtilizationSumPercent=sum(engines),engineUtilizationPeakPercent=max(engines,default=0),
                    localCounterInstances=len(local),engineCounterInstances=len(engines),
                    method='Windows GPU Process Memory Local Usage and GPU Engine utilization; owned Edge tree')
        with self.path.open('a',encoding='utf-8') as output:output.write(json.dumps(record)+'\n')
        self.count+=1
        if local and sum(local.values())>0:self.positive+=1
    def work(self):
        try:
            while not self.stopping.is_set():
                self.sample()
                if self.stopping.wait(120):break
        except Exception as error:self.error=str(error)
    def stop(self):
        self.stopping.set();self.thread.join(25)
        if self.thread.is_alive():raise RuntimeError('GPU observer did not stop normally')
        result=dict(status='passed' if not self.error and self.positive else 'failed',
                    error=self.error,normalExit=True,samples=self.count,positiveSamples=self.positive)
        self.path.with_suffix('.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        return result
