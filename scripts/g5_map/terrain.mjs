// Resample only the qualified EPSG:4979 field. Outside is explicitly reference ellipsoid.
export function sample(field, grid, longitude, latitude) {
  const { west, south, east, north } = grid.bounds;
  if (longitude < west || longitude > east || latitude < south || latitude > north) return null;
  const gx = (longitude-west)/(east-west)*(grid.width-1);
  const gy = (north-latitude)/(north-south)*(grid.height-1);
  const x = Math.min(Math.floor(gx), grid.width-2), y = Math.min(Math.floor(gy), grid.height-2);
  const u = gx-x, v = gy-y;
  const nw=field[y*grid.width+x], ne=field[y*grid.width+x+1];
  const sw=field[(y+1)*grid.width+x], se=field[(y+1)*grid.width+x+1];
  // Cesium's southwest-to-northeast diagonal, expressed with north-first rows.
  const height = u+v <= 1 ? nw+u*(ne-nw)+v*(sw-nw) : se+(1-u)*(sw-se)+(1-v)*(ne-se);
  if (!Number.isFinite(height)) throw new Error('Nonfinite qualified terrain sample');
  return height;
}

export function tile(field, grid, z, x, y, size=65) {
  if (![z,x,y].every(Number.isInteger) || z<0 || z>14 || x<0 || x>=2**(z+1) || y<0 || y>=2**z) {
    throw new Error('Invalid terrain XYZ');
  }
  const span=180/2**z, west=-180+x*span, north=90-y*span;
  const data=Buffer.alloc(size*size*4); let qualified=0;
  for(let row=0;row<size;row++) for(let column=0;column<size;column++) {
    const height=sample(field,grid,west+column*span/(size-1),north-row*span/(size-1));
    if(height !== null) qualified++;
    data.writeFloatLE(height ?? 0,4*(row*size+column));
  }
  return {data,qualified};
}
