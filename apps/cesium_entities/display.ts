import { Cartesian2, Cartesian3, CustomShader, LightingModel, type Viewer } from 'cesium';

export interface DisplayConfig { sizePixels: number; minimumScale: number; maximumScale: number }
export function validateDisplay(config: DisplayConfig, diameter: number): void {
  if (!config || !Number.isFinite(diameter) || diameter <= 0 ||
      !Number.isFinite(config.sizePixels) || config.sizePixels < 24 || config.sizePixels > 256 ||
      !Number.isFinite(config.minimumScale) || !Number.isFinite(config.maximumScale) ||
      config.minimumScale <= 0 || config.minimumScale > 1 || config.maximumScale < 1 ||
      config.sizePixels * config.minimumScale < 24 || config.sizePixels * config.maximumScale > 512)
    throw new Error('模型屏幕尺寸配置无效');
}

const offset=new Cartesian3(), pixel=new Cartesian2();
export function screenScale(viewer: Viewer, position: Cartesian3, diameter: number, pixels: number): number {
  const {camera,canvas}=viewer;
  if (canvas.clientWidth <= 0 || canvas.clientHeight <= 0) return 1;
  const depth=Cartesian3.dot(Cartesian3.subtract(position,camera.positionWC,offset),camera.directionWC);
  // CSS pixels, independent of browser DPR and Cesium resolutionScale. Orthographic frusta also work.
  camera.frustum.getPixelDimensions(canvas.clientWidth,canvas.clientHeight,Math.max(camera.frustum.near,depth),1,pixel);
  return pixels*Math.max(pixel.x,pixel.y)/diameter;
}

export function modelLighting(): CustomShader {
  return new CustomShader({lightingModel:LightingModel.UNLIT,fragmentShaderText:`
    void fragmentMain(FragmentInput fsInput, inout czm_modelMaterial material) {
      vec3 n = normalize(fsInput.attributes.normalEC);
      if (!gl_FrontFacing) { n = -n; }
      vec3 view = normalize(-fsInput.attributes.positionEC);
      vec3 key = normalize(vec3(-0.85, 0.35, 0.25));
      vec3 fill = normalize(vec3(0.65, -0.35, 0.50));
      float diffuse = max(dot(n, key), 0.0);
      float specular = pow(max(dot(n, normalize(key + view)), 0.0), 24.0);
      float brightness = 0.10 + 0.85 * diffuse + 0.12 * max(dot(n, fill), 0.0);
      // Retain panel/cockpit texture detail with a floor so the original dark paint cannot hide the symbol.
      float detail = 0.60 + 0.40 * smoothstep(0.0, 0.55, dot(material.diffuse, vec3(0.2126, 0.7152, 0.0722)));
      material.diffuse = vec3(brightness * detail + 0.55 * specular * step(0.001, diffuse));
    }
  `});
  // Lighting is computed above from real mesh normals in eye space. UNLIT prevents
  // Cesium applying a second sunlight pass; this is display fill, not simulated solar illumination.
}
