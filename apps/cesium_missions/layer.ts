import { ArcType, BoundingSphere, CallbackProperty, Cartesian2, Cartesian3, Color, ConstantProperty, CustomDataSource, Entity, HeadingPitchRange, HeightReference, LabelStyle, PolygonHierarchy, PolylineDashMaterialProperty, type Viewer } from 'cesium';
import { MissionModel, type Category, type Feature } from './model.js';
import type { Vertex } from './geometry.js';

export const world=(v:Vertex)=>Cartesian3.fromDegrees(v.longitude,v.latitude,v.ellipsoid);
const colors:Record<Category,string>={plans:'#83b9e5',commands:'#ffc267',execution:'#62ffbd',tasks:'#eac769',zones:'#ec7795'};
export class MissionLayer {
  readonly source=new CustomDataSource('航线、任务与区域');
  readonly groups=new Map<string,{signature:string;entities:Entity[]}>();
  readonly visible:Record<Category,boolean>={plans:true,commands:true,execution:true,tasks:true,zones:true};
  selected:string|null=null;waypoint:string|null=null;showWaypoints=false;
  private readonly picks=new Map<string,{key:string;waypoint?:string}>();
  private disposed=false;private readonly removeSelection:()=>void;
  constructor(readonly viewer:Viewer,readonly model:MissionModel,readonly changed:()=>void){
    viewer.dataSources.add(this.source);this.removeSelection=viewer.selectedEntityChanged.addEventListener(this.selection);
  }
  private selection=(entity:Entity|undefined)=>{
    const pick=entity&&this.picks.get(entity.id);
    if(pick){this.selected=pick.key;this.waypoint=pick.waypoint??null;this.refreshVisibility();this.changed();}
  };
  update():void {
    if(this.disposed||this.viewer.isDestroyed())return;
    for(const [key,g] of this.groups)if(!this.model.features.has(key)){for(const e of g.entities)this.remove(e);this.groups.delete(key);}
    if(this.selected&&!this.model.features.has(this.selected)){this.selected=null;this.waypoint=null;}
    for(const f of this.model.features.values()) {
      const signature=JSON.stringify([f.drawings,f.waypoints?.map(w=>[w.id,w.vertex])]);
      const old=this.groups.get(f.key);if(old?.signature===signature)continue;
      if(old)for(const e of old.entities)this.remove(e);
      const entities:Entity[]=[],color=Color.fromCssColorString(colors[f.category]);
      const add=(options:Entity.ConstructorOptions,waypoint?:string)=>{
        const e=this.source.entities.add({...options,id:'mission:'+f.key+':'+entities.length,name:f.title});entities.push(e);this.picks.set(e.id,{key:f.key,waypoint});return e;
      };
      for(const d of f.drawings) {
        const positions=d.vertices.map(world);
        if(d.kind==='line')add({polyline:{positions:new CallbackProperty(()=>positions,false),width:f.category==='execution'?5:f.category==='commands'?3:2,
          material:f.category==='plans'?new PolylineDashMaterialProperty({color,dashLength:12}):color,depthFailMaterial:color.withAlpha(.45),arcType:d.ground?ArcType.GEODESIC:ArcType.NONE,clampToGround:d.ground===true}});
        else if(d.kind==='point')add({position:positions[0],point:{pixelSize:f.category==='execution'?11:10,color,outlineColor:Color.BLACK,outlineWidth:2,disableDepthTestDistance:Number.POSITIVE_INFINITY},
          label:{text:f.category==='tasks'?f.title:'目标 '+d.waypoint,font:'13px "Map CJK"',style:LabelStyle.FILL_AND_OUTLINE,fillColor:color,outlineWidth:3,pixelOffset:new Cartesian2(0,-22),disableDepthTestDistance:Number.POSITIVE_INFINITY}},d.waypoint);
        else if(d.kind==='area')add({polygon:{hierarchy:new PolygonHierarchy(positions),material:color.withAlpha(f.category==='zones'?.08:.18),perPositionHeight:!d.ground,heightReference:d.ground?HeightReference.CLAMP_TO_GROUND:HeightReference.NONE,arcType:ArcType.GEODESIC}});
        else if(d.kind==='wall')add({wall:{positions,minimumHeights:d.lower!.map(v=>v.ellipsoid),maximumHeights:d.vertices.map(v=>v.ellipsoid),material:color.withAlpha(.12)}});
      }
      for(const w of f.waypoints??[])add({position:world(w.vertex),point:{pixelSize:5,color,outlineColor:Color.BLACK,outlineWidth:1,disableDepthTestDistance:Number.POSITIVE_INFINITY},
        label:{show:new CallbackProperty(()=>this.selected===f.key&&this.waypoint===w.id,false),text:'航点 '+w.id,font:'13px "Map CJK"',fillColor:color,style:LabelStyle.FILL_AND_OUTLINE,outlineWidth:3,pixelOffset:new Cartesian2(0,-20),disableDepthTestDistance:Number.POSITIVE_INFINITY}},w.id);
      this.groups.set(f.key,{signature,entities});
    }
    this.refreshVisibility();
  }
  private remove(e:Entity){if(this.viewer.selectedEntity===e)this.viewer.selectedEntity=undefined;if(this.viewer.trackedEntity===e)this.viewer.trackedEntity=undefined;this.source.entities.remove(e);this.picks.delete(e.id);}
  refreshVisibility(){
    for(const [key,g] of this.groups){const f=this.model.features.get(key)!;for(const e of g.entities){const pick=this.picks.get(e.id)!;e.show=this.visible[f.category]&&(!f.waypoints||!pick.waypoint||this.showWaypoints||this.selected===key);}}
    this.viewer.scene.requestRender();
  }
  select(key:string,waypoint:string|null=null){if(!this.model.features.has(key))return;this.selected=key;this.waypoint=waypoint;this.refreshVisibility();this.changed();}
  locate(key=this.selected,waypoint=this.waypoint){
    const f=key&&this.model.features.get(key);if(!f)return;
    const related=f.category==='zones'&&f.related.length?f.related.map(k=>this.model.features.get(k)).filter((x):x is Feature=>!!x):[f];
    const specific=waypoint&&f.waypoints?.find(w=>w.id===waypoint);
    const points=specific?[world(specific.vertex)]:related.flatMap(v=>[...v.drawings.flatMap(d=>d.vertices.map(world)),...(v.waypoints??[]).map(w=>world(w.vertex))]);
    if(!points.length)return;
    const sphere=BoundingSphere.fromPoints(points);sphere.radius=Math.max(sphere.radius,50);
    this.viewer.trackedEntity=undefined;this.viewer.camera.flyToBoundingSphere(sphere,{duration:0,offset:new HeadingPitchRange(0,-Math.PI/3,Math.max(400,sphere.radius*3))});this.viewer.scene.requestRender();
  }
  clear(){for(const g of this.groups.values())for(const e of g.entities)this.remove(e);this.groups.clear();this.picks.clear();this.selected=null;this.waypoint=null;this.viewer.scene.requestRender();}
  inspect(){return {selected:this.selected,waypoint:this.waypoint,visible:{...this.visible},showWaypoints:this.showWaypoints,renderedObjects:this.source.entities.values.length,
    features:Object.fromEntries([...this.model.features].map(([key,f])=>[key,{...f,drawings:f.drawings.map(d=>({...d,ecef:d.vertices.map(v=>Cartesian3.pack(world(v),[]))}))}]))};}
  destroy(){
    if(this.disposed)return;this.disposed=true;this.removeSelection();
    if(!this.viewer.isDestroyed()){this.clear();this.viewer.dataSources.remove(this.source,true);}
    else {this.source.entities.removeAll();this.groups.clear();this.picks.clear();this.selected=null;this.waypoint=null;}
  }
}
