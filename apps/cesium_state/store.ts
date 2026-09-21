import { bytes, clock, collections, decimal, defaults, header, need, object, validateJson,
  type Change, type Collection, type Header, type Limits, type ObjectValue, type State } from './protocol.js';

export interface Sample { time: string; position: ObjectValue; attitude: ObjectValue }
const empty = (): State => ({ entities: {}, tasks: {}, routes: {}, commands: {}, zones: {}, simulation: {} });
export class StateStore {
  state: State = empty(); identity: Header | null = null;
  samples = new Map<string, Sample[]>(); generation = 0; stateBytes = 0;
  constructor(readonly limits: Limits = defaults) {}
  clear(): void { this.state = empty(); this.identity = null; this.samples.clear(); this.stateBytes = 0; this.generation++; }
  accept(value: unknown): void {
    try { this.apply(value); } catch (error) { this.clear(); throw error; }
  }
  private apply(value: unknown): void {
    header(value); validateJson(value); need(bytes(value) <= this.limits.packetBytes, '消息超过缓存上限');
    let next: State; let entityChanges: Change[] = [];
    if (value.kind === 'snapshot') {
      need(this.identity === null, '同一连接重复快照');
      need(object(value.state) && Object.keys(value.state).length === 6, '快照集合不完整');
      for (const name of collections) {
        const collection = value.state[name]; need(object(collection), '缺少快照集合');
        this.validateCollection(name, collection);
      }
      need(object(value.state.simulation), '缺少仿真时间'); clock(value.state.simulation);
      next = structuredClone(value.state) as unknown as State;
    } else {
      need(value.kind === 'delta' && this.identity !== null, '必须先收到同连接快照');
      need(value.run_id === this.identity.run_id && value.stream_id === this.identity.stream_id, '运行或流身份变化');
      need(BigInt(value.sequence) === BigInt(this.identity.sequence) + 1n, '增量重复、乱序或缺口');
      need(Array.isArray(value.changes) && value.changes.length > 0 && value.changes.length <= 8192, '增量集合无效');
      // Commit all changes together after validation; an invalid packet never leaves partial state.
      next = { ...this.state }; const copied = new Set<string>();
      for (const raw of value.changes) {
        need(object(raw) && typeof raw.collection === 'string' && typeof raw.id === 'string', '增量键无效');
        const change = raw as unknown as Change;
        need(['upsert', 'delete'].includes(change.op), '增量操作无效');
        if (change.collection === 'simulation') {
          need(change.id === 'clock' && change.op === 'upsert' && object(change.value), '时钟更新无效');
          clock(change.value);
          const previous = next.simulation.simulation_time_ms, current = change.value.simulation_time_ms;
          if (previous !== undefined) { decimal(current); decimal(previous); need(BigInt(current) >= BigInt(previous), '同运行时钟回退'); }
          next.simulation = structuredClone(change.value); continue;
        }
        need(collections.includes(change.collection), '未知业务集合');
        this.key(change.collection, change.id);
        if (!copied.has(change.collection)) { next[change.collection] = { ...next[change.collection] }; copied.add(change.collection); }
        if (change.op === 'delete') delete next[change.collection][change.id];
        else { need(object(change.value), '缺少完整对象'); next[change.collection][change.id] = structuredClone(change.value); }
        need(Object.keys(next[change.collection]).length <= this.limits.objectsPerCollection, '对象数超过上限');
        if (change.collection === 'entities') entityChanges.push(change);
      }
    }
    const size = bytes(next); need(size <= this.limits.stateBytes, '业务缓存超过上限');
    this.state = next; this.stateBytes = size;
    this.identity = { schema_version: 1, run_id: value.run_id, stream_id: value.stream_id, sequence: value.sequence, source_time_ms: value.source_time_ms as string | null };
    for (const change of entityChanges) {
      if (change.op === 'delete') { this.samples.delete(change.id); continue; }
      const entity = next.entities[change.id];
      if (!entity || !object(entity.position) || !object(entity.attitude) || typeof entity.simulation_time_ms !== 'string') continue;
      const time = entity.simulation_time_ms; decimal(time);
      if (!this.samples.has(change.id) && this.samples.size >= this.limits.sampleEntities) continue;
      const list = this.samples.get(change.id) ?? [];
      if (list.length && BigInt(time) <= BigInt(list[list.length - 1].time)) continue;
      const position: ObjectValue = {}, attitude: ObjectValue = {};
      for (const key of ['latitude_deg', 'longitude_deg', 'altitude_m', 'altitude_reference']) {
        need(typeof entity.position[key] === 'number' && Number.isFinite(entity.position[key]), '位置字段无效'); position[key] = entity.position[key];
      }
      for (const key of ['heading_deg', 'pitch_deg', 'roll_deg']) {
        need(typeof entity.attitude[key] === 'number' && Number.isFinite(entity.attitude[key]), '姿态字段无效'); attitude[key] = entity.attitude[key];
      }
      list.push({ time, position, attitude });
      const cutoff = BigInt(time) - BigInt(this.limits.trajectoryWindowMs);
      while (list.length && (list.length > this.limits.samplesPerEntity || BigInt(list[0].time) < cutoff)) list.shift();
      this.samples.set(change.id, list);
    }
    const now = this.state.simulation.simulation_time_ms;
    if (typeof now === 'string') {
      const cutoff = BigInt(now) - BigInt(this.limits.trajectoryWindowMs);
      for (const [id, list] of this.samples) {
        while (list.length && BigInt(list[0].time) < cutoff) list.shift();
        if (!list.length) this.samples.delete(id);
      }
    }
  }
  private key(name: Collection, key: string): void {
    if (name === 'commands') need(/^-?\d+:(mission|action)$/.test(key) && key.length <= 32, '命令键无效');
    else if (name === 'zones' && key.startsWith('region:')) decimal(key.slice(7));
    else decimal(key);
  }
  private validateCollection(name: Collection, value: ObjectValue): void {
    need(Object.keys(value).length <= this.limits.objectsPerCollection, '对象数超过上限');
    for (const [key, child] of Object.entries(value)) { this.key(name, key); need(object(child), '快照对象无效'); }
  }
  inspect() { return { identity: this.identity, state: this.state, generation: this.generation, stateBytes: this.stateBytes,
    sampleCounts: Object.fromEntries([...this.samples].map(([id, samples]) => [id, samples.length])) }; }
}
