"""Deterministic browser state; no web framework, sockets, or wall clock."""
from copy import deepcopy

from .codec import require
from .journal import digest


COLLECTIONS = ('entities', 'tasks', 'routes', 'commands', 'zones')
TASK_TYPES = {'PointSearchTask': 'point', 'LineSearchTask': 'line', 'AreaSearchTask': 'area'}


class State:
    def __init__(self, run_id, entity_ids, limit=4096):
        self.run_id, self.entity_ids, self.limit = run_id, set(entity_ids), limit
        self.data = {key: {} for key in COLLECTIONS}
        self.data['simulation'] = {}
        self.cursor, self.sequence = (0, 0), 0
        self.deleted = {key: set() for key in ('entities', 'tasks', 'zones')}

    def snapshot(self):
        return deepcopy(self.data)

    def fingerprint(self):
        return digest(self.data)

    def apply(self, event):
        require(event['run_id'] == self.run_id, 'State event belongs to another run')
        key = tuple(int(event['event_id'][k]) for k in ('shard', 'row_id'))
        if key <= self.cursor:
            return []
        require(key == (self.cursor[0], self.cursor[1] + 1) or key == (self.cursor[0] + 1, 1), 'State event order has a gap')
        message = event['message']
        f, name = message['fields'], message['type'].split('.')[-1]
        source = {'entity_id': message['sourceEntity'], 'service_id': message['sourceService'],
                  'group': message['sourceGroup'], 'event_id': event['event_id'], 'source_time_ms': event['source_time_ms']}
        changes = []

        def update(collection, identifier, value):
            require(collection not in self.deleted or identifier not in self.deleted[collection], 'Update resurrects deleted object')
            old = self.data[collection].get(identifier, {})
            result = {**old, **deepcopy(value)}
            if result == old:
                return
            result['source'] = deepcopy(source)
            require(identifier in self.data[collection] or len(self.data[collection]) < self.limit, 'State object limit exceeded')
            self.data[collection][identifier] = result
            changes.append({'collection': collection, 'id': identifier, 'op': 'upsert', 'value': deepcopy(result)})

        def delete(collection, identifier):
            self.data[collection].pop(identifier, None)
            require(len(self.deleted[collection]) < self.limit or identifier in self.deleted[collection], 'Tombstone limit exceeded')
            self.deleted[collection].add(identifier)
            changes.append({'collection': collection, 'id': identifier, 'op': 'delete'})

        if name in ('AirVehicleState', 'AirVehicleConfiguration', 'SessionStatus'):
            require(message['sourceEntity'] == message['sourceService'] == '0', 'State authority differs')
        if name in ('AirVehicleState', 'AirVehicleConfiguration'):
            identifier = f['ID']
            require(identifier in self.entity_ids, 'Unexpected state entity')
            if identifier not in self.deleted['entities']:
                if name == 'AirVehicleConfiguration':
                    update('entities', identifier, {'entity_id': identifier, 'configuration': f})
                else:
                    previous = self.data['entities'].get(identifier, {})
                    if int(f['Time']) >= int(previous.get('simulation_time_ms', '-1')):
                        location = f['Location']
                        update('entities', identifier, {'entity_id': identifier, 'simulation_time_ms': f['Time'],
                               'position': {'latitude_deg': location['Latitude'], 'longitude_deg': location['Longitude'],
                                            'altitude_m': location['Altitude'], 'altitude_reference': location['AltitudeType']},
                               'attitude': {'heading_deg': f['Heading'], 'pitch_deg': f['Pitch'], 'roll_deg': f['Roll']},
                               'groundspeed_mps': f['Groundspeed'], 'current_command_id': f['CurrentCommand'],
                               'current_waypoint_id': f['CurrentWaypoint'], 'associated_task_ids': f['AssociatedTasks'], 'state': f})
                        command_key = identifier + ':mission'
                        command = self.data['commands'].get(command_key)
                        if command and command['command_id'] == f['CurrentCommand']:
                            update('commands', command_key, {'execution_observed': True, 'execution_time_ms': f['Time'],
                                                            'current_waypoint_id': f['CurrentWaypoint']})
        elif name == 'SessionStatus':
            if int(f['ScenarioTime']) >= int(self.data['simulation'].get('simulation_time_ms', '-1')):
                value = {'simulation_time_ms': f['ScenarioTime'], 'start_time_ms': f['StartTime'],
                         'state': f['State'], 'real_time_multiple': f['RealTimeMultiple'], 'source': deepcopy(source)}
                self.data['simulation'] = value
                changes.append({'collection': 'simulation', 'id': 'clock', 'op': 'upsert', 'value': deepcopy(value)})
        elif name in TASK_TYPES:
            require(set(f['EligibleEntities']).issubset(self.entity_ids), 'Task references unknown entity')
            if f['TaskID'] not in self.deleted['tasks']:
                update('tasks', f['TaskID'], {'task_id': f['TaskID'], 'kind': TASK_TYPES[name], 'definition': f,
                                           'eligible_entity_ids': f['EligibleEntities']})
        elif name in ('TaskInitialized', 'TaskActive', 'TaskComplete'):
            identifier = f['TaskID']
            require(message['sourceEntity'] == '100', 'Task event authority differs')
            if name == 'TaskActive':
                require(f['EntityID'] in self.entity_ids, 'Active task references unknown entity')
            elif name == 'TaskComplete':
                require(set(f['EntitiesInvolved']).issubset(self.entity_ids), 'Completion references unknown entity')
            if identifier not in self.deleted['tasks']:
                task = self.data['tasks'].get(identifier, {})
                if name == 'TaskInitialized':
                    update('tasks', identifier, {'task_id': identifier, 'initialized': True})
                elif name == 'TaskActive' and not task.get('backend_completed'):
                    update('tasks', identifier, {'task_id': identifier, 'active_entity_id': f['EntityID'],
                                               'activated_time_ms': f['TimeTaskActivated'], 'active': True})
                elif name == 'TaskComplete':
                    update('tasks', identifier, {'task_id': identifier, 'backend_completed': True, 'active': False,
                                               'completed_entity_ids': f['EntitiesInvolved'], 'completed_time_ms': f['TimeTaskCompleted']})
        elif name == 'TaskAssignmentSummary':
            assignments = {}
            for assignment in f['TaskList']:
                require(assignment['AssignedVehicle'] in self.entity_ids, 'Assignment references unknown entity')
                assignments.setdefault(assignment['TaskID'], []).append(assignment)
            for identifier, values in assignments.items():
                if identifier not in self.deleted['tasks']:
                    update('tasks', identifier, {'task_id': identifier, 'assignments': values,
                                               'request_id': f['CorrespondingAutomationRequestID']})
        elif name == 'AutomationResponse':
            for command in f['MissionCommandList']:
                identifier = command['VehicleID']
                require(identifier in self.entity_ids, 'Plan references unknown entity')
                if identifier not in self.deleted['entities']:
                    update('routes', identifier, {'entity_id': identifier, 'command_id': command['CommandID'],
                                                 'planned_mission': command})
        elif name in ('MissionCommand', 'VehicleActionCommand'):
            identifier = f['VehicleID']
            require(identifier in self.entity_ids, 'Command references unknown entity')
            if identifier not in self.deleted['entities']:
                kind = 'mission' if name == 'MissionCommand' else 'action'
                identifier_key = identifier + ':' + kind
                prior = self.data['commands'].get(identifier_key, {})
                # Exact resends keep execution evidence; a new segment starts unobserved.
                if prior.get('message') != f:
                    update('commands', identifier_key, {'entity_id': identifier, 'command_id': f['CommandID'],
                                                       'kind': kind, 'received': True, 'execution_observed': False,
                                                       'execution_time_ms': None, 'current_waypoint_id': None, 'message': f})
        elif name in ('KeepInZone', 'KeepOutZone', 'OperatingRegion'):
            identifier = ('region:' + f['ID']) if name == 'OperatingRegion' else f['ZoneID']
            if identifier not in self.deleted['zones']:
                update('zones', identifier, {'kind': name, 'definition': f})
        elif name in ('RemoveEntities', 'RemoveTasks', 'RemoveZones'):
            collection, field = {'RemoveEntities': ('entities', 'EntityList'), 'RemoveTasks': ('tasks', 'TaskList'),
                                 'RemoveZones': ('zones', 'ZoneList')}[name]
            for identifier in f[field]:
                delete(collection, identifier)
                if collection == 'entities':
                    for dependent, keys in (('routes', [identifier]), ('commands', [identifier + ':mission', identifier + ':action'])):
                        for dependent_key in keys:
                            if dependent_key in self.data[dependent]:
                                self.data[dependent].pop(dependent_key)
                                changes.append({'collection': dependent, 'id': dependent_key, 'op': 'delete'})
        self.cursor = key
        if changes:
            self.sequence += 1
        return changes
