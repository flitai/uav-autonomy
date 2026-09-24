"""Real Edge controls G6-A03, using the Cesium page and its actual HTTP API."""
import argparse
import asyncio
import base64
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import traceback
from urllib.request import urlopen
from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('g6_browser_cdp', ROOT / 'tests/g5_entities/browser.py')
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)


async def verify(directory, scenario='basic', stop_file=None):
    directory.mkdir(parents=True)
    edge = Path(os.environ['ProgramFiles(x86)']) / 'Microsoft/Edge/Application/msedge.exe'
    with socket.socket() as port:
        port.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        port.bind(('127.0.0.1', 9223))
    arguments = [str(edge), '--headless=new', '--no-first-run', '--no-default-browser-check',
                 '--disable-background-networking', '--disable-background-mode', '--disable-extensions',
                 '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost',
                 '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=9223',
                 '--window-size=1440,1100', '--user-data-dir=' + str(directory / 'profile'), 'about:blank']
    result = {'task': 'G6-A04' if scenario == 'reset' else 'G6-A03',
              'status': 'running', 'browser': 'Microsoft Edge', 'steps': []}
    process = ws = cdp = None
    with (directory / 'stdout.log').open('wb') as stdout, (directory / 'stderr.log').open('wb') as stderr:
        try:
            process = subprocess.Popen(arguments, stdout=stdout, stderr=stderr,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            deadline = time.monotonic() + 25
            version = None
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError('Edge exited before CDP ready')
                try:
                    with urlopen('http://127.0.0.1:9223/json/version', timeout=.5) as response:
                        version = json.load(response)
                    break
                except OSError:
                    await asyncio.sleep(.1)
            if not version:
                raise RuntimeError('Edge CDP not ready')
            ws = await connect(version['webSocketDebuggerUrl'], max_size=64 * 1024 * 1024)
            cdp = previous.DevTools(ws)
            target = await cdp.call('Target.createTarget', {'url': 'about:blank'})
            session = (await cdp.call('Target.attachToTarget',
                {'targetId': target['targetId'], 'flatten': True}))['sessionId']
            for method in ('Page.enable', 'Runtime.enable', 'Network.enable'):
                await cdp.call(method, session=session)
            await cdp.call('Page.navigate', {'url': 'http://127.0.0.1:8080/'}, session=session)

            async def evaluate(expression):
                answer = await cdp.call('Runtime.evaluate',
                    {'expression': expression, 'returnByValue': True, 'awaitPromise': True}, session=session)
                if answer.get('exceptionDetails'):
                    raise RuntimeError('Browser expression failed: ' + str(answer['exceptionDetails']))
                return answer.get('result', {}).get('value')

            async def until(expression, predicate, seconds=30):
                deadline = time.monotonic() + seconds
                last = None
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError('Edge exited during control run')
                    last = await evaluate(expression)
                    if predicate(last):
                        return last
                    await asyncio.sleep(.15)
                raise RuntimeError('Browser control timeout: ' + expression + ' last=' + str(last))

            def state_expression():
                return """(()=>{const p=document.getElementById('simulation-controls');
                  const s=window.__g5State?.inspect();return {panel:!!p,backend:document.documentElement.dataset.backendReady,
                  state:p?.querySelector('p')?.textContent,time:p?.querySelectorAll('p')[1]?.textContent,
                  result:p?.querySelectorAll('p')[2]?.textContent,progress:p?.querySelector('progress')?.value,
                  progressHidden:p?.querySelector('progress')?.hidden,
                  startDisabled:document.getElementById('control-start')?.disabled,
                  pauseDisabled:document.getElementById('control-pause')?.disabled,
                  resumeDisabled:document.getElementById('control-resume')?.disabled,
                  resetDisabled:document.getElementById('control-reset')?.disabled,
                  rateDisabled:document.getElementById('control-set-rate')?.disabled,
                  runId:s?.identity?.run_id,streamId:s?.identity?.stream_id,
                  simulation:s?.state?.simulation};})()"""

            if scenario == 'degrade':
                initial = await until(state_expression(),
                    lambda v: v and v.get('panel') and v.get('backend') == 'true' and
                    v.get('resetDisabled') is False, 45)
                result['steps'].append({'action': 'control-ready', 'state': initial})
                if stop_file is None:
                    raise RuntimeError('Control stop marker missing')
                stop_file.touch()
                degraded = await until(state_expression(), lambda v: v and
                    '控制后端不可用' in (v.get('state') or '') and
                    all(v.get(name) is True for name in ('startDisabled', 'pauseDisabled',
                                                         'resumeDisabled', 'resetDisabled', 'rateDisabled')), 20)
                result['steps'].append({'action': 'api-disconnected', 'state': degraded})
                result['status'] = 'passed'
                return result

            if scenario == 'reset':
                initial = await until(state_expression(),
                    lambda v: v and v.get('panel') and v.get('startDisabled') is False, 45)
                result['steps'].append({'action': 'initial', 'state': initial})
                await evaluate("document.getElementById('control-start').click()")
                first = await until(state_expression(), lambda v: v and v.get('backend') == 'true' and
                    v.get('resetDisabled') is False and '开始：后端已确认' in (v.get('result') or ''), 40)
                result['steps'].append({'action': 'first-start', 'state': first})
                await evaluate("document.getElementById('control-reset').click()")
                restored = await until(state_expression(), lambda v: v and v.get('panel') and
                    v.get('startDisabled') is False and v.get('progressHidden') is True and
                    '重置：后端已确认' in (v.get('result') or ''), 100)
                result['steps'].append({'action': 'reset-restored', 'state': restored})
                await evaluate("document.getElementById('control-start').click()")
                second = await until(state_expression(), lambda v: v and v.get('backend') == 'true' and
                    v.get('runId') and v.get('runId') != first['runId'] and
                    v.get('pauseDisabled') is False and
                    '开始：后端已确认' in (v.get('result') or ''), 40)
                result['steps'].append({'action': 'second-start', 'state': second})
                await evaluate("document.getElementById('control-pause').click()")
                paused = await until(state_expression(), lambda v: v and v.get('resumeDisabled') is False and
                    '暂停：后端已确认' in (v.get('result') or ''), 20)
                result['steps'].append({'action': 'second-pause', 'state': paused})
                screenshot = await cdp.call('Page.captureScreenshot', {'format': 'png'}, session=session)
                (directory / 'controls.png').write_bytes(base64.b64decode(screenshot['data']))
                result['status'] = 'passed'
                return result

            initial = await until(state_expression(),
                lambda v: v and v['panel'] and v['startDisabled'] is False, 45)
            result['steps'].append({'action': 'initial', 'state': initial})
            await evaluate("document.getElementById('control-start').click()")
            started = await until(state_expression(), lambda v: v and v['backend'] == 'true' and
                                  v['pauseDisabled'] is False and '后端已确认' in (v['result'] or ''), 40)
            result['steps'].append({'action': 'start', 'state': started})
            await evaluate("document.getElementById('control-pause').click()")
            paused = await until(state_expression(), lambda v: v and v['resumeDisabled'] is False and
                                 '后端已确认' in (v['result'] or '') and '暂停' in (v['time'] or ''), 15)
            result['steps'].append({'action': 'pause', 'state': paused})
            await evaluate("document.getElementById('control-rate').value='2';document.getElementById('control-set-rate').click()")
            await until(state_expression(), lambda v: v and '倍率：已受理' in (v['result'] or '') and
                        v['resumeDisabled'] is False, 15)
            await evaluate("document.getElementById('control-resume').click()")
            resumed = await until(state_expression(), lambda v: v and v['pauseDisabled'] is False and
                                  '2×' in (v['time'] or '') and '后端已确认' in (v['result'] or ''), 20)
            result['steps'].append({'action': 'resume-2x', 'state': resumed})
            await evaluate("document.getElementById('control-rate').value='0.5';document.getElementById('control-set-rate').click()")
            slower = await until(state_expression(), lambda v: v and '0.5×' in (v['time'] or '') and
                                 '后端已确认' in (v['result'] or ''), 20)
            result['steps'].append({'action': 'rate-0.5x', 'state': slower})
            await evaluate("document.getElementById('control-pause').click()")
            final = await until(state_expression(), lambda v: v and v['resumeDisabled'] is False and
                                '暂停' in (v['time'] or '') and '后端已确认' in (v['result'] or ''), 15)
            result['steps'].append({'action': 'final-pause', 'state': final})
            if final['progressHidden'] or not 0 < final['progress'] < 1000:
                raise RuntimeError('Read-only progress did not show the qualified scenario time')
            if not final['runId'] or not final['streamId']:
                raise RuntimeError('Browser did not bind the real G4 stream')
            await cdp.call('Page.reload', {'ignoreCache': True}, session=session)
            restored = await until(state_expression(), lambda v: v and v.get('backend') == 'true' and
                                   v.get('runId') == final['runId'] and v.get('streamId') == final['streamId'] and
                                   v['resumeDisabled'] is False and
                                   '操作 000000000006' in (v['result'] or ''), 40)
            result['steps'].append({'action': 'refresh-restored', 'state': restored})
            screenshot = await cdp.call('Page.captureScreenshot', {'format': 'png'}, session=session)
            (directory / 'controls.png').write_bytes(base64.b64decode(screenshot['data']))
            result['status'] = 'passed'
        except Exception as error:
            result.update(status='failed', error=str(error), traceback=traceback.format_exc())
        finally:
            if cdp is not None:
                try:
                    await cdp.call('Browser.close')
                except Exception:
                    pass
            if ws is not None:
                await ws.close()
            if process is not None:
                try:
                    process.wait(timeout=30)
                    result.update(exitCode=process.returncode, forcedTermination=False)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    result.update(status='failed', forcedTermination=True)
            (directory / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--scenario', choices=('basic', 'reset', 'degrade'), default='basic')
    parser.add_argument('--stop-file', type=Path)
    args = parser.parse_args()
    result = asyncio.run(verify(args.output.resolve(), args.scenario, args.stop_file))
    print('G6_BROWSER_STATUS=' + result['status'], flush=True)
    return 0 if result['status'] == 'passed' and result.get('exitCode') == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
