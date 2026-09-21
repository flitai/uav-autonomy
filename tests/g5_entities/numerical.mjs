import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const [project, calibration, output] = process.argv.slice(2);
const load = path => JSON.parse(readFileSync(path,'utf8'));
const { Cartesian3, Matrix3, Quaternion } = await import(pathToFileURL(resolve(project,'node_modules/cesium/Source/Cesium.js')));
const coordinate = await import(pathToFileURL(resolve(project,'numerical/coordinates.js')));
const grid=load(resolve(calibration,'height.json')), references=load(resolve(calibration,'position-reference.json'));
let positionError=0, correctionError=0, attitudeError=0;
for(const row of references){const actual=coordinate.position(row.position,grid);positionError=Math.max(positionError,Math.hypot(...Cartesian3.pack(actual.ecef,[]).map((n,i)=>n-row.ecef[i])));correctionError=Math.max(correctionError,Math.abs(actual.correction-row.correction));}
assert(positionError<=1 && correctionError<=1);
const origin={latitude_deg:45.3,longitude_deg:-121,altitude_m:1090,altitude_reference:1};
const lat=origin.latitude_deg*Math.PI/180,lon=origin.longitude_deg*Math.PI/180;
const ned=[[-Math.sin(lat)*Math.cos(lon),-Math.sin(lat)*Math.sin(lon),Math.cos(lat)],[-Math.sin(lon),Math.cos(lon),0],[-Math.cos(lat)*Math.cos(lon),-Math.cos(lat)*Math.sin(lon),-Math.sin(lat)]];
const poses=load(resolve(calibration,'attitude-reference.json'));
for(const row of poses){
 const q=coordinate.orientation(origin,{heading_deg:row.heading,pitch_deg:row.pitch,roll_deg:row.roll}),matrix=Matrix3.fromQuaternion(q);
 for(let col=0;col<3;col++){
  const expected=[0,1,2].map(axis=>row.nedColumns[col].reduce((sum,value,k)=>sum+value*ned[k][axis],0));
  const actual=Cartesian3.pack(Matrix3.getColumn(matrix,col,new Cartesian3()),[]);
  const dot=actual.reduce((sum,value,k)=>sum+value*expected[k],0);
  attitudeError=Math.max(attitudeError,Math.acos(Math.max(-1,Math.min(1,dot)))*180/Math.PI);
 }
}
assert(attitudeError<=.1);
const bad=[{...origin,latitude_deg:46},{...origin,longitude_deg:-120},{...origin,longitude_deg:45,latitude_deg:-121},{...origin,altitude_reference:0},{...origin,altitude_m:NaN}];
for(const value of bad)assert.throws(()=>coordinate.position(value,grid));
const base=9007199254740993000n;
const samples=[{time:String(base),position:origin,attitude:{heading_deg:359,pitch_deg:0,roll_deg:0}},{time:String(base+2000n),position:{...origin,altitude_m:1190},attitude:{heading_deg:1,pitch_deg:0,roll_deg:0}}];
assert.equal(coordinate.interpolate(samples,base-1000n,grid).time,String(base));
assert.equal(coordinate.interpolate(samples,base+3000n,grid).time,String(base+2000n));
assert.equal(coordinate.interpolate(samples.slice(0,1),base+1000n,grid).time,String(base));
assert.throws(()=>coordinate.interpolate([],base,grid));
const mid=coordinate.interpolate(samples,base+1000n,grid);assert.equal(mid.fraction,.5);assert.equal(mid.time,String(base+1000n));
const expected=coordinate.position({...origin,altitude_m:1140},grid).ecef;
assert(Cartesian3.distance(mid.position,expected)<1e-6);
const straight=coordinate.orientation(origin,{heading_deg:0,pitch_deg:0,roll_deg:0});
assert(Math.abs(Quaternion.dot(straight,mid.orientation))>1-1e-10,'Heading wrap chose the long rotation');
const result={status:'passed',independentPositions:references.length,formalAmaseAttitudes:poses.length,positionErrorMeters:positionError,geoidErrorMeters:correctionError,attitudeErrorDegrees:attitudeError,rejections:bad.length,interpolationChecks:6,largeTimePreserved:true};
writeFileSync(output,JSON.stringify(result,null,2));console.log(JSON.stringify(result));
