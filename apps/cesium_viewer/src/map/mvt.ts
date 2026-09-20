import { Proto, requireValue } from './archive';
export type Feature={kind:number;properties:Record<string,string|number|boolean>;paths:number[][][]};
export type Layer={name:string;extent:number;features:Feature[]};
const decoder=new TextDecoder('utf-8',{fatal:true});
function value(data:Uint8Array):string|number|boolean {
  const fields=[...new Proto(data).fields()];requireValue(fields.length===1,'MVT value type');const f=fields[0];
  if(f.tag===1&&f.wire===2)return decoder.decode(f.value as Uint8Array);
  if((f.tag===2&&f.wire===5)||(f.tag===3&&f.wire===1)){const b=f.value as Uint8Array,v=new DataView(b.buffer,b.byteOffset,b.length);return f.tag===2?v.getFloat32(0,true):v.getFloat64(0,true);}
  requireValue(f.wire===0,'MVT value wire');const n=f.value as bigint;
  if(f.tag===7)return n!==0n;
  if(f.tag===6)return ((n>>1n)^-(n&1n)).toString();
  if(f.tag===4)return BigInt.asIntN(64,n).toString();
  requireValue(f.tag===5,'MVT value tag');return n.toString();
}
export function decodeMvt(data:Uint8Array):Layer[]{
  requireValue(data.length<=16*1024*1024,'MVT exceeds limit');const result:Layer[]=[];let totalFeatures=0,totalVertices=0;
  for(const top of new Proto(data).fields()){
    if(top.tag!==3)continue;requireValue(top.wire===2,'MVT layer wire');
    const fields=[...new Proto(top.value as Uint8Array).fields()];const keys:string[]=[],values:(string|number|boolean)[]=[],raw:Uint8Array[]=[];
    let name='',extent=4096,version=0;
    for(const f of fields){
      if(f.tag===1&&f.wire===2)name=decoder.decode(f.value as Uint8Array);
      if(f.tag===2&&f.wire===2)raw.push(f.value as Uint8Array);
      if(f.tag===3&&f.wire===2)keys.push(decoder.decode(f.value as Uint8Array));
      if(f.tag===4&&f.wire===2)values.push(value(f.value as Uint8Array));
      if(f.tag===5&&f.wire===0)extent=Number(f.value);
      if(f.tag===15&&f.wire===0)version=Number(f.value);
    }
    requireValue(name && [1,2].includes(version)&&extent>0&&extent<=65536&&!result.some(l=>l.name===name),'Invalid MVT layer');
    const features:Feature[]=[];
    for(const bytes of raw){
      requireValue(++totalFeatures<=200000,'Feature limit exceeded');let kind=0,geometry:Uint8Array|undefined;
      const properties:Record<string,string|number|boolean>=Object.create(null);
      for(const f of new Proto(bytes).fields()){
        if(f.tag===3&&f.wire===0)kind=Number(f.value);
        if(f.tag===4&&f.wire===2)geometry=f.value as Uint8Array;
        if(f.tag===2&&f.wire===2){const tags=new Proto(f.value as Uint8Array);
          while(tags.cursor<tags.data.length){const k=tags.number(),v=tags.number();requireValue(k<keys.length&&v<values.length,'MVT tag index');properties[keys[k]]=values[v];}}
      }
      requireValue([1,2,3].includes(kind)&&geometry,'Missing MVT geometry');const paths:number[][][]=[],g=new Proto(geometry);let x=0,y=0;
      while(g.cursor<g.data.length){const command=g.number(),op=command&7,count=Math.floor(command/8);
        requireValue([1,2,7].includes(op)&&count>0,'Geometry command');
        if(op===7){requireValue(kind===3&&count===1&&paths.length,'Invalid polygon close');paths.at(-1)!.push(paths.at(-1)![0]);continue;}
        requireValue(op===1||paths.length,'Line before MoveTo');requireValue(kind!==1||op===1,'Point LineTo');
        for(let i=0;i<count;i++){const dx=g.number(),dy=g.number();x+=(dx%2?-1:1)*Math.floor((dx+1)/2);y+=(dy%2?-1:1)*Math.floor((dy+1)/2);
          requireValue(++totalVertices<=1_000_000&&Math.abs(x)<2**31&&Math.abs(y)<2**31,'Geometry size/coordinate limit');
          if(op===1)paths.push([]);paths.at(-1)!.push([x,y]);}
      }
      features.push({kind,properties,paths});
    }
    result.push({name,extent,features});
  }
  requireValue(result.length>0&&result.length<=64,'Missing/excessive MVT layers');return result;
}
