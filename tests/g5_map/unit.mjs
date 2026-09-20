import assert from 'node:assert/strict';
import { readFileSync,writeFileSync,mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { gzipSync } from 'node:zlib';
import { spawnSync } from 'node:child_process';
import { parseRange } from '../../scripts/g5_map/server.mjs';
import { sample,tile } from '../../scripts/g5_map/terrain.mjs';
const [root,project,output]=process.argv.slice(2);
mkdirSync(resolve(output,'compiled'),{recursive:true});
const compilation=spawnSync(process.execPath,[resolve(project,'node_modules/typescript/bin/tsc'),
  resolve(root,'apps/cesium_viewer/src/map/archive.ts'),resolve(root,'apps/cesium_viewer/src/map/mvt.ts'),
  '--target','ES2022','--module','ESNext','--lib','ES2022,DOM','--skipLibCheck','--outDir',resolve(output,'compiled')],{encoding:'utf8',windowsHide:true});
assert.equal(compilation.status,0,compilation.stdout+compilation.stderr);
for(const name of ['archive','mvt']){
  const code=readFileSync(resolve(output,`compiled/${name}.js`),'utf8');
  writeFileSync(resolve(output,`compiled/${name}.mjs`),code.replace("'./archive'","'./archive.mjs'"));
}
const {Lru,Proto,tileId,directory,gunzip}=await import(pathToFileURL(resolve(output,'compiled/archive.mjs')));
const {decodeMvt}=await import(pathToFileURL(resolve(output,'compiled/mvt.mjs')));
const reference=JSON.parse(readFileSync(resolve(output,'fixtures/reference.json'),'utf8'));
const checks=[];function check(name,fn){fn();checks.push(name);}
check('range-boundaries',()=>{
  assert.deepEqual(parseRange('bytes=0-126',1000,500),{start:0,end:126});assert.deepEqual(parseRange('bytes=-16',1000,500),{start:984,end:999});
  assert.deepEqual(parseRange('bytes=950-',1000,500),{start:950,end:999});assert.deepEqual(parseRange('bytes=999-2000',1000,500),{start:999,end:999});
  for(const value of [undefined,'bytes=','bytes=-0','bytes=0-','bytes=0-500','bytes=1000-1001','bytes=5-4','bytes=0-1,3-4','bytes=9007199254740999-'])assert.throws(()=>parseRange(value,1000,500));
});
check('byte-and-entry-cache-eviction',()=>{const cache=new Lru(9,2);cache.set('a','A',4);cache.set('b','B',4);assert.equal(cache.get('a'),'A');cache.set('c','C',4);
  assert.equal(cache.get('b'),undefined);assert.equal(cache.size,2);cache.set('huge','X',10);assert.equal(cache.size,2);assert(cache.bytes<=9&&cache.peakBytes<=9&&cache.evictions===1);});
check('uint64-and-protobuf-rejection',()=>{
  assert.equal(new Proto(new Uint8Array([255,255,255,255,255,255,255,255,127])).integer(),9223372036854775807n);
  for(const bytes of [[128],Array(11).fill(255),[255,255,255,255,255,255,255,255,255,2]])assert.throws(()=>new Proto(new Uint8Array(bytes)).integer());
  assert.throws(()=>[...new Proto(new Uint8Array([26,5,1])).fields()]);assert.throws(()=>directory(new Uint8Array([1,0])));
  assert.throws(()=>decodeMvt(new Uint8Array([26,100,1])));
});
await assert.rejects(()=>gunzip(new Uint8Array(gzipSync(Buffer.alloc(1000))),50));checks.push('gzip-expansion-limit');
await assert.rejects(()=>gunzip(new Uint8Array([1,2,3])));checks.push('bad-gzip-rejection');
check('Hilbert-independent-known-cells',()=>{assert.equal(tileId(0,0,0),0);assert.deepEqual([[0,0],[0,1],[1,1],[1,0]].map(([x,y])=>tileId(1,x,y)),[1,2,3,4]);assert.throws(()=>tileId(15,32768,0));});
check('real-MVT-versus-independent-Python',()=>{
  for(const row of reference.mvt){assert.equal(String(tileId(...row.xyz)),row.tileId);const layers=decodeMvt(new Uint8Array(readFileSync(resolve(output,'fixtures',row.file))));
    assert.deepEqual(layers.map(l=>({name:l.name,extent:l.extent,features:l.features.length})),row.layers.map(l=>({name:l.name,extent:l.extent,features:l.features})));
    for(let i=0;i<layers.length;i++){
      const vertices=layers[i].features.reduce((n,f)=>n+f.paths.reduce((m,p)=>m+p.length-(f.kind===3&&p.length>1&&p[0]===p.at(-1)?1:0),0),0);
      assert.equal(vertices,row.layers[i].vertices);
    }
  }
});
const bytes=readFileSync(reference.heightfield),field=new Float32Array(bytes.buffer,bytes.byteOffset,bytes.length/4),grid=reference.grid;
let maximumError=0;
check('terrain-versus-independent-barycentric-solve',()=>{for(const point of reference.terrain){const error=Math.abs(sample(field,grid,point.longitude,point.latitude)-point.expected);maximumError=Math.max(error,maximumError);assert(error<0.00001);}});
check('adjacent-terrain-tiles-byte-identical-boundaries',()=>{
  for(const z of [8,10,12,14]){const x=Math.floor(59/180*2**z),y=Math.floor(44.5/180*2**z);
    const a=tile(field,grid,z,x,y).data,b=tile(field,grid,z,x+1,y).data,c=tile(field,grid,z,x,y+1).data;
    for(let k=0;k<65;k++){assert.equal(a.readFloatLE((k*65+64)*4),b.readFloatLE(k*65*4));assert.equal(a.readFloatLE((64*65+k)*4),c.readFloatLE(k*4));}
  }
});
check('outside-is-explicit-null-and-bad-terrain-refused',()=>{
  assert.equal(sample(field,grid,116,39),null);assert.equal(sample(field,grid,-122.0001,45.5),null);
  assert.throws(()=>tile(field,grid,15,0,0));assert.throws(()=>tile(field,grid,3,-1,0));
  const invalid=field.slice();invalid[0]=NaN;assert.throws(()=>sample(invalid,grid,-122,46));
});
writeFileSync(resolve(output,'unit-result.json'),JSON.stringify({status:'passed',checks,realMvtTiles:reference.mvt.length,maxTerrainErrorMeters:maximumError},null,2));
console.log('Independent unit checks passed:',checks.length);
