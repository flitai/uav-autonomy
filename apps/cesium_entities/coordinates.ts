import { Cartesian3, Matrix3, Quaternion } from 'cesium';

export interface Position { latitude_deg: number; longitude_deg: number; altitude_m: number; altitude_reference: number }
export interface Attitude { heading_deg: number; pitch_deg: number; roll_deg: number }
export interface HeightGrid { west: number; south: number; east: number; north: number; width: number; height: number; stepDegrees: number; values: number[]; datum: 'EGM96'; sha256: string }
const radians = (n: number) => n * Math.PI / 180;
export function requireValue(value: unknown, message: string): asserts value { if (!value) throw new Error(message); }

export function undulation(lon: number, lat: number, grid: HeightGrid): number {
  requireValue(Number.isFinite(lon) && Number.isFinite(lat) && lon >= grid.west && lon < grid.east && lat >= grid.south && lat < grid.north, '实体位置超出合格区域');
  const x = (lon - grid.west) / grid.stepDegrees, y = (grid.north - lat) / grid.stepDegrees;
  const col = Math.min(grid.width - 2, Math.floor(x)), row = Math.min(grid.height - 2, Math.floor(y));
  const fx = x - col, fy = y - row, at = (dy: number, dx: number) => grid.values[(row + dy) * grid.width + col + dx];
  const value = (1 - fy) * ((1 - fx) * at(0, 0) + fx * at(0, 1)) + fy * ((1 - fx) * at(1, 0) + fx * at(1, 1));
  requireValue(Number.isFinite(value), '高程转换网格无效'); return value;
}

export function position(value: Position, grid: HeightGrid) {
  // The qualified AirVehicleState reports MSL/EGM96. Never guess another datum.
  requireValue(value.altitude_reference === 1, '当前实体显示要求 MSL／EGM96 高度');
  requireValue(Number.isFinite(value.altitude_m), '实体高度无效');
  const correction = undulation(value.longitude_deg, value.latitude_deg, grid), ellipsoid = value.altitude_m + correction;
  return { ecef: Cartesian3.fromDegrees(value.longitude_deg, value.latitude_deg, ellipsoid), ellipsoid, correction };
}

export function orientation(value: Position, attitude: Attitude): Quaternion {
  requireValue([value.latitude_deg, value.longitude_deg, attitude.heading_deg, attitude.pitch_deg, attitude.roll_deg].every(Number.isFinite), '姿态数值无效');
  const lat = radians(value.latitude_deg), lon = radians(value.longitude_deg);
  const h = radians(attitude.heading_deg), p = radians(attitude.pitch_deg), r = radians(attitude.roll_deg);
  const [ch, sh, cp, sp, cr, sr] = [Math.cos(h), Math.sin(h), Math.cos(p), Math.sin(p), Math.cos(r), Math.sin(r)];
  // AMASE Euler.getDxDyDz: body forward/right/down -> north/east/down.
  // Cesium's converted model frame is forward/left/up. Asset axes are handled in GLB.
  const north = new Cartesian3(-Math.sin(lat) * Math.cos(lon), -Math.sin(lat) * Math.sin(lon), Math.cos(lat));
  const east = new Cartesian3(-Math.sin(lon), Math.cos(lon), 0);
  const down = new Cartesian3(-Math.cos(lat) * Math.cos(lon), -Math.cos(lat) * Math.sin(lon), -Math.sin(lat));
  const world = (n: number, e: number, d: number) => new Cartesian3(north.x*n+east.x*e+down.x*d, north.y*n+east.y*e+down.y*d, north.z*n+east.z*e+down.z*d);
  const forward = world(cp*ch, cp*sh, -sp);
  const left = world(-sr*sp*ch+cr*sh, -sr*sp*sh-cr*ch, -sr*cp);
  const up = world(-cr*sp*ch-sr*sh, -cr*sp*sh+sr*ch, -cr*cp);
  const matrix = new Matrix3(forward.x,left.x,up.x, forward.y,left.y,up.y, forward.z,left.z,up.z);
  return Quaternion.normalize(Quaternion.fromRotationMatrix(matrix), new Quaternion());
}

export interface PoseSample { time: string; position: Position; attitude: Attitude }
export function interpolate(samples: PoseSample[], requested: bigint, grid: HeightGrid) {
  requireValue(samples.length > 0, '缺少位置样本');
  const first = BigInt(samples[0].time), last = BigInt(samples[samples.length-1].time);
  const target = requested < first ? first : requested > last ? last : requested;
  let right = samples.findIndex(s => BigInt(s.time) >= target); if (right < 0) right = samples.length - 1;
  const left = Math.max(0, right - 1), a = samples[left], b = samples[right];
  const dt = BigInt(b.time) - BigInt(a.time), fraction = dt > 0n ? Number(target - BigInt(a.time)) / Number(dt) : 0;
  const pa = position(a.position, grid), pb = position(b.position, grid);
  return { time: target.toString(), lower: a.time, upper: b.time, fraction,
    position: Cartesian3.lerp(pa.ecef, pb.ecef, fraction, new Cartesian3()),
    orientation: Quaternion.slerp(orientation(a.position, a.attitude), orientation(b.position, b.attitude), fraction, new Quaternion()) };
}
