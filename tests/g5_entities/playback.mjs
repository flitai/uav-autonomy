import assert from 'node:assert/strict';
import { writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const [project,output]=process.argv.slice(2);
const {BufferedPlayback}=await import(pathToFileURL(resolve(project,'layer-unit/entities/playback.js')));
const base=9007199254740993000n,p=new BufferedPlayback(1000n);
p.observe(base,true,1,0);assert.equal(p.value,base-1000n);
let previous=p.value;let intermediate=0;
for(let wall=10;wall<=2500;wall+=10){
  const packet=Math.floor(wall/530)*530;
  if(wall%530===0){const before=p.value;p.observe(base+BigInt(packet),true,1,wall);assert.equal(p.value,before,'Packet snapped cursor');}
  const current=p.advance(wall);assert(current>previous);assert(current-previous<=11n);assert(current<=base+BigInt(packet));previous=current;intermediate++;
}
const twin=new BufferedPlayback(1000n),health=new BufferedPlayback(1000n);
for(const item of [twin,health])item.observe(base,true,1,0);
for(let wall=10;wall<=500;wall+=10){health.observe(base,true,1,wall);assert.equal(health.advance(wall),twin.advance(wall));}
const frozen=p.value;p.observe(base+3000n,false,1,2510);
for(let wall=2520;wall<=3500;wall+=10)assert.equal(p.advance(wall),frozen);
p.observe(base+3000n,true,2,3500);p.advance(3510);assert(p.value-frozen>=18n&&p.value-frozen<=22n);
const beforeStall=p.value;p.advance(100000);assert(p.value-beforeStall<=220n,'Hidden tab consumed arbitrary wall time');
for(let wall=100010;wall<=110000;wall+=10)p.advance(wall);
assert.equal(p.value,base+3000n);assert.equal(p.advance(120000),base+3000n,'Extrapolated past latest sample');
for(const rate of [NaN,Infinity,0,-1]){p.observe(base+4000n,true,rate,120000);assert.equal(p.advance(120010),base+3000n);}
p.reset();assert.equal(p.value,null);assert.equal(p.advance(130000),null);p.observe(50n,true,1,130000);assert.equal(p.value,-950n);
assert.throws(()=>new BufferedPlayback(0n));assert.throws(()=>new BufferedPlayback(10001n));
writeFileSync(output,JSON.stringify({status:'passed',intermediateFrames:intermediate,checks:['large-int64','between-packets','bounded-jitter-correction','same-sample-health','immediate-pause','backend-rate','long-frame-cap','buffer-exhaustion','invalid-rate','identity-reset','invalid-buffer']},null,2));
