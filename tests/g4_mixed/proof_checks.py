"""Adversarial changes to real point-flight evidence; original files stay intact."""
import base64
from copy import deepcopy
import json
import xml.etree.ElementTree as ET


def verify(root,execution,inputs):
    original=inputs
    positive=execution.assess(root,*original)
    assert positive['status']=='passed' and positive['tasks'][0]['planningStartAnchor'] is not None
    checks=['real-point-execution-and-planning-anchor']
    def xml(row): return ET.fromstring(base64.b64decode(row['xmlBase64']))
    def replace(row,node): row['xmlBase64']=base64.b64encode(ET.tostring(node,encoding='utf-8')).decode()
    def completion(data,field,value):
        row=next(r for r in data[0] if r['type']=='uxas.messages.task.TaskComplete'); node=xml(row)
        node.find(field).text=value; replace(row,node)
    def run(name,change):
        data=deepcopy(original); change(data)
        try: execution.assess(root,*data)
        except (ValueError,RuntimeError,AssertionError): checks.append(name)
        else: raise AssertionError('Corrupt evidence accepted: '+name)
    run('completion-wrong-entity',lambda d:completion(d,'EntitiesInvolved/int64','500'))
    run('completion-wrong-task',lambda d:completion(d,'TaskID','3001'))
    run('completion-before-arrival',lambda d:completion(d,'TimeTaskCompleted','1'))
    run('completion-duplicate',lambda d:d[0].append(deepcopy(next(r for r in d[0] if r['type']=='uxas.messages.task.TaskComplete'))))
    run('task-active-missing',lambda d:d[0].__setitem__(slice(None),[r for r in d[0] if r['type']!='uxas.messages.task.TaskActive']))
    run('task-target-skipped',lambda d:d[3].__setitem__(slice(None),[r for r in d[3] if r['waypoint']!='4']))
    run('native-terminal-missing',lambda d:d[3].__setitem__(slice(None),[r for r in d[3] if r['waypoint']!='8']))
    def change_first(data):
        for collection in data[:3]:
            for row in collection:
                if 'xmlBase64' not in row: continue
                node=xml(row)
                if node.tag=='MissionCommand' and node.findtext('CommandID')==positive['tasks'][0]['segments'][0]['commandId']:
                    node.find('FirstWaypoint').text='3'; replace(row,node)
    run('only-one-planning-anchor-may-be-skipped',change_first)
    def source(data):
        next(r for r in data[0] if r['type']=='uxas.messages.task.TaskComplete')['sourceEntity']='0'
    run('non-uxas-completion-refused',source)
    return {'status':'passed','checks':checks,'realRecordRetained':True}
