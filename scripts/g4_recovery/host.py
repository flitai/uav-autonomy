"""Run-owned gateway process host; backend lifecycle is controlled elsewhere."""
import hashlib
import json
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from sim_bridge.codec import require
from sim_bridge.journal import Journal
from sim_bridge.windows import main_connection, process_identity


def save(path, value):
    path.write_text(json.dumps(value, indent=2), encoding='utf-8')


class GatewayHost:
    def __init__(self, owner, python, schema, ports, main_port=None):
        self.owner, self.python = owner, python
        self.directory = owner.directory / 'gateway-host'; self.directory.mkdir()
        self.instances, self.current, self.records = [], None, []
        self.url = 'http://127.0.0.1:8000'
        binding = {'run_id': owner.args.run_id + '/' + owner.item['name'],
                   'log_directory': str(owner.cpp_dir / 'datawork/SavedMessages')}
        path = self.directory / 'anchor-binding.json'; save(path, binding)
        journal = Journal(path, binding['run_id'], schema, ['400', '500'])
        manifest = {'schema_version': 1, **binding, 'entity_ids': ['400', '500'], 'ports': ports,
                    'processes': [process_identity(owner.java_process.pid), process_identity(owner.cpp.pid)],
                    'main_connection': main_connection(owner.cpp.pid, main_port or owner.ports['amasePort']),
                    'journal_anchors': journal.anchors(), 'ledger_path': str(self.directory / 'normalized-events.db3'),
                    'uxas_stdout': str(owner.cpp_dir / 'stdout.log'), 'baseline_run_id': owner.context['baselineRunId']}
        self.manifest_path = self.directory / 'manifest.json'; save(self.manifest_path, manifest)
        self.manifest = manifest

    def start(self):
        self.owner.amase.check_port(8000)
        directory = self.directory / ('instance-' + str(len(self.instances) + 1)); directory.mkdir()
        output = directory / 'observer'
        argv = [str(self.python), '-I', '-B', '-X', 'utf8', str(self.owner.root / 'apps/gis_gateway/server.py'),
                '--root', str(self.owner.root), '--manifest', str(self.manifest_path), '--manifest-sha256',
                hashlib.sha256(self.manifest_path.read_bytes()).hexdigest(), '--output', str(output)]
        # Keep independently restartable gateway children outside the backend
        # host's all-processes-must-stay-alive list.
        with (directory / 'stdout.log').open('wb') as stdout, (directory / 'stderr.log').open('wb') as stderr:
            process = subprocess.Popen(argv, cwd=directory, stdout=stdout, stderr=stderr,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
        item = {'pid': str(process.pid), 'arguments': argv, 'forced_termination': False}
        self.current = (directory, output, process, item); self.instances.append(self.current)
        self.wait(lambda: self.health(), 'HTTP listening', 20)
        return self.current

    def request(self, suffix):
        try:
            with urlopen(self.url + suffix, timeout=2) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def health(self):
        try:
            status, value = self.request('/api/v1/health')
            require(status == 200 and value['run_id'] == self.manifest['run_id'], 'Gateway HTTP ownership differs')
            return value
        except URLError:
            return None

    def wait(self, predicate, label, seconds=30, backend_alive=True):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if backend_alive: self.owner.alive()
            require(self.current[2].poll() is None, 'Gateway process exited before ' + label)
            value = predicate()
            if value: return value
            time.sleep(.1)
        raise RuntimeError('Gateway timeout: ' + label)

    def live(self):
        def ready():
            value = self.health()
            require(value and value['error'] is None, 'Gateway degraded: ' + str(value))
            return value if value['ready'] else None
        value = self.wait(ready, 'complete live snapshot', 40)
        status, snapshot = self.request('/api/v1/snapshot')
        require(status == 200 and snapshot['stream_id'] == value['stream_id'], 'Snapshot changed at ready check')
        return snapshot

    def stop(self, expected=0):
        if self.current is None: return
        directory, output, process, item = self.current
        if output.is_dir(): (output / 'request-stop').touch()
        try: process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            item['forced_termination'] = True; process.kill(); process.wait(timeout=10)
        item['exit_code'] = process.returncode
        save(directory / 'process.json', item)
        require(not item['forced_termination'] and process.returncode == expected, 'Gateway shutdown failed: ' + str(item))
        result = json.loads((output / 'result.json').read_text(encoding='utf-8'))
        require(result['status'] == ('passed' if expected == 0 else 'failed'), 'Gateway receipt differs')
        self.records.append(result)
        self.owner.amase.check_port(8000)
        self.current = None
