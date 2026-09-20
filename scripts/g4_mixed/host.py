"""Generic entity manifest for the existing independently owned gateway host."""
import importlib.util
from pathlib import Path

spec=importlib.util.spec_from_file_location('mixed_gateway_host',Path(__file__).parents[1]/'g4_recovery/host.py')
host=importlib.util.module_from_spec(spec); spec.loader.exec_module(host)
from sim_bridge.journal import Journal
from sim_bridge.windows import main_connection, process_identity


class GatewayHost(host.GatewayHost):
    def __init__(self,owner,python,schema,ports):
        self.owner,self.python=owner,python
        self.directory=owner.directory/'gateway-host'; self.directory.mkdir()
        self.instances,self.current,self.records=[],None,[]; self.url='http://127.0.0.1:8000'
        ids=[r['entityId'] for r in owner.scene['assignments']]
        binding={'run_id':owner.args.run_id+'/'+owner.item['name'],'log_directory':str(owner.cpp_dir/'datawork/SavedMessages')}
        path=self.directory/'anchor-binding.json'; host.save(path,binding)
        journal=Journal(path,binding['run_id'],schema,ids)
        self.manifest={'schema_version':1,**binding,'entity_ids':ids,'ports':ports,
            'processes':[process_identity(owner.java_process.pid),process_identity(owner.cpp.pid)],
            'main_connection':main_connection(owner.cpp.pid,owner.ports['amasePort']),
            'journal_anchors':journal.anchors(),'ledger_path':str(self.directory/'normalized-events.db3'),
            'uxas_stdout':str(owner.cpp_dir/'stdout.log'),'baseline_run_id':owner.context['baselineRunId'],
            'amase_build_run_id':owner.record['amaseBuildRunId'],'artifacts':owner.record['artifacts'],
            'stage_qualified':False}
        self.manifest_path=self.directory/'manifest.json'; host.save(self.manifest_path,self.manifest)
