import { ReadOnlyConnection } from './connection.js';
import { collections, need, type Limits } from './protocol.js';

const names = { connecting: '正在连接', 'waiting-snapshot': '等待完整快照', live: '已同步', recovering: '恢复中 · 数据已过期', degraded: '后端不可用', ended: '后端已结束', offline: '未连接' };
const panel = document.createElement('section'); panel.id = 'backend-panel'; panel.setAttribute('aria-label', '后端连接');
panel.innerHTML = '<h2>仿真连接</h2><p id="backend-status" role="status">正在读取连接配置…</p><p id="backend-counts"></p><p id="backend-error" role="alert"></p><p class="hint">时间由后端提供，连接恢复时重新同步。</p>';
document.body.append(panel);
const style = document.createElement('style'); style.textContent = '#backend-panel{position:absolute;right:20px;top:76px;width:248px;padding:20px;background:#142630ee;border:1px solid #496574;border-radius:9px;color:#e8eff2}#backend-panel h2{font-size:17px;margin:0 0 18px}#backend-panel p{font-size:13px;line-height:1.7}#backend-error{color:#ffd58c;overflow-wrap:anywhere}@media(max-width:900px){#backend-panel{top:auto;bottom:50px;right:10px;width:210px;padding:12px}}';
document.head.append(style);
const timeElement = document.querySelector('footer span')!; timeElement.id = 'backend-time';
function formatTime(value: unknown): string {
  if (typeof value !== 'string') return '未连接';
  const milliseconds = BigInt(value); return `${milliseconds / 1000n}.${(milliseconds % 1000n).toString().padStart(3, '0')} 秒`;
}
try {
  const response = await fetch('/state/runtime.json', { cache: 'no-store' }); need(response.ok, '连接配置不可用');
  const config = await response.json() as { schemaVersion: number; protocolVersion: number; limits: Limits; terrain: { datum: string } };
  need(config.schemaVersion === 1 && config.protocolVersion === 1 && config.terrain.datum === 'EPSG:5773', '连接配置版本或地形绑定无效');
  const connection = new ReadOnlyConnection(location.origin, config.limits, () => {
    const value = connection.inspect(); document.documentElement.dataset.backendReady = String(value.phase === 'live');
    document.querySelector('#backend-status')!.textContent = names[value.phase];
    document.querySelector('#backend-counts')!.textContent = collections.map((key, i) => ['实体', '任务', '航线', '命令', '区域'][i]+' '+Object.keys(value.state[key]).length).join(' · ');
    document.querySelector('#backend-error')!.textContent = value.error;
    const simulation = value.state.simulation;
    const stateName = ['停止', '运行', '暂停', '重置', '未知'][Number(simulation.state)] ?? '';
    timeElement.textContent = value.phase === 'live' ? `后端时间：${formatTime(simulation.simulation_time_ms)} · ${stateName}` :
      `后端时间：${formatTime(value.lastKnownTime)}${value.lastKnownTime === null ? '' : ' · 已过期'}`;
  });
  // Read-only copies for independent acceptance and future display adapters.
  Object.assign(window, { __g5State: { inspect: () => structuredClone(connection.inspect()), config } });
  window.addEventListener('pagehide', () => { connection.stop(); Object.assign(window, { __g5State: undefined }); }, { once: true });
  connection.start();
} catch (error) { document.querySelector('#backend-status')!.textContent = '连接配置不可用'; document.querySelector('#backend-error')!.textContent = String(error); }
