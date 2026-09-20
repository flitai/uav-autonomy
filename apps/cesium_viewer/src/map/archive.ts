// PMTiles v3 reader: https://github.com/protomaps/PMTiles/blob/main/spec/v3/spec.md
export function requireValue(value: unknown, message: string): asserts value {
  if (!value) throw new Error(message);
}
export class Lru<T> {
  private values=new Map<string,{value:T;bytes:number}>();
  bytes=0; peakBytes=0; evictions=0;
  constructor(readonly limit:number,readonly entries:number){}
  get(key:string){const row=this.values.get(key);if(row){this.values.delete(key);this.values.set(key,row);}return row?.value;}
  set(key:string,value:T,bytes:number){
    if(bytes>this.limit)return;
    const previous=this.values.get(key);if(previous){this.bytes-=previous.bytes;this.values.delete(key);}
    while(this.bytes+bytes>this.limit || this.values.size>=this.entries){
      const first=this.values.keys().next().value!;this.bytes-=this.values.get(first)!.bytes;this.values.delete(first);this.evictions++;
    }
    this.values.set(key,{value,bytes});this.bytes+=bytes;this.peakBytes=Math.max(this.peakBytes,this.bytes);
  }
  get size(){return this.values.size;}
}
export class Proto {
  cursor=0;
  constructor(readonly data:Uint8Array){}
  integer():bigint {
    let value=0n;
    for(let i=0;i<10;i++){
      requireValue(this.cursor<this.data.length,'Truncated varint');const byte=this.data[this.cursor++];
      requireValue(i<9 || byte<=1,'Varint overflow');value|=BigInt(byte&127)<<BigInt(i*7);
      if(byte<128)return value;
    }
    throw new Error('Varint overflow');
  }
  number(){const n=this.integer();requireValue(n<=BigInt(Number.MAX_SAFE_INTEGER),'Unsafe integer');return Number(n);}
  field():{tag:number;wire:number;value:bigint|Uint8Array}{
    const key=this.number(),tag=Math.floor(key/8),wire=key%8;requireValue(tag>0,'Invalid protobuf tag');
    if(wire===0)return {tag,wire,value:this.integer()};
    const length=wire===2?this.number():wire===1?8:wire===5?4:-1;
    requireValue(length>=0 && length<=this.data.length-this.cursor,'Truncated protobuf field');
    const value=this.data.subarray(this.cursor,this.cursor+length);this.cursor+=length;return {tag,wire,value};
  }
  *fields(){while(this.cursor<this.data.length)yield this.field();}
}
export async function gunzip(data:Uint8Array,maximum=16*1024*1024){
  const stream=new Blob([new Uint8Array(data)]).stream().pipeThrough(new DecompressionStream('gzip')).getReader();
  const chunks:Uint8Array[]=[];let size=0;
  try{while(true){const part=await stream.read();if(part.done)break;size+=part.value.length;
    requireValue(size<=maximum,'Inflated data exceeds limit');chunks.push(part.value);}}
  catch(error){await stream.cancel();throw error;}
  const result=new Uint8Array(size);let offset=0;for(const part of chunks){result.set(part,offset);offset+=part.length;}return result;
}
export function tileId(z:number,x:number,y:number){
  requireValue([z,x,y].every(Number.isInteger)&&z>=0&&z<=26&&x>=0&&y>=0&&x<2**z&&y<2**z,'Invalid tile XYZ');
  const n=2**z;let d=0;
  for(let step=n/2;step>=1;step/=2){const rx=(x&step)?1:0,ry=(y&step)?1:0;d+=step*step*((3*rx)^ry);
    if(ry===0){if(rx){x=n-1-x;y=n-1-y;}[x,y]=[y,x];}}
  return (4**z-1)/3+d;
}
export function directory(data:Uint8Array){
  const reader=new Proto(data),count=reader.number();requireValue(count>0&&count<=1_000_000,'Directory count exceeds limit');
  const rows=new Float64Array(count*4);let id=0;
  for(let i=0;i<count;i++){id+=reader.number();rows[i*4]=id;if(i)requireValue(id>rows[(i-1)*4],'Unsorted directory');}
  for(let i=0;i<count;i++)rows[i*4+1]=reader.number();
  for(let i=0;i<count;i++){const length=reader.number();requireValue(length>0&&length<=4*1024*1024,'Invalid directory span');rows[i*4+2]=length;}
  for(let i=0;i<count;i++){const encoded=reader.number();requireValue(i>0||encoded>0,'Invalid first offset');rows[i*4+3]=encoded?encoded-1:rows[(i-1)*4+3]+rows[(i-1)*4+2];}
  requireValue(reader.cursor===data.length,'Trailing directory bytes');return rows;
}
export class Archive {
  readonly ranges=new Lru<Uint8Array>(16*1024*1024,128);
  readonly directories=new Lru<Float64Array>(16*1024*1024,64);
  readonly metrics={rangeRequests:0,rangeBytes:0,maximumRead:0};
  private header?:{root:number;rootLength:number;leaf:number;leafLength:number;tile:number;tileLength:number;maxZoom:number};
  private opening?:Promise<void>;
  constructor(readonly url:string,readonly bytes:number,readonly digest:string){}
  async range(start:number,length:number){
    requireValue(Number.isSafeInteger(start)&&Number.isInteger(length)&&start>=0&&length>0&&length<=4*1024*1024&&start+length<=this.bytes,'Invalid archive range');
    const key=`${start}:${length}`,cached=this.ranges.get(key);if(cached)return cached;
    const response=await fetch(this.url,{headers:{Range:`bytes=${start}-${start+length-1}`,'If-Range':`"${this.digest}"`},signal:AbortSignal.timeout(15000)});
    requireValue(response.status===206 && response.headers.get('content-range')===`bytes ${start}-${start+length-1}/${this.bytes}` &&
      response.headers.get('etag')===`"${this.digest}"` && Number(response.headers.get('content-length'))===length,'Archive Range/version mismatch');
    const result=new Uint8Array(await response.arrayBuffer());requireValue(result.length===length,'Short archive response');
    this.metrics.rangeRequests++;this.metrics.rangeBytes+=length;this.metrics.maximumRead=Math.max(this.metrics.maximumRead,length);
    this.ranges.set(key,result,length);return result;
  }
  async open(){
    if(this.opening)return this.opening;
    this.opening=(async()=>{const bytes=await this.range(0,127),view=new DataView(bytes.buffer,bytes.byteOffset,bytes.length);
      requireValue(new TextDecoder().decode(bytes.subarray(0,7))==='PMTiles'&&bytes[7]===3,'PMTiles v3 required');
      requireValue(bytes[97]===2&&bytes[98]===2&&bytes[99]===1,'Gzip MVT required');
      const uint=(offset:number)=>{const n=view.getBigUint64(offset,true);requireValue(n<=BigInt(Number.MAX_SAFE_INTEGER),'PMTiles offset overflow');return Number(n);};
      const h={root:uint(8),rootLength:uint(16),leaf:uint(40),leafLength:uint(48),tile:uint(56),tileLength:uint(64),maxZoom:bytes[101]};
      requireValue(h.root>=127&&h.root+h.rootLength<=16384&&h.leaf+h.leafLength<=this.bytes&&h.tile+h.tileLength<=this.bytes&&h.maxZoom<=15,'PMTiles sections/zoom differ');this.header=h;
    })();return this.opening;
  }
  async tile(z:number,x:number,y:number){
    await this.open();const h=this.header!;requireValue(z<=h.maxZoom,'Zoom exceeds archive');const id=tileId(z,x,y);
    let start=h.root,length=h.rootLength;
    for(let depth=0;depth<5;depth++){
      const key=`${start}:${length}`;let rows=this.directories.get(key);
      if(!rows){rows=directory(await gunzip(await this.range(start,length)));this.directories.set(key,rows,rows.byteLength);}
      let low=0,high=rows.length/4;
      while(low<high){const mid=Math.floor((low+high)/2);if(rows[mid*4]<=id)low=mid+1;else high=mid;}
      if(!low)return null;const i=(low-1)*4,run=rows[i+1],count=rows[i+2],offset=rows[i+3];
      if(run){if(id>=rows[i]+run)return null;requireValue(offset+count<=h.tileLength,'Tile exceeds data section');return gunzip(await this.range(h.tile+offset,count));}
      requireValue(offset+count<=h.leafLength,'Leaf exceeds section');start=h.leaf+offset;length=count;
    }
    throw new Error('Directory depth exceeded');
  }
}
