import { BoundingSphere, CallbackProperty, Cartesian2, Cartesian3, Color, ColorBlendMode, ColorMaterialProperty, ConstantPositionProperty, ConstantProperty, CustomDataSource, Entity, HeadingPitchRange, JulianDate, LabelStyle, Matrix4, Quaternion, Viewer } from 'cesium';
import { interpolate, position, type Attitude, type HeightGrid, type PoseSample, type Position } from './coordinates.js';
import type { ReadOnlyConnection } from '../state/connection.js';
import { appearance, type Appearance, type AffiliationConfig } from './affiliation.js';
import { modelLighting, screenScale, validateDisplay, type DisplayConfig } from './display.js';

export interface EntityConfig { modelUrl: string; modelName: string; modelLengthMeters: number; modelDiameterMeters: number; display: DisplayConfig; entityModels: Record<string, string>; height: HeightGrid; interpolationMilliseconds: string; affiliations: AffiliationConfig }
export class EntityLayer {
  readonly source = new CustomDataSource('仿真实体');
  readonly objects = new Map<string, Entity>();
  readonly poses = new Map<string, ReturnType<typeof interpolate>>();
  readonly affiliations = new Map<string, Appearance>();
  selected: string | null = null; error = ''; private generation = -1; private displayClock: bigint | null = null;
  showModels = true; showLabels = true; showTrails = true;
  modelScale = 1;
  private readonly lighting = modelLighting();
  constructor(readonly viewer: Viewer, readonly connection: ReadOnlyConnection, readonly config: EntityConfig, readonly changed: () => void) {
    validateDisplay(config.display,config.modelDiameterMeters);
    viewer.dataSources.add(this.source);
    viewer.selectedEntityChanged.addEventListener(this.selection);
  }
  private selection = (entity: Entity | undefined) => { this.selected = [...this.objects].find(([, e]) => e === entity)?.[0] ?? null; this.outlines(); this.changed(); };
  private outlines(): void {
    const config=this.config.affiliations;
    for (const [id,entity] of this.objects) {
      entity.model!.silhouetteColor=new ConstantProperty(Color.fromCssColorString(id===this.selected?config.selectedOutlineColor:config.outlineColor));
      entity.model!.silhouetteSize=new ConstantProperty(id===this.selected?config.selectedOutlinePixels:config.outlinePixels);
    }
    this.viewer.scene.requestRender();
  }
  private paint(id: string, entity: Entity, style: Appearance): void {
    const previous=this.affiliations.get(id);
    if (previous?.color===style.color && previous?.label===style.label && previous?.source===style.source && previous?.reported===style.reported) return;
    this.affiliations.set(id,style);
    const color=Color.fromCssColorString(style.color);
    entity.model!.color=new ConstantProperty(color);
    // Tint the normal-based lighting result, retaining bright/dark surfaces.
    entity.model!.colorBlendMode=new ConstantProperty(ColorBlendMode.HIGHLIGHT);
    entity.label!.fillColor=new ConstantProperty(color);
    entity.label!.text=new ConstantProperty('实体 '+id+' · '+style.label);
    entity.polyline!.material=new ColorMaterialProperty(color);
    this.outlines();
  }
  clear(): void {
    if (this.viewer.trackedEntity && [...this.objects.values()].includes(this.viewer.trackedEntity)) this.viewer.trackedEntity = undefined;
    if (this.viewer.selectedEntity && [...this.objects.values()].includes(this.viewer.selectedEntity)) this.viewer.selectedEntity = undefined;
    this.source.entities.removeAll(); this.objects.clear(); this.poses.clear(); this.affiliations.clear(); this.selected = null; this.displayClock = null;
  }
  update(): void {
    if (this.viewer.isDestroyed()) return;
    const store = this.connection.store;
    if (this.generation !== store.generation || this.connection.phase !== 'live') { this.clear(); this.generation = store.generation; }
    if (this.connection.phase !== 'live') { this.viewer.scene.requestRender(); this.changed(); return; }
    const now = store.state.simulation.simulation_time_ms;
    if (typeof now !== 'string') return;
    const running = store.state.simulation.state === 1 && !this.connection.lastHealth?.freshness.paused;
    // Only committed backend time drives interpolation. No browser wall-clock prediction.
    if (running || this.displayClock === null) this.displayClock = BigInt(now) - BigInt(this.config.interpolationMilliseconds);
    this.error = '';
    for (const [id, entity] of this.objects) if (!store.state.entities[id]) {
      if (this.viewer.trackedEntity === entity) this.viewer.trackedEntity = undefined;
      if (this.viewer.selectedEntity === entity) this.viewer.selectedEntity = undefined;
      this.source.entities.remove(entity); this.objects.delete(id); this.poses.delete(id); this.affiliations.delete(id); if (this.selected === id) this.selected = null;
    }
    for (const [id, raw] of Object.entries(store.state.entities)) {
      if (!raw.position || !raw.attitude || typeof raw.simulation_time_ms !== 'string') continue;
      try {
        if (!this.config.entityModels[id]) throw new Error('未配置实体模型映射');
        const current: PoseSample = { time: raw.simulation_time_ms, position: raw.position as unknown as Position, attitude: raw.attitude as unknown as Attitude };
        // Snapshot location is displayed immediately, but never becomes invented past history.
        const samples = (store.samples.get(id) ?? []) as unknown as PoseSample[];
        const pose = interpolate(samples.length ? samples : [current], this.displayClock, this.config.height);
        let entity = this.objects.get(id);
        if (!entity) {
          entity = this.source.entities.add({ id: 'aircraft:'+id, name: '实体 '+id,
            position: new ConstantPositionProperty(pose.position), orientation: new ConstantProperty(pose.orientation),
            viewFrom: new Cartesian3(-120,-180,100),
            model: { uri: this.config.modelUrl, minimumPixelSize: 0, runAnimations: false, customShader: this.lighting,
              scale: new CallbackProperty(() => screenScale(this.viewer,this.poses.get(id)?.position ?? pose.position,this.config.modelDiameterMeters,this.config.display.sizePixels*this.modelScale),false) },
            label: { text: '实体 '+id, font: '14px "Map CJK"', fillColor: Color.WHITE, outlineColor: Color.BLACK, outlineWidth: 3, style: LabelStyle.FILL_AND_OUTLINE, pixelOffset: new Cartesian2(0,-24) },
            polyline: { positions: [], width: 2, material: Color.fromCssColorString('#7be1c9'), clampToGround: false } });
          this.objects.set(id, entity);
        }
        this.paint(id,entity,appearance(id,raw,this.config.affiliations));
        (entity.position as ConstantPositionProperty).setValue(pose.position);
        (entity.orientation as ConstantProperty).setValue(pose.orientation);
        const trail = samples.filter(s => BigInt(s.time) <= BigInt(pose.time)).map(s => position(s.position,this.config.height).ecef);
        if (trail.length) trail.push(pose.position);
        entity.polyline!.positions = new ConstantProperty(trail);
        entity.show = this.showModels; entity.label!.show = new ConstantProperty(this.showLabels);
        entity.polyline!.show = new ConstantProperty(this.showTrails && trail.length > 1);
        this.poses.set(id, pose);
      } catch (error) {
        const previous = this.objects.get(id);
        if (previous) { if (this.viewer.trackedEntity === previous) this.viewer.trackedEntity = undefined; if (this.viewer.selectedEntity === previous) this.viewer.selectedEntity = undefined; this.source.entities.remove(previous); this.objects.delete(id); this.poses.delete(id); this.affiliations.delete(id); }
        if (this.selected === id) this.selected = null;
        this.error = ('实体 '+id+'：'+String(error)).slice(0,600);
      }
    }
    this.viewer.scene.requestRender(); this.changed();
  }
  select(id: string): void { if (!this.objects.has(id)) return; this.selected = id; this.viewer.selectedEntity = this.objects.get(id); this.outlines(); this.changed(); }
  locate(): void {
    const pose = this.selected && this.poses.get(this.selected); if (!pose) return;
    this.viewer.trackedEntity = undefined;
    this.viewer.camera.flyToBoundingSphere(new BoundingSphere(pose.position,20), { duration:0, offset:new HeadingPitchRange(0,-Math.PI/6,160) });
    this.viewer.scene.requestRender(); this.changed();
  }
  follow(): void { if (!this.selected) return; this.viewer.trackedEntity = this.objects.get(this.selected); this.viewer.scene.requestRender(); this.changed(); }
  reset(): void {
    this.viewer.trackedEntity = undefined;
    this.viewer.camera.lookAtTransform(Matrix4.IDENTITY);
    this.viewer.camera.setView({destination:Cartesian3.fromDegrees(-121,45.31,45000),orientation:{heading:0,pitch:-65*Math.PI/180,roll:0}});
    this.viewer.scene.requestRender(); this.changed();
  }
  inspect() {
    const time = JulianDate.now();
    return { count:this.objects.size, selected:this.selected, followed:[...this.objects].find(([,e])=>e===this.viewer.trackedEntity)?.[0] ?? null,
      error:this.error, displayClock:this.displayClock?.toString() ?? null, generation:this.generation,
      visible:this.showModels, labels:this.showLabels, trails:this.showTrails, modelScale:this.modelScale, screenPixels:this.config.display.sizePixels*this.modelScale,
      objects:Object.fromEntries([...this.objects].map(([id,e]) => { const pose=this.poses.get(id)!;
        return [id,{position:Cartesian3.pack(e.position!.getValue(time)!,[]),orientation:Quaternion.pack(e.orientation!.getValue(time),[]),
          time:pose.time,lower:pose.lower,upper:pose.upper,fraction:pose.fraction,model:e.model!.uri!.getValue(time),scale:e.model!.scale!.getValue(time),
          trailPoints:e.polyline!.positions!.getValue(time).length,affiliation:this.affiliations.get(id),color:e.model!.color!.getValue(time).toCssHexString(),
          outline:e.model!.silhouetteColor!.getValue(time).toCssHexString(),outlinePixels:e.model!.silhouetteSize!.getValue(time),pointFallback:!!e.point}]; })) };
  }
  destroy(): void {
    if (!this.viewer.isDestroyed()) { this.viewer.selectedEntityChanged.removeEventListener(this.selection); this.clear(); this.viewer.dataSources.remove(this.source,true); }
    else { this.objects.clear(); this.poses.clear(); this.affiliations.clear(); this.selected = null; this.displayClock = null; }
    if (!this.lighting.isDestroyed()) this.lighting.destroy();
  }
}
