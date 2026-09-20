"""All-entity real initialization followed by exactly one request per assignment."""


class GateError(RuntimeError):
    pass


class Gate:
    def __init__(self, assignments, minimum_states=5):
        self.assignments=assignments; self.minimum_states=minimum_states
        self.ids={r['entityId'] for r in assignments}; self.initial=None; self.index=0
        if len(self.ids)!=len(assignments) or not assignments: raise GateError('One task per entity required')
        self.task_sent=False; self.task_initialized=False; self.request_sent=False

    @property
    def current(self):
        if self.index>=len(self.assignments): raise GateError('All assignments already requested')
        return self.assignments[self.index]

    def inspect(self, rows, monitor):
        hashes={r['rawSHA256'] for r in monitor}; summary={}
        for entity in sorted(self.ids):
            configs=[r for r in rows if r['type']=='afrl.cmasi.AirVehicleConfiguration' and r.get('id')==entity]
            states=[r for r in rows if r['type']=='afrl.cmasi.AirVehicleState' and r.get('id')==entity]
            if any(r['sourceEntity']!='0' or r['sourceService']!='0' for r in configs+states): raise GateError('Non-AMASE initialization')
            if not configs or len(states)<self.minimum_states: return None
            if any(r['rawSHA256'] not in hashes for r in configs+states): return None
            times=[int(r['timeMs']) for r in states]
            if any(b<=a for a,b in zip(times,times[1:])): raise GateError('Duplicate or regressed state time')
            if len({(r['latitude'],r['longitude']) for r in states})<2: return None
            summary[entity]={'configuration':configs[0],'firstState':states[0],'lastState':states[-1],'stateCount':len(states)}
        self.initial=summary; return summary

    def before_task(self):
        self.current
        if self.initial is None or self.task_sent: raise GateError('Task before real barrier or duplicate task')
        self.task_sent=True

    def observe_task(self,row):
        if (self.task_sent and row['type']=='uxas.messages.task.TaskInitialized' and row.get('taskId')==self.current['taskId']
                and row['sourceEntity']=='100'):
            self.task_initialized=True

    def before_request(self):
        if self.initial is None or not self.task_initialized or self.request_sent: raise GateError('Request before initialization or duplicate')
        self.request_sent=True

    def planned(self):
        if not self.request_sent: raise GateError('Planning before request')
        self.index+=1; self.task_sent=False; self.task_initialized=False; self.request_sent=False
