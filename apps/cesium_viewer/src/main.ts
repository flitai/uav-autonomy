import {
  Cartesian3, Color, EllipsoidTerrainProvider, GeometryInstance, Ion,
  PerInstanceColorAppearance, ColorGeometryInstanceAttribute, Primitive,
  Rectangle, RectangleGeometry, Viewer,
} from 'cesium';
import 'cesium/Build/Cesium/Widgets/widgets.css';
import './style.css';

declare const __CESIUM_VERSION__: string;

Ion.defaultAccessToken = '';
const viewer = new Viewer('scene', {
  baseLayer: false,
  terrainProvider: new EllipsoidTerrainProvider(),
  animation: false, timeline: false, baseLayerPicker: false,
  geocoder: false, homeButton: false, sceneModePicker: false,
  navigationHelpButton: false, fullscreenButton: false,
  infoBox: false, selectionIndicator: false, shouldAnimate: false,
  skyBox: false, skyAtmosphere: false,
});
viewer.scene.globe.baseColor = Color.fromCssColorString('#314652');
viewer.camera.setView({ destination: Cartesian3.fromDegrees(110, 30, 19_000_000) });

// A labelled engineering sample exercises Cesium's asynchronous geometry worker.
// It is neither a simulated entity nor qualified geographic data.
const sample = viewer.scene.primitives.add(new Primitive({
  geometryInstances: new GeometryInstance({
    geometry: new RectangleGeometry({
      rectangle: Rectangle.fromDegrees(109, 29, 111, 31),
      vertexFormat: PerInstanceColorAppearance.VERTEX_FORMAT,
    }),
    attributes: { color: ColorGeometryInstanceAttribute.fromColor(Color.CYAN.withAlpha(0.6)) },
  }),
  appearance: new PerInstanceColorAppearance({ flat: true }),
  asynchronous: true,
}));
viewer.entities.add({
  position: Cartesian3.fromDegrees(110, 30),
  label: { text: '资源验证样片', font: '16px "Microsoft YaHei", sans-serif', fillColor: Color.WHITE },
});
const status = document.querySelector<HTMLParagraphElement>('#status')!;
const stop = viewer.scene.postRender.addEventListener(() => {
  if (!sample.ready) return;
  status.textContent = `Cesium ${__CESIUM_VERSION__} 已就绪 · 中文标签与工作线程已加载`;
  document.documentElement.dataset.ready = 'true';
  stop();
});
viewer.scene.renderError.addEventListener((_scene, error: Error) => {
  status.textContent = `场景加载失败：${error.message}`;
  document.documentElement.dataset.ready = 'failed';
});
