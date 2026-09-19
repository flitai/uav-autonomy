"""Initialization gates. Inputs are decoded real bus observations, never injected state."""


class GateError(RuntimeError):
    pass


class StartupGate:
    def __init__(self, minimum_states=5):
        self.minimum_states = minimum_states
        self.task_sent = False
        self.request_sent = False
        self.task_initialized = False
        self.initial = None

    def inspect(self, rows, java_rows):
        java_hashes = {r['rawSHA256'] for r in java_rows}
        summary = {}
        for entity in ('400', '500'):
            configs = [r for r in rows if r['type'] == 'afrl.cmasi.AirVehicleConfiguration' and r['id'] == entity]
            states = [r for r in rows if r['type'] == 'afrl.cmasi.AirVehicleState' and r['id'] == entity]
            for row in configs + states:
                if row['sourceEntity'] != '0' or row['sourceService'] != '0':
                    raise GateError('Non-AMASE source in initial data')
                # The independent Java monitor may receive a few milliseconds later.
                if row['rawSHA256'] not in java_hashes:
                    return None
            if not configs or len(states) < self.minimum_states:
                return None
            times = [int(r['timeMs']) for r in states]
            if any(b < a for a, b in zip(times, times[1:])):
                raise GateError('Simulation time regressed')
            if len(set(times)) < self.minimum_states or len({(r['latitude'], r['longitude']) for r in states}) < 2:
                return None
            summary[entity] = dict(configuration=configs[0], firstState=states[0], lastState=states[-1],
                                   stateCount=len(states), distinctTimes=len(set(times)))
        self.initial = summary
        return summary

    def before_task(self):
        if self.initial is None or self.task_sent:
            raise GateError('Task requires complete real initialization and single injection')
        self.task_sent = True

    def observe_task(self, row):
        if (self.task_sent and row['type'] == 'uxas.messages.task.TaskInitialized'
                and row.get('taskId') == '1000' and row['sourceEntity'] == '100'):
            self.task_initialized = True

    def before_request(self):
        if self.initial is None or not self.task_initialized or self.request_sent:
            raise GateError('AutomationRequest requires TaskInitialized and single injection')
        self.request_sent = True
