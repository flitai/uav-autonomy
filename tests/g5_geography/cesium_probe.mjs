import { readFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { join } from 'node:path';

const [project, input, output] = process.argv.slice(2);
const core = join(project, 'node_modules/@cesium/engine/Source/Core');
const {default: HeightmapTerrainData} = await import(pathToFileURL(join(core, 'HeightmapTerrainData.js')));
const {default: Rectangle} = await import(pathToFileURL(join(core, 'Rectangle.js')));
const request = JSON.parse(readFileSync(input, 'utf8'));
const bytes = readFileSync(request.path);
const terrain = new HeightmapTerrainData({
  buffer: new Float32Array(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength)),
  width: request.width, height: request.height,
});
const b = request.bounds;
const rectangle = Rectangle.fromDegrees(b.west, b.south, b.east, b.north);
const values = request.points.map(p => terrain.interpolateHeight(rectangle, p[0]*Math.PI/180, p[1]*Math.PI/180));
writeFileSync(output, JSON.stringify({values, node: process.version, actualCesiumHeightmapInterpolation: true}, null, 2));
