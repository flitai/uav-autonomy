/// <reference lib="webworker" />
import { Archive, requireValue } from './archive';
import { decodeMvt, type Layer } from './mvt';
const worker=self as unknown as DedicatedWorkerGlobalScope;
let archive:Archive, opening:Promise<void>, active=0;
const totals={tiles:0,features:0,chineseLabels:0,peakActive:0,errors:0};
const order=['earth','landcover','landuse','water','buildings','boundaries','roads','transit','places','pois'];
async function paint(layers:Layer[],z:number){
  const canvas=new OffscreenCanvas(512,512),ctx=canvas.getContext('2d')!;
  ctx.fillStyle='#bdd8e4';ctx.fillRect(0,0,512,512);
  const labels:{x:number;y:number;text:string;rank:number}[]=[];let features=0;
  layers.sort((a,b)=>order.indexOf(a.name)-order.indexOf(b.name));
  for(const layer of layers){const scale=512/layer.extent;
    for(const feature of layer.features){features++;const p=feature.properties;if(Number(p.min_zoom??0)>z+0.5)continue;
      if(feature.kind===3){ctx.beginPath();for(const path of feature.paths){path.forEach(([x,y],i)=>i?ctx.lineTo(x*scale,y*scale):ctx.moveTo(x*scale,y*scale));ctx.closePath();}
        ctx.fillStyle=layer.name==='water'?'#bdd8e4':layer.name==='buildings'?'#d4cabc':layer.name==='landcover'?'#d8e2c8':layer.name==='landuse'?'#e1e6d5':'#eeeade';ctx.fill('evenodd');
      }else if(feature.kind===2){ctx.beginPath();for(const path of feature.paths)path.forEach(([x,y],i)=>i?ctx.lineTo(x*scale,y*scale):ctx.moveTo(x*scale,y*scale));
        ctx.setLineDash(layer.name==='boundaries'?[5,4]:[]);ctx.strokeStyle=layer.name==='water'?'#8cb8ce':layer.name==='boundaries'?'#909b8e':layer.name==='transit'?'#9b9890':'#fffaf0';
        ctx.lineWidth=layer.name==='roads'?(p.kind==='highway'?3:1.4):1;ctx.stroke();if(layer.name==='roads'&&p.kind==='highway'){ctx.strokeStyle='#d9ba81';ctx.lineWidth=1;ctx.stroke();}
      }
      if(feature.kind===1&&(layer.name==='places'||layer.name==='pois')){const text=String(p['name:zh-Hans']??p['name:zh']??p.name??'').slice(0,80),point=feature.paths[0]?.[0];
        if(text&&point)labels.push({x:point[0]*scale,y:point[1]*scale,text,rank:Number(p.population_rank??20)});}
    }
  }
  ctx.setLineDash([]);ctx.font='14px "Map CJK"';ctx.textAlign='center';ctx.textBaseline='middle';const boxes:number[][]=[],shown:string[]=[];
  for(const label of labels.sort((a,b)=>a.rank-b.rank)){
    if(shown.length>=100)break;const width=ctx.measureText(label.text).width,box=[label.x-width/2-3,label.y-11,label.x+width/2+3,label.y+11];
    if(box[0]<2||box[1]<2||box[2]>510||box[3]>510||boxes.some(b=>box[0]<b[2]&&box[2]>b[0]&&box[1]<b[3]&&box[3]>b[1]))continue;
    boxes.push(box);ctx.strokeStyle='#fffef4';ctx.lineWidth=3;ctx.strokeText(label.text,label.x,label.y);ctx.fillStyle='#354642';ctx.fillText(label.text,label.x,label.y);shown.push(label.text);
  }
  // WebGL ignores UNPACK_FLIP_Y for ImageBitmap; match Cesium's image loader orientation.
  return {bitmap:await createImageBitmap(canvas,{imageOrientation:'flipY',premultiplyAlpha:'none'}),features,labels:shown};
}
worker.onmessage=async event=>{
  const message=event.data;
  if(message.kind==='init'){
    opening=(async()=>{archive=new Archive(message.url,message.bytes,message.sha256);await archive.open();const face=new FontFace('Map CJK',`url(${message.font})`);await face.load();worker.fonts.add(face);})();
    opening.then(()=>worker.postMessage({kind:'ready'})).catch(error=>worker.postMessage({kind:'fatal',error:String(error)}));return;
  }
  const id=message.id;let entered=false;
  try{
    requireValue(active<4,'Worker concurrency exceeded');active++;entered=true;totals.peakActive=Math.max(totals.peakActive,active);
    await opening;const data=await archive.tile(message.z,message.x,message.y);requireValue(data,'Vector tile absent from archive');const result=await paint(decodeMvt(data),message.z);
    totals.tiles++;totals.features+=result.features;totals.chineseLabels+=result.labels.filter(t=>/[\u3400-\u9fff]/.test(t)).length;
    worker.postMessage({kind:'tile',id,bitmap:result.bitmap,labels:result.labels,metrics:{...totals,...archive.metrics,rangeCacheBytes:archive.ranges.bytes,rangeCachePeak:archive.ranges.peakBytes,directoryCacheBytes:archive.directories.bytes,directoryCachePeak:archive.directories.peakBytes,evictions:archive.ranges.evictions+archive.directories.evictions}},[result.bitmap]);
  }catch(error){totals.errors++;worker.postMessage({kind:'error',id,error:String(error)});}finally{if(entered)active--;}
};
