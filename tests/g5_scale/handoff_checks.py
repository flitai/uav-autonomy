"""Negative controls for a real one-message public segment receipt transient."""
import argparse
import base64
import importlib.util
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def rows(path):return [json.loads(line) for line in path.open(encoding='utf-8')]


def main(root,run_id):
    helper=module('scale_handoff_checks',root/'tests/g5_scale/handoff.py')
    directory=root/'out/runs'/run_id/'scale-headless'
    assignments=json.loads((directory/'scene/scene.json').read_text(encoding='utf-8'))['assignments']
    bus=rows(directory/'observer.jsonl');wire=rows(directory/'amase.jsonl')
    events=rows(directory/'amase/events.jsonl')
    navigation=[row for path in sorted((directory/'amase').glob('execution-*.jsonl')) for row in rows(path)]
    _,_,episodes=helper.normalize(root,bus,wire,events,navigation,assignments)
    published=[value for group in episodes.values() for episode in group
               for value in episode.get('publicReceiptStates',[])]
    if not published:raise RuntimeError('Expected a real public transient fixture')
    target=published[0]['rawSHA256']
    index=next(i for i,row in enumerate(bus) if row.get('rawSHA256')==target)
    checks=[]
    def rejected(name,changed_bus,changed_wire,expected):
        try:helper.normalize(root,changed_bus,changed_wire,events,navigation,assignments)
        except RuntimeError as error:
            if expected not in str(error):raise
            checks.append(name);return
        raise RuntimeError('Unsafe public overlap passed: '+name)
    def changed_node(edit):
        changed=list(bus);node=ET.fromstring(base64.b64decode(bus[index]['xmlBase64']))
        edit(node)
        changed[index]=dict(bus[index],xmlBase64=base64.b64encode(ET.tostring(node)).decode('ascii'))
        return changed
    def task_reentry(node):ET.SubElement(node.find('AssociatedTasks'),'int64').text='3000'
    rejected('task-reentry',changed_node(task_reentry),wire,'Public overlap entered task or action')
    def jump(node):
        latitude=node.find('Location/Location3D/Latitude');latitude.text=str(float(latitude.text)+.01)
    rejected('position-jump',changed_node(jump),wire,'Public overlap moved away from actual trajectory')
    rejected('repeated-public-state',bus+[bus[index]],wire,'Repeated public overlap state')
    rejected('missing-wire-state',bus,[row for row in wire if row.get('rawSHA256')!=target],
             'Public overlap missing or duplicated on AMASE wire')
    print(json.dumps(dict(status='passed',runId=run_id,publicTransientSHA256=target,
                          rejected=checks),indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--run-id',required=True);args=parser.parse_args()
    main(args.root.resolve(),args.run_id)
