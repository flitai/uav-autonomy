"""Render the actual diagnostic page in an isolated native Edge instance."""
import argparse
import asyncio
import base64
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib.error import URLError
from urllib.request import urlopen

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed


class DevTools:
    def __init__(self, websocket):
        self.websocket, self.sequence, self.errors = websocket, 0, []

    async def call(self, method, params=None, session=None):
        self.sequence += 1
        message = {'id': self.sequence, 'method': method, 'params': params or {}}
        if session: message['sessionId'] = session
        await self.websocket.send(json.dumps(message))
        while True:
            reply = json.loads(await asyncio.wait_for(self.websocket.recv(), 10))
            if reply.get('method') == 'Runtime.exceptionThrown': self.errors.append(reply)
            if reply.get('id') == self.sequence:
                assert 'error' not in reply, reply
                return reply.get('result', {})


async def verify(url, directory):
    directory.mkdir(parents=True)
    edge = Path(os.environ['ProgramFiles(x86)']) / 'Microsoft/Edge/Application/msedge.exe'
    assert edge.is_file(), 'Native Edge is required for diagnostic-page qualification'
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 9222))  # Explicit test port; conflicts fail rather than switching.
    arguments = [str(edge), '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
                 '--disable-background-networking', '--disable-background-mode', '--disable-extensions',
                 '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=9222',
                 '--window-size=1280,900', '--user-data-dir=' + str(directory / 'profile'), 'about:blank']
    with (directory / 'stdout.log').open('wb') as stdout, (directory / 'stderr.log').open('wb') as stderr:
        process = subprocess.Popen(arguments, stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW)
        websocket, devtools, result = None, None, {'status': 'running', 'pid': str(process.pid)}
        try:
            deadline = time.monotonic() + 20
            version = None
            while time.monotonic() < deadline:
                assert process.poll() is None, 'Edge exited before debugging was ready'
                try:
                    with urlopen('http://127.0.0.1:9222/json/version', timeout=.5) as response: version = json.load(response)
                    break
                except URLError:
                    await asyncio.sleep(.1)
            assert version is not None, 'Edge debugging endpoint timed out'
            websocket = await connect(version['webSocketDebuggerUrl'], max_size=8388608)
            devtools = DevTools(websocket)
            target = await devtools.call('Target.createTarget', {'url': 'about:blank'})
            session = (await devtools.call('Target.attachToTarget', {'targetId': target['targetId'], 'flatten': True}))['sessionId']
            await devtools.call('Runtime.enable', session=session)
            await devtools.call('Page.enable', session=session)
            await devtools.call('Page.navigate', {'url': url}, session)
            expression = '''(()=>({title:document.title, connection:document.getElementById('connection')?.textContent,
                entities:document.querySelectorAll('#entities tr').length, tasks:document.querySelectorAll('#tasks tr').length,
                assignedEntity:document.querySelector('#tasks tr td:nth-child(4)')?.textContent,
                sequence:typeof sequence==='bigint'?String(sequence):null,
                timeOrigin:performance.timeOrigin, identity:document.getElementById('identity')?.textContent}))()'''
            async def rendered(previous_origin=None):
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    reply = await devtools.call('Runtime.evaluate', {'expression': expression, 'returnByValue': True}, session)
                    value = reply.get('result', {}).get('value', {})
                    if (value.get('entities') == 2 and value.get('tasks') == 1 and value.get('assignedEntity') == '400'
                            and '已同步' in value.get('connection', '')
                            and value.get('timeOrigin') != previous_origin):
                        return value
                    await asyncio.sleep(.1)
                raise AssertionError('Diagnostic page did not render live entities/tasks')
            initial = await rendered()
            await devtools.call('Page.reload', {'ignoreCache': True}, session)
            refreshed = await rendered(initial['timeOrigin'])
            assert int(refreshed['sequence']) >= int(initial['sequence']) and refreshed['identity'] == initial['identity']
            screenshot = await devtools.call('Page.captureScreenshot', {'format': 'png'}, session)
            (directory / 'diagnostic.png').write_bytes(base64.b64decode(screenshot['data']))
            assert not devtools.errors, 'Browser JavaScript exception'
            result.update(status='passed', browser=version['Browser'], initial=initial, refreshed=refreshed,
                          javascriptErrors=devtools.errors, isolatedProfile=True)
        except BaseException as error:
            result.update(status='failed', error=str(error)); raise
        finally:
            if devtools is not None:
                try: await devtools.call('Browser.close')
                except ConnectionClosed: pass
            if websocket is not None: await websocket.close()
            try:
                process.wait(timeout=30)
                result.update(exitCode=process.returncode, forcedTermination=False)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)
                result.update(status='failed', exitCode=process.returncode, forcedTermination=True)
            released = False
            for _ in range(50):
                try:
                    with socket.create_connection(('127.0.0.1', 9222), timeout=.1): pass
                except OSError:
                    released = True; break
                await asyncio.sleep(.1)
            result['debugPortReleased'] = released
            if not released or result['exitCode'] != 0: result['status'] = 'failed'
            (directory / 'result.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
        assert result['status'] == 'passed', 'Edge shutdown was not normal'
        print('Native Edge page, refresh, JavaScript and normal shutdown passed', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--url', required=True); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); asyncio.run(verify(args.url, args.output))
