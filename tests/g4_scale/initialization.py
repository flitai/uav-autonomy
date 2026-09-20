"""Check real service-creation messages against MDM bounds and task eligibility."""
from contextlib import closing
import html
import json
from pathlib import Path
import sqlite3
import sys
import xml.etree.ElementTree as ET


def inspect(root,directory):
    sys.path.insert(0,str(root/'src'))
    from sim_bridge.codec import load_schema
    from sim_bridge.journal import xml_object
    schema=load_schema(root);scene=json.loads((directory/'scene/scene.json').read_text())
    assignments={r['taskId']:r['entityId'] for r in scene['assignments']};seen={}
    for path in sorted((directory/'uxas/datawork/SavedMessages').glob('messageLog_*.db3')):
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as database:
            for row,xml in database.execute("SELECT id,xml FROM msg WHERE descriptor='uxas.messages.uxnative.CreateNewService' ORDER BY id"):
                node=ET.fromstring(xml);xml_object(node,schema)
                service=ET.fromstring(html.unescape(node.findtext('XmlConfiguration'))+'</Service>')
                task=service.find('TaskRequest/*');task_id=task.findtext('TaskID')
                assert task_id in assignments and task_id not in seen,'Unexpected or duplicate task creation'
                eligible=[n.text for n in task.findall('EligibleEntities/int64')]
                configs=[n.findtext('ID') for n in node.findall('EntityConfigurations/*')]
                states=[n.findtext('ID') for n in node.findall('EntityStates/*')]
                assert configs==states==eligible==[assignments[task_id]],'Service initialization not restricted to assigned entity'
                seen[task_id]={'entityId':eligible[0],'configurationCount':len(configs),'stateCount':len(states),
                               'shard':path.name,'row':str(row)}
    assert set(seen)==set(assignments),'Missing service initialization'
    return {'status':'passed','tasks':seen,'modelArrayLimit':16}
