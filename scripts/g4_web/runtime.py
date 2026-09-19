"""G4-T04 real browser-interface qualification against owned live backends."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback
from urllib.error import URLError
from urllib.request import urlopen


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result); return result


root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / 'src'))
from sim_bridge.windows import process_identity

state_runtime = module('g4_web_state', root / 'scripts/g4_state/runtime.py')
save, sha, require = state_runtime.save, state_runtime.sha, state_runtime.require


class Qualification(state_runtime.Qualification):
    def __init__(self, args):
        super().__init__(args); self.record['task'] = 'G4-T04'; self.gateway_output = None

    def inputs(self):
        paths = [p for directory in ('apps/gis_gateway', 'scripts/g4_web', 'tests/g4_web')
                 for p in (self.root / directory).rglob('*') if p.is_file() and p.suffix in ('.py', '.html')]
        paths += [self.root / p for p in ('scripts/windows/run-g4-web.ps1', 'tests/windows/g4-web.tests.ps1', 'config/g4-gateway.json')]
        return super().inputs() + [{'path': p.relative_to(self.root).as_posix(), 'sha256': sha(p)} for p in sorted(paths)]

    def prepare(self):
        super().prepare()
        self.web_python = state_runtime.ingress.environment.environment(self.root)[0]
        self.web_config = state_runtime.load(self.root / 'config/g4-gateway.json')
        self.web_port = self.web_config['port']
        checks = module('g4_publication_checks', self.root / 'tests/g4_web/publication_checks.py')
        self.record['publicationChecks'] = checks.verify(self.run / 'publication-checks')

    def handshake(self):
        super().handshake()
        self.amase.check_port(self.web_port)
        host = self.directory / 'gateway-host'; host.mkdir()
        self.gateway_output = host / 'observer'
        manifest = {'schema_version': 1, 'run_id': self.binding['run_id'], 'entity_ids': ['400', '500'],
                    'log_directory': self.binding['log_directory'],
                    'ports': {'amase': self.ports['amasePort'], 'uxas': self.ports['observerPort']},
                    'processes': [process_identity(self.java_process.pid), process_identity(self.cpp.pid)],
                    'baseline_run_id': self.context['baselineRunId']}
        path = host / 'manifest.json'; save(path, manifest)
        self.gateway_process = self.launch(host, [str(self.web_python), '-I', '-B', '-X', 'utf8',
            str(self.root / 'apps/gis_gateway/server.py'), '--root', str(self.root), '--manifest', str(path),
            '--manifest-sha256', sha(path), '--output', str(self.gateway_output)])
        def listening():
            try:
                with urlopen('http://127.0.0.1:' + str(self.web_port) + '/api/v1/health', timeout=.5) as response:
                    health = json.load(response)
                    require(health['run_id'] == self.binding['run_id'], 'Different gateway owns the HTTP port')
                    return True
            except URLError:
                return False
        self.wait('gateway-http-listening', listening, 20)

    def body(self, mode, fault, keep_gui):
        super().body(mode, fault, False)
        url = 'http://127.0.0.1:' + str(self.web_port)
        def ready():
            with urlopen(url + '/api/v1/health', timeout=2) as response:
                health = json.load(response)
                require(health['error'] is None, 'Gateway failed: ' + str(health['error']))
                return health['ready']
        self.wait('gateway-live', ready, 20)
        result = subprocess.run([str(self.web_python), '-I', '-B', '-X', 'utf8', str(self.root / 'tests/g4_web/clients.py'),
                                 '--url', url, '--output', str(self.directory / 'browser-clients.json')],
                                capture_output=True, timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
        (self.directory / 'clients.stdout').write_bytes(result.stdout); (self.directory / 'clients.stderr').write_bytes(result.stderr)
        require(result.returncode == 0, 'Real browser client checks failed')
        browser = subprocess.run([str(self.web_python), '-I', '-B', '-X', 'utf8', str(self.root / 'tests/g4_web/browser.py'),
                                  '--url', url, '--output', str(self.directory / 'edge-browser')],
                                 capture_output=True, timeout=100, creationflags=subprocess.CREATE_NO_WINDOW)
        (self.directory / 'browser.stdout').write_bytes(browser.stdout); (self.directory / 'browser.stderr').write_bytes(browser.stderr)
        require(browser.returncode == 0, 'Native diagnostic page check failed')
        self.alive()

    def cleanup(self):
        if self.gateway_output is not None and self.gateway_output.exists():
            (self.gateway_output / 'request-stop').touch()
            if self.gateway_process.poll() is None:
                self.gateway_process.wait(timeout=30)
        # Base cleanup owns the gateway child too; it must already have ended
        # before shutting down the observed backend processes.
        super().cleanup()

    def audit(self):
        super().audit()
        gateway = state_runtime.load(self.gateway_output / 'result.json')
        clients = state_runtime.load(self.directory / 'browser-clients.json')
        require(gateway['status'] == clients['status'] == 'passed', 'Gateway/browser evidence failed')
        require(state_runtime.load(self.directory / 'edge-browser/result.json')['status'] == 'passed', 'Diagnostic page evidence failed')
        require(gateway['sent_business_frames'] == 0, 'Gateway transmitted backend business frames')
        self.amase.check_port(self.web_port)
        self.item['gatewayWeb'] = {'status': 'passed', 'clientCount': len(clients['clients']),
                                   'gateway': gateway, 'httpPortReleased': True}
        save(self.directory / 'web-evidence.json', self.item['gatewayWeb'])
        self.gateway_output = None


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--root', type=Path, required=True); parser.add_argument('--run-id', required=True)
    parser.add_argument('--mode', choices=['Gui', 'Headless'], default='Headless'); parser.add_argument('--verify', action='store_true')
    args = parser.parse_args(); args.keep_gui = False
    require(re.fullmatch(r'g4-t04-[A-Za-z0-9-]+', args.run_id), 'Invalid G4 web run identity')
    task = Qualification(args)
    try:
        task.execute(); task.record['webInterfaceValidated'] = True; return 0
    except Exception as error:
        task.record.update(status='failed', error=str(error), traceback=traceback.format_exc()); print('FAILED: ' + str(error), flush=True); return 1
    finally:
        if task.event_store is not None: task.event_store.close()
        task.record['finishedAt'] = state_runtime.ingress.startup.stamp(); save(task.run / 'result.json', task.record)
        print('G4_T04_EVIDENCE=' + str(task.run), flush=True)


if __name__ == '__main__':
    sys.exit(main())
