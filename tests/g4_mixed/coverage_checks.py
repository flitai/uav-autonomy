"""Tampered statistics and zero-observation boundary using isolated real samples."""
import base64
from copy import deepcopy
import shutil
import xml.etree.ElementTree as ET


def verify(root,coverage,source,output,assignments):
    output.mkdir(); checks=[]
    def copy_case(name):
        target=output/name; (target/'amase').mkdir(parents=True); (target/'scene').mkdir()
        for file in ('analysis.xml','coverage-cells.xml','analysis-events.tsv'): shutil.copyfile(source/'amase'/file,target/'amase'/file)
        for row in assignments: shutil.copyfile(source/'scene'/row['taskFile'],target/'scene'/row['taskFile'])
        return target
    def rejects(name,mutate):
        target=copy_case(name); mutate(target)
        try: coverage.inspect(root,target,assignments)
        except (ValueError,RuntimeError,AssertionError): checks.append(name)
        else: raise AssertionError('Corrupt statistics accepted: '+name)
    def report(target):
        path=target/'amase/analysis.xml'; tree=ET.parse(path)
        tree.find('.//TimeSeenSec').text='750'; tree.write(path,encoding='utf-8')
    rejects('milliseconds-mislabeled-as-seconds',report)
    def coordinate(target):
        path=target/'amase/coverage-cells.xml'; tree=ET.parse(path)
        cell=tree.find('.//Cell'); cell.set('latitude',str(float(cell.get('latitude'))+.01)); tree.write(path,encoding='utf-8')
    rejects('wrong-coverage-location',coordinate)
    target=copy_case('zero-observation-is-allowed')
    report=ET.parse(target/'amase/analysis.xml'); report.find('.//TimeSeenSec').text='0'; report.write(target/'amase/analysis.xml',encoding='utf-8')
    cells=ET.parse(target/'amase/coverage-cells.xml'); cells.find('.//Cell').set('seen','false'); cells.write(target/'amase/coverage-cells.xml',encoding='utf-8')
    transformed=[]
    for line in (target/'amase/analysis-events.tsv').read_text().splitlines():
        time,encoded=line.split('\t',1); node=ET.fromstring(base64.b64decode(encoded))
        if node.tag=='AirVehicleState':
            for location in node.findall('PayloadStateList/CameraState/Footprint/Location3D'):
                location.find('Latitude').text='0'; location.find('Longitude').text='0'
        transformed.append(time+'\t'+base64.b64encode(ET.tostring(node,encoding='utf-8')).decode())
    (target/'amase/analysis-events.tsv').write_text('\n'.join(transformed)+'\n',encoding='utf-8')
    result=coverage.inspect(root,target,assignments)
    assert result['tasks'][0]['observationMilliseconds']=='0' and result['tasks'][0]['contributingEntities']==[]
    checks.append('zero-observation-is-allowed')
    target=copy_case('incidental-observation-keeps-assignment-separate')
    transformed=[]
    for line in (target/'amase/analysis-events.tsv').read_text().splitlines():
        time,encoded=line.split('\t',1); node=ET.fromstring(base64.b64decode(encoded))
        if node.tag in ('AirVehicleConfiguration','AirVehicleState'):
            assert node.findtext('ID')=='400'; node.find('ID').text='500'
        transformed.append(time+'\t'+base64.b64encode(ET.tostring(node,encoding='utf-8')).decode())
    (target/'amase/analysis-events.tsv').write_text('\n'.join(transformed)+'\n',encoding='utf-8')
    incidental=coverage.inspect(root,target,assignments)['tasks'][0]
    original=coverage.inspect(root,source,assignments)['tasks'][0]
    assert incidental['observationMilliseconds']==original['observationMilliseconds']
    assert incidental['assignedEntityObservationMilliseconds']=='0' and incidental['contributingEntities']==['500']
    assert incidental['observationMillisecondsByEntity']['500']==original['observationMilliseconds']
    checks.append('incidental-observation-keeps-assignment-separate')
    return {'status':'passed','checks':checks,'isolatedCopies':True}
