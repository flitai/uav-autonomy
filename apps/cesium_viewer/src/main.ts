import { ArcGisMapServerImageryProvider, Cartesian3, Color, EllipsoidTerrainProvider, ImageryLayer, Ion, Math as CesiumMath, Rectangle, Viewer } from 'cesium';
import { RegionalTerrain, VectorProvider, type Runtime } from './map/providers';
import 'cesium/Build/Cesium/Widgets/widgets.css';
import './style.css';

Ion.defaultAccessToken='';
const status=document.querySelector<HTMLElement>('#status')!, notice=document.querySelector<HTMLElement>('#notice')!;
const terrainSwitch=document.querySelector<HTMLInputElement>('#terrain-toggle')!;
const boundarySwitch=document.querySelector<HTMLInputElement>('#boundary-toggle')!;
const baseSelect=document.querySelector<HTMLSelectElement>('#base-layer')!;
const errors:string[]=[];
function fail(message:string){errors.push(message);if(errors.length>64)errors.shift();notice.textContent=message;notice.hidden=false;}
try {
  const response=await fetch('/map/runtime.json',{cache:'no-store'});
  if(!response.ok)throw new Error('本地地图配置不可用');
  const runtime=await response.json() as Runtime;
  if(runtime.schemaVersion!==1||runtime.terrain.datum!=='EPSG:4979')throw new Error('地图配置或高度基准不受支持');
  const font=new FontFace('Map CJK',`url(${runtime.font})`);await font.load();document.fonts.add(font);
  const vector=new VectorProvider(runtime),terrain=new RegionalTerrain(runtime.terrain);
  const viewer=new Viewer('scene',{
    baseLayer:new ImageryLayer(vector),terrainProvider:terrain,animation:false,timeline:false,baseLayerPicker:false,
    geocoder:false,homeButton:false,sceneModePicker:false,navigationHelpButton:false,fullscreenButton:false,
    infoBox:false,selectionIndicator:false,shouldAnimate:false,skyBox:false,requestRenderMode:true,maximumRenderTimeChange:Infinity,
  });
  viewer.scene.globe.baseColor=Color.fromCssColorString('#bdd8e4');viewer.scene.globe.tileCacheSize=128;
  viewer.scene.globe.maximumScreenSpaceError=3;
  const {west,south,east,north}=runtime.terrain.bounds;
  const boundary=viewer.entities.add({id:'terrain-qualification-boundary',name:'区域地形资格边界',rectangle:{
    coordinates:Rectangle.fromDegrees(west,south,east,north),height:3600,fill:false,outline:true,outlineColor:Color.fromCssColorString('#f7bf68')},show:false});
  const reset=()=>viewer.camera.setView({destination:Cartesian3.fromDegrees(-121.0,45.31,45000),orientation:{heading:0,pitch:CesiumMath.toRadians(-65),roll:0}});
  reset();document.querySelector('#reset-view')!.addEventListener('click',reset);
  document.querySelector('#global-view')!.addEventListener('click',()=>viewer.camera.setView({destination:Cartesian3.fromDegrees(110,30,19_000_000)}));
  document.querySelector('#beijing-view')!.addEventListener('click',()=>viewer.camera.setView({destination:Cartesian3.fromDegrees(116.397,39.908,80000)}));
  document.querySelector('#terrain-detail')!.addEventListener('click',()=>viewer.camera.setView({destination:Cartesian3.fromDegrees(-121.70,45.20,9500),orientation:{heading:0,pitch:CesiumMath.toRadians(-25),roll:0}}));
  terrainSwitch.addEventListener('change',()=>{viewer.terrainProvider=terrainSwitch.checked?terrain:new EllipsoidTerrainProvider();viewer.scene.requestRender();});
  boundarySwitch.addEventListener('change',()=>{boundary.show=boundarySwitch.checked;viewer.scene.requestRender();});
  vector.errorEvent.addEventListener((error:Error)=>{document.documentElement.dataset.ready='failed';fail('本地底图加载失败：'+error.message);});
  terrain.errorEvent.addEventListener((error:Error)=>{document.documentElement.dataset.ready='failed';fail('区域地形加载失败：'+String(error));});
  viewer.scene.renderError.addEventListener((_scene,error:Error)=>{document.documentElement.dataset.ready='failed';fail('场景绘制失败：'+error.message);});
  let satellite:ImageryLayer|undefined,selection=0;
  function local(message?:string){
    selection++;baseSelect.value='local';
    if(satellite){viewer.imageryLayers.remove(satellite,true);satellite=undefined;}
    if(message)fail(message);viewer.scene.requestRender();
  }
  baseSelect.addEventListener('change',async()=>{
    if(baseSelect.value==='local'){local();return;}
    const current=++selection;notice.hidden=true;
    let timer:ReturnType<typeof setTimeout>|undefined;
    try {
      const provider=await Promise.race([ArcGisMapServerImageryProvider.fromUrl(runtime.satellite.url,{enablePickFeatures:false}),
        new Promise<never>((_resolve,reject)=>{timer=setTimeout(()=>reject(new Error('影像服务响应超时')),12000);})]);
      if(current!==selection)return;
      provider.errorEvent.addEventListener(()=>{if(current===selection)local('在线影像不可用，已恢复本地矢量底图。');});
      satellite=viewer.imageryLayers.addImageryProvider(provider);viewer.scene.requestRender();
    }catch(error){if(current===selection)local('在线影像不可用，已恢复本地矢量底图。'+String(error));}
    finally{clearTimeout(timer);}
  });
  let frames=0;
  viewer.scene.postRender.addEventListener(()=>{
    frames++;
    if(vector.metrics.tiles>0&&terrain.requests>0&&!errors.length){document.documentElement.dataset.ready='true';status.textContent='地图已就绪';}
    const p=viewer.camera.positionCartographic,lon=CesiumMath.toDegrees(p.longitude),lat=CesiumMath.toDegrees(p.latitude);
    document.querySelector('#location')!.textContent=`${lon.toFixed(4)}°，${lat.toFixed(4)}°`;
    document.querySelector('#terrain-status')!.textContent=terrainSwitch.checked&&lon>=west&&lon<=east&&lat>=south&&lat<=north?'USGS 区域地形':'参考椭球 · 区域外地形未验收';
  });
  // Inspection handles for the independent browser acceptance probe.
  Object.assign(window,{__g5Map:{viewer,vector,terrain,runtime,errors,get frames(){return frames;}}});
  window.addEventListener('beforeunload',()=>{Object.assign(window,{__g5Map:undefined});vector.worker.terminate();viewer.destroy();});
}catch(error){document.documentElement.dataset.ready='failed';status.textContent='地图未就绪';fail(String(error));}
