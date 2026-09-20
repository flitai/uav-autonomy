import { Credit, Event, GeographicTilingScheme, HeightmapTerrainData, NeverTileDiscardPolicy, Resource, TerrainProvider, WebMercatorTilingScheme, type Request } from 'cesium';
import { requireValue } from './archive';
export type Runtime={schemaVersion:number;stage:string;simulationConnected:boolean;
  vector:{url:string;bytes:number;sha256:string;attribution:string};
  terrain:{bounds:{west:number;south:number;east:number;north:number};width:number;height:number;tileSize:number;maxLevel:number;regionId:string;datum:string;url:string};
  font:string;satellite:{url:string;credit:string};limits:{rangeBytes:number;terrainCacheTiles:number};};
export class VectorProvider {
  readonly tileWidth=512;readonly tileHeight=512;readonly minimumLevel=0;readonly maximumLevel=15;
  readonly tilingScheme=new WebMercatorTilingScheme();readonly rectangle=this.tilingScheme.rectangle;
  readonly errorEvent=new Event();readonly credit:Credit;readonly hasAlphaChannel=false;
  readonly tileDiscardPolicy=new NeverTileDiscardPolicy();readonly proxy={getURL:(resource:string)=>resource};
  readonly worker=new Worker(new URL('./vector.worker.ts',import.meta.url),{type:'module'});
  readonly pending=new Map<number,{resolve:(value:ImageBitmap)=>void;reject:(error:Error)=>void;timer:ReturnType<typeof setTimeout>}>();
  metrics:Record<string,number>={};labels:string[]=[];ready=false;failed=false;private sequence=0;
  constructor(runtime:Runtime){
    this.credit=new Credit(runtime.vector.attribution,true);
    this.worker.onmessage=event=>{const m=event.data;if(m.kind==='ready'){this.ready=true;return;}if(m.kind==='fatal'){this.fail(m.error);return;}
      const job=this.pending.get(m.id);if(!job){m.bitmap?.close();return;}clearTimeout(job.timer);this.pending.delete(m.id);
      if(m.kind==='tile'){this.metrics=m.metrics;this.labels=m.labels;job.resolve(m.bitmap);}else{const error=new Error(m.error);job.reject(error);this.errorEvent.raiseEvent(error);}};
    this.worker.onerror=event=>this.fail(event.message);
    this.worker.postMessage({kind:'init',...runtime.vector,font:new URL(runtime.font,location.href).href,url:new URL(runtime.vector.url,location.href).href});
  }
  private fail(message:string){this.failed=true;this.errorEvent.raiseEvent(new Error(message));for(const job of this.pending.values()){clearTimeout(job.timer);job.reject(new Error(message));}this.pending.clear();this.worker.terminate();}
  requestImage(x:number,y:number,z:number){
    if(this.failed)return Promise.reject(new Error('Vector worker unavailable'));if(!this.ready||this.pending.size>=4)return undefined;
    const id=++this.sequence;return new Promise<ImageBitmap>((resolve,reject)=>{const timer=setTimeout(()=>this.fail('Vector rendering timeout'),60000);this.pending.set(id,{resolve,reject,timer});this.worker.postMessage({kind:'tile',id,x,y,z});});
  }
  getTileCredits():Credit[]{return [];}pickFeatures(){return undefined;}destroy(){this.fail('Viewer closed');}
}
export class RegionalTerrain {
  readonly tilingScheme=new GeographicTilingScheme();readonly errorEvent=new Event();
  readonly credit=new Credit('区域地形：USGS 3DEP · WGS84 椭球高；区域外为参考椭球',true);
  readonly hasWaterMask=false;readonly hasVertexNormals=false;readonly availability=undefined;
  requests=0;errors=0;active=0;peakActive=0;
  constructor(readonly config:Runtime['terrain']){}
  getLevelMaximumGeometricError(level:number){return TerrainProvider.getEstimatedLevelZeroGeometricErrorForAHeightmap(this.tilingScheme.ellipsoid,this.config.tileSize,2)/2**level;}
  getTileDataAvailable(_x:number,_y:number,level:number){return level<=this.config.maxLevel;}loadTileDataAvailability(){return undefined;}
  requestTileGeometry(x:number,y:number,level:number,request?:Request){
    if(this.active>=8)return undefined;const resource=new Resource({url:`${this.config.url}/${level}/${x}/${y}.f32`,request});
    const response=resource.fetchArrayBuffer();if(!response)return undefined;this.active++;this.peakActive=Math.max(this.peakActive,this.active);
    return response.then(data=>{requireValue(data.byteLength===this.config.tileSize**2*4,'Terrain response size differs');const buffer=new Float32Array(data);requireValue(buffer.every(Number.isFinite),'Invalid terrain response');this.requests++;
      return new HeightmapTerrainData({buffer,width:this.config.tileSize,height:this.config.tileSize,childTileMask:level<this.config.maxLevel?15:0});
    }).catch(error=>{this.errors++;this.errorEvent.raiseEvent(error);throw error;}).finally(()=>this.active--);
  }
}
