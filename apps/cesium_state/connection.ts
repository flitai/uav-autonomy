import { health, need, type Health, type Limits } from './protocol.js';
import { StateStore } from './store.js';

export type ConnectionPhase = 'connecting' | 'waiting-snapshot' | 'live' | 'recovering' | 'degraded' | 'ended' | 'offline';
export class ReadOnlyConnection {
  readonly store: StateStore; phase: ConnectionPhase = 'connecting'; lastHealth: Health | null = null;
  lastKnownTime: string | null = null; error = ''; snapshots = 0; deltas = 0; attempts = 0; closeCode: number | null = null;
  private socket: WebSocket | null = null; private retry?: ReturnType<typeof setTimeout>;
  private poll?: ReturnType<typeof setTimeout>; private abort?: AbortController; private stopped = true; private epoch = 0;
  private retryDelay = 250; private lastMessage = 0;
  constructor(readonly origin: string, limits: Limits, private readonly changed: () => void) { this.store = new StateStore(limits); }
  start(): void { if (!this.stopped) return; this.stopped = false; this.connect(); }
  stop(): void { this.stopped = true; this.epoch++; clearTimeout(this.retry); clearTimeout(this.poll); this.abort?.abort(); this.socket?.close(); this.socket = null; this.store.clear(); }
  private invalidate(message: string): void {
    const time = this.store.state.simulation.simulation_time_ms;
    if (typeof time === 'string') this.lastKnownTime = time;
    this.store.clear(); this.error = message;
  }
  private connect(): void {
    if (this.stopped) return;
    const epoch = ++this.epoch; this.attempts++; this.invalidate(''); this.lastHealth = null;
    this.phase = 'connecting'; this.changed();
    const url = new URL('/api/v1/stream', this.origin); url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    const socket = this.socket = new WebSocket(url); this.lastMessage = performance.now();
    const current = () => !this.stopped && epoch === this.epoch;
    const restart = (message: string) => {
      if (!current()) return;
      this.invalidate(message); this.phase = this.lastHealth?.status === 'ended' ? 'ended' : this.lastHealth?.status === 'degraded' ? 'degraded' : 'recovering';
      this.epoch++; clearTimeout(this.poll); this.abort?.abort(); socket.close(); this.socket = null; this.changed();
      if (this.phase !== 'ended') { this.retry = setTimeout(() => this.connect(), this.retryDelay); this.retryDelay = Math.min(5000, this.retryDelay * 2); }
    };
    socket.onopen = () => { if (current()) { this.phase = 'waiting-snapshot'; this.changed(); } };
    socket.onmessage = event => {
      if (!current()) return;
      try {
        need(typeof event.data === 'string' && new TextEncoder().encode(event.data).byteLength <= this.store.limits.packetBytes, '消息过大或不是文本');
        const message: unknown = JSON.parse(event.data);
        if ((message as { kind?: string })?.kind === 'health') {
          this.lastHealth = health(message); need(!this.store.identity, '完整流中收到异常健康包');
          this.phase = this.lastHealth.status === 'ended' ? 'ended' : 'recovering'; this.changed(); return;
        }
        const snapshot = (message as { kind?: string })?.kind === 'snapshot';
        this.store.accept(message); this.lastMessage = performance.now();
        if (snapshot) { this.snapshots++; this.retryDelay = 250; this.error = ''; } else this.deltas++;
        this.refreshPhase(); this.changed();
      } catch (error) { restart(String(error)); }
    };
    socket.onclose = event => { if (current()) { this.closeCode = event.code; restart('连接已关闭，等待新快照（'+event.code+'）'); } };
    socket.onerror = () => restart('网关连接不可用');
    const poll = async () => {
      if (!current()) return;
      const abort = this.abort = new AbortController(); const timeout = setTimeout(() => abort.abort(), 2500);
      try {
        const response = await fetch(new URL('/api/v1/health', this.origin), { cache: 'no-store', signal: abort.signal });
        need(response.ok, '网关 HTTP '+response.status);
        const text = await response.text(); need(new TextEncoder().encode(text).byteLength <= 65536, '健康消息过大');
        const value = health(JSON.parse(text));
        if (!current()) return;
        this.lastHealth = value;
        const id = this.store.identity;
        if (id && (id.run_id !== value.run_id || id.stream_id !== value.stream_id || !value.ready || value.freshness.stale)) {
          restart('后端身份或就绪状态变化，重新同步'); return;
        }
        if (!id && performance.now() - this.lastMessage > 10000) { restart('快照等待超时'); return; }
        if (id && !value.freshness.paused && performance.now() - this.lastMessage > 6000) { restart('消息已过期'); return; }
        this.refreshPhase(); this.changed();
      } catch (error) { if (current()) { restart(String(error)); return; } }
      finally { clearTimeout(timeout); }
      if (current()) this.poll = setTimeout(poll, 1000);
    };
    void poll();
  }
  private refreshPhase(): void {
    const identity = this.store.identity, health = this.lastHealth;
    this.phase = identity && health?.ready && health.status === 'live' && !health.freshness.stale &&
      health.run_id === identity.run_id && health.stream_id === identity.stream_id ? 'live' :
      health?.status === 'ended' ? 'ended' : health?.status === 'degraded' ? 'degraded' : 'waiting-snapshot';
  }
  inspect() { return { ...this.store.inspect(), phase: this.phase, health: this.lastHealth, lastKnownTime: this.lastKnownTime,
    error: this.error, snapshots: this.snapshots, deltas: this.deltas, attempts: this.attempts, closeCode: this.closeCode }; }
}
