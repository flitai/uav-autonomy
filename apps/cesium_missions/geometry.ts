import { undulation, type HeightGrid } from '../entities/coordinates.js';
import { need, object, type ObjectValue } from '../state/protocol.js';

export interface GroundConfig { west:number; south:number; east:number; north:number; width:number; height:number; stepDegrees:number; url:string; sha256:string }
export interface Heights { geoid:HeightGrid; ground:GroundConfig; values:Float32Array }
export interface Vertex { longitude:number; latitude:number; msl:number; ellipsoid:number }
export const numeric=(x:unknown,label:string):number=>{need(typeof x==='number'&&Number.isFinite(x),label+'无效');return x;};
export const record=(x:unknown,label:string):ObjectValue=>{need(object(x),label+'缺失');return x;};
export const array=(x:unknown,label:string):unknown[]=>{need(Array.isArray(x),label+'缺失');return x;};
export type XY=[number,number];
export function xy(raw:unknown,heights:Heights):XY {
  const v=record(raw,'位置'),lon=numeric(v.Longitude,'经度'),lat=numeric(v.Latitude,'纬度');
  undulation(lon,lat,heights.geoid);return [lon,lat];
}
export function ground(lon:number,lat:number,h:Heights):number {
  const g=h.ground;need(lon>=g.west&&lon<g.east&&lat>=g.south&&lat<g.north,'位置超出同源地形范围');
  const x=(lon-g.west)/g.stepDegrees,y=(g.north-lat)/g.stepDegrees,i=Math.min(g.width-2,Math.floor(x)),j=Math.min(g.height-2,Math.floor(y)),dx=x-i,dy=y-j;
  need(i>=0&&j>=0&&i+1<g.width&&j+1<g.height,'地形取样越界');
  const at=(r:number,c:number)=>h.values[(j+r)*g.width+i+c];
  const value=(1-dy)*((1-dx)*at(0,0)+dx*at(0,1))+dy*((1-dx)*at(1,0)+dx*at(1,1));
  need(Number.isFinite(value),'同源地形无效');return value;
}
export function altitude(point:XY,value:number,reference:number,h:Heights):Vertex {
  need(reference===0||reference===1,'高度基准未确认');numeric(value,'高度');
  const [longitude,latitude]=point,msl=value+(reference===0?ground(longitude,latitude,h):0);
  return {longitude,latitude,msl,ellipsoid:msl+undulation(longitude,latitude,h.geoid)};
}
export function location(raw:unknown,h:Heights):Vertex {
  const v=record(raw,'位置');return altitude(xy(v,h),numeric(v.Altitude,'高度'),numeric(v.AltitudeType,'高度类型'),h);
}
export function surface(point:XY,h:Heights):Vertex { return altitude(point,0,0,h); }
const radians=(x:number)=>x*Math.PI/180,degrees=(x:number)=>x*180/Math.PI;
// AMASE NavUtils uses a sphere of radius 6378137 m for CMASI rectangle corners.
export function destination(center:XY,bearing:number,distance:number):XY {
  const lon=radians(center[0]),lat=radians(center[1]),arc=distance/6378137;
  const latitude=Math.asin(Math.sin(lat)*Math.cos(arc)+Math.cos(lat)*Math.sin(arc)*Math.cos(bearing));
  const longitude=lon+Math.atan2(Math.sin(bearing)*Math.sin(arc),Math.cos(lat)*Math.cos(arc)-Math.sin(lat)*Math.sin(arc)*Math.cos(bearing));
  return [degrees(longitude),degrees(latitude)];
}
export function boundary(raw:unknown,h:Heights):XY[] {
  const g=record(raw,'二维几何'),kind=String(g._type).split('.').pop();let points:XY[];
  if(kind==='Rectangle') {
    const c=xy(g.CenterPoint,h),w=numeric(g.Width,'矩形宽度'),height=numeric(g.Height,'矩形高度'),rotation=radians(numeric(g.Rotation,'旋转'));
    need(w>0&&height>0&&w<=100000&&height<=100000,'矩形尺寸超出显示范围');
    const angle=Math.atan2(w,height),distance=Math.hypot(w/2,height/2);
    points=[-angle,angle,Math.PI-angle,Math.PI+angle].map(a=>destination(c,a+rotation,distance));
  } else if(kind==='Polygon') points=array(g.BoundaryPoints,'多边形顶点').map(v=>xy(v,h));
  else if(kind==='Circle') {
    const c=xy(g.CenterPoint,h),radius=numeric(g.Radius,'半径');need(radius>0&&radius<=50000,'圆半径超出显示范围');
    const n=Math.max(32,Math.ceil(2*Math.PI*radius/100));need(n<=4096,'圆边界超过上限');
    points=Array.from({length:n},(_,i)=>destination(c,i*2*Math.PI/n,radius));
  } else throw new Error('尚未支持的二维几何：'+kind);
  if(points.length>1&&points[0][0]===points.at(-1)![0]&&points[0][1]===points.at(-1)![1])points.pop();
  need(points.length>=3&&points.length<=4096,'边界顶点数量无效');
  for(const [lon,lat] of points)undulation(lon,lat,h.geoid);
  const cross=(a:XY,b:XY,c:XY)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);
  let area=0;
  for(let i=0;i<points.length;i++) {
    const a=points[i],b=points[(i+1)%points.length];need(Math.hypot(a[0]-b[0],a[1]-b[1])>1e-12,'边界重复顶点');
    area+=(a[0]-points[0][0])*(b[1]-points[0][1])-(b[0]-points[0][0])*(a[1]-points[0][1]);
    for(let j=i+2;j<points.length;j++) {
      if(i===0&&j===points.length-1)continue;
      const c=points[j],d=points[(j+1)%points.length];
      need(!(cross(a,b,c)*cross(a,b,d)<0&&cross(c,d,a)*cross(c,d,b)<0),'区域边界自相交');
    }
  }
  need(Math.abs(area)>1e-12,'区域面积为零');return points;
}
export function densify(points:XY[]):XY[] {
  const result:XY[]=[];
  for(let i=0;i<points.length;i++) {
    const a=points[i],b=points[(i+1)%points.length];
    const distance=6378137*Math.hypot(radians(b[0]-a[0])*Math.cos(radians((a[1]+b[1])/2)),radians(b[1]-a[1]));
    const n=Math.max(1,Math.ceil(distance/100));need(result.length+n<=4096,'区域加密顶点超过上限');
    for(let j=0;j<n;j++)result.push([a[0]+(b[0]-a[0])*j/n,a[1]+(b[1]-a[1])*j/n]);
  }
  return result;
}
