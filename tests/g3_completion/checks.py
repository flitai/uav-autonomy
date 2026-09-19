"""Offline mutations of real evidence. Never inject synthetic completion into AMASE."""
import base64
import copy
import json
import xml.etree.ElementTree as ET


def verify(task, completion, coverage):
    folder = task.run/'headless'
    read = lambda p: [json.loads(line) for line in p.read_text(encoding='utf-8').splitlines()]
    bus, monitor, events = read(folder/'observer.jsonl'), read(folder/'amase.jsonl'), read(folder/'amase/events.jsonl')
    navigation = [r for p in sorted((folder/'amase').glob('execution-*.jsonl')) for r in read(p)]
    request = ET.fromstring(task.input_message('request').toXMLStr(''))
    results = []
    def reject(name, callback, reason):
        try: callback()
        except (RuntimeError, ValueError, TypeError) as error:
            if reason not in str(error): raise RuntimeError(name+': unexpected diagnostic: '+str(error)) from error
            results.append(dict(name=name, status='passed', rejectedReason=str(error)))
        else: raise RuntimeError('Counterexample accepted: '+name)
    assess = lambda b=bus,n=navigation: completion.assess(b, monitor, events, task.policy, request, n)
    assess(); results.append(dict(name='unaltered-real-evidence', status='passed'))
    completion_index = next(i for i,r in enumerate(bus) if r['type'] == 'uxas.messages.task.TaskComplete')
    row = bus[completion_index]
    def changed(field, text):
        node = completion.xml(row); node.find(field).text = text
        return bus[:completion_index]+[dict(row, xmlBase64=base64.b64encode(ET.tostring(node)).decode('ascii'))]+bus[completion_index+1:]
    reject('missing-completion', lambda: assess([r for r in bus if r is not row]), 'completion-missing')
    reject('duplicate-completion', lambda: assess(bus+[row]), 'completion-missing-or-duplicate')
    reject('wrong-completed-task', lambda: assess(changed('TaskID', '1001')), 'completion-source-or-task')
    reject('wrong-completed-entity', lambda: assess(changed('EntitiesInvolved/int64', '500')), 'completion-entities')
    reject('premature-completion', lambda: assess(changed('TimeTaskCompleted', '100000')), 'completion-before-terminal')
    good = json.loads((folder/'completion.json').read_text(encoding='utf-8'))
    terminal = good['entities'][0]['terminalWaypoint']
    successor = good['entities'][0]['successorWaypoint']
    assigned = good['entities'][0]['entityId']
    reject('missing-terminal-navigation', lambda: assess(n=[r for r in navigation if not
           (r['entityId']==assigned and r['waypoint']==successor and r['waypointReached']==terminal)]), 'completion-terminal-navigation-missing')
    reject('missing-task-target', lambda: assess(n=[r for r in navigation if not
           (r['entityId']==assigned and r['waypoint']==terminal)]), 'completion-task-waypoints-incomplete')
    terminal_nodes = [r for r in navigation if r['entityId']==assigned and r['waypoint']==terminal]
    stationary = [dict(r,position=terminal_nodes[0]['position']) if r in terminal_nodes else r for r in navigation]
    reject('stationary-terminal-leg', lambda: assess(n=stationary), 'completion-terminal-leg-not-executed')
    no_off = [r for r in bus if not (r['type']=='afrl.cmasi.AirVehicleState' and
        completion.xml(r).findtext('ID')==assigned and completion.xml(r).findtext('CurrentWaypoint')==successor)]
    reject('missing-terminal-public-state', lambda: assess(no_off), 'completion-terminal-state-missing')
    report = ET.parse(folder/'amase/analysis.xml').getroot()
    details = ET.parse(folder/'amase/coverage-cells.xml').getroot()
    expected = coverage.grid(ET.parse(task.root/task.config['task']).getroot())
    coverage.inspect(report, details, expected)
    def report_changed(field, value):
        r = copy.deepcopy(report); r.find('.//SearchLine/'+field).text = value; return r
    reject('empty-statistics', lambda: coverage.inspect(report_changed('TotalCells','0'), details, expected), 'coverage-count-range')
    reject('seen-greater-than-total', lambda: coverage.inspect(report_changed('SeenCells',str(len(expected)+1)), details, expected), 'coverage-count-range')
    reject('negative-seen', lambda: coverage.inspect(report_changed('SeenCells','-1'), details, expected), 'coverage-count-range')
    reject('wrong-report-percent', lambda: coverage.inspect(report_changed('CoveragePercent','-1'), details, expected), 'coverage-report-percent')
    missing = copy.deepcopy(details); missing.find('Task').remove(missing.find('Task/Cell'))
    reject('missing-cell-export', lambda: coverage.inspect(report, missing, expected), 'coverage-cell-export-incomplete')
    bad = copy.deepcopy(details); bad.find('Task/Cell').set('latitude', '0')
    reject('wrong-cell-coordinate', lambda: coverage.inspect(report, bad, expected), 'coverage-cell-coordinate')
    wrong = copy.deepcopy(report); wrong.find('.//SearchLine').set('ID', '999')
    reject('wrong-report-task', lambda: coverage.inspect(wrong, details, expected), 'coverage-task-report-missing')
    flipped = copy.deepcopy(details)
    cell = flipped.find('Task/Cell'); cell.set('seen', 'false' if cell.get('seen') == 'true' else 'true')
    reject('raw-seen-count-mismatch', lambda: coverage.inspect(report, flipped, expected), 'coverage-seen-count')
    # A valid zero result passes the arithmetic/export gate: there is no score floor.
    zero_report, zero_cells = copy.deepcopy(report), copy.deepcopy(details)
    zero_report.find('.//SearchLine/SeenCells').text = '0'
    zero_report.find('.//SearchLine/CoveragePercent').text = '0'
    for cell in zero_cells.findall('Task/Cell'): cell.set('seen', 'false')
    coverage.inspect(zero_report, zero_cells, expected)
    results.append(dict(name='valid-zero-coverage-has-no-threshold', status='passed'))
    return results
