// G4 v1 wire values stay JSON-compatible; 64-bit identifiers are never numbers.
export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type ObjectValue = { [key: string]: Json };
export const collections = ['entities', 'tasks', 'routes', 'commands', 'zones'] as const;
export type Collection = typeof collections[number];
export type State = Record<Collection, Record<string, ObjectValue>> & { simulation: ObjectValue };
export interface Header { schema_version: 1; run_id: string; stream_id: string; sequence: string; source_time_ms: string | null }
export interface Snapshot extends Header { kind: 'snapshot'; state: State }
export interface Change { collection: Collection | 'simulation'; id: string; op: 'upsert' | 'delete'; value?: ObjectValue }
export interface Delta extends Header { kind: 'delta'; changes: Change[] }
export interface Health extends Header {
  kind: 'health'; status: 'initializing' | 'live' | 'recovering' | 'degraded' | 'ended'; ready: boolean;
  freshness: { paused: boolean; stale: boolean }; connections: Record<string, { connected: boolean }>;
  [key: string]: unknown;
}
export interface Limits { packetBytes: number; stateBytes: number; objectsPerCollection: number; samplesPerEntity: number; sampleEntities: number; trajectoryWindowMs: string }
export const defaults: Limits = { packetBytes: 8 * 1024 * 1024, stateBytes: 32 * 1024 * 1024,
  objectsPerCollection: 4096, samplesPerEntity: 2048, sampleEntities: 128, trajectoryWindowMs: '600000' };
export function need(value: unknown, message: string): asserts value { if (!value) throw new Error(message); }
export const object = (value: unknown): value is ObjectValue => !!value && typeof value === 'object' && !Array.isArray(value);
export function decimal(value: unknown): asserts value is string {
  need(typeof value === 'string' && /^-?(0|[1-9][0-9]*)$/.test(value) && value.length <= 21, '整数标识或时间必须为十进制字符串');
}
export const bytes = (value: unknown) => new TextEncoder().encode(JSON.stringify(value)).byteLength;
export function validateJson(value: unknown, depth = 0, key = ''): void {
  need(depth <= 40, '消息嵌套过深');
  if (value === null) return;
  if (Array.isArray(value)) { need(value.length <= 65536, '数组超过上限'); value.forEach(v => validateJson(v, depth + 1, key)); return; }
  if (object(value)) {
    for (const [name, child] of Object.entries(value)) {
      need(!['__proto__', 'prototype', 'constructor'].includes(name), '不支持的对象键');
      validateJson(child, depth + 1, name);
    }
    return;
  }
  if (typeof value === 'number') need(Number.isFinite(value) && (!Number.isInteger(value) || Number.isSafeInteger(value)), '不安全的数值');
  else need(['string', 'boolean'].includes(typeof value), '非 JSON 值');
  if ((/(?:_id|_ids|_time_ms)$/.test(key) && !['run_id', 'stream_id'].includes(key)) || ['ID', 'Time', 'ScenarioTime', 'StartTime', 'TaskID', 'VehicleID', 'PayloadID', 'CommandID', 'CurrentCommand', 'AssociatedTasks', 'EligibleEntities', 'EntitiesInvolved', 'EntityID', 'TaskList', 'EntityList', 'ZoneList'].includes(key)) decimal(value);
}
export function header(value: unknown): asserts value is Header & ObjectValue {
  need(object(value) && value.schema_version === 1, '不支持的协议版本');
  need(typeof value.run_id === 'string' && value.run_id.length > 0 && value.run_id.length <= 512, '运行身份无效');
  need(typeof value.stream_id === 'string' && value.stream_id.length > 0 && value.stream_id.length <= 128, '流身份无效');
  decimal(value.sequence); need(BigInt(value.sequence) >= 0n, '序号无效');
  need(value.source_time_ms === null || typeof value.source_time_ms === 'string', '源时间无效');
  if (value.source_time_ms !== null) decimal(value.source_time_ms);
}
export function health(value: unknown): Health {
  header(value); need(value.kind === 'health' && typeof value.ready === 'boolean', '健康消息无效');
  need(['initializing', 'live', 'recovering', 'degraded', 'ended'].includes(String(value.status)), '健康状态无效');
  need(object(value.freshness) && typeof value.freshness.paused === 'boolean' && typeof value.freshness.stale === 'boolean', '缺少新鲜度');
  need(object(value.connections), '缺少连接状态');
  return value as unknown as Health;
}
export function clock(value: ObjectValue): void {
  if (Object.keys(value).length === 0) return;
  decimal(value.simulation_time_ms); decimal(value.start_time_ms);
  need([0, 1, 2, 3, 4].includes(Number(value.state)) && typeof value.state === 'number', '仿真状态无效');
  need(typeof value.real_time_multiple === 'number' && Number.isFinite(value.real_time_multiple), '仿真倍率无效');
}
