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
      // Silver alloy; preserve panel/cockpit detail from the original texture.
      float detail = 0.48 + 0.52 * smoothstep(0.0, 0.55, dot(material.diffuse, vec3(0.2126, 0.7152, 0.0722)));
      vec3 base = vec3(0.66, 0.69, 0.73) * detail;
      material.diffuse = base * 0.08;
      material.specular = mix(vec3(0.04), base, 0.92);
      material.roughness = 0.30;
      material.normalEC = n;
      vec3 key = normalize(vec3(-0.60, 0.75, 1.0));
      vec3 fill = normalize(vec3(0.90, -0.20, 0.45));
      vec3 direct = 3.5 * czm_pbrLighting(view, n, key, material)
                  + 1.4 * czm_pbrLighting(view, n, fill, material);
      // Analytic studio environment: broad reflected sky/ground and soft light panels.
      // No external texture or changing simulation sun is needed for this display material.
      vec3 reflection = reflect(-view, n);
      vec3 environment = mix(vec3(0.12, 0.14, 0.17), vec3(0.85, 0.90, 1.0), smoothstep(-0.35, 0.65, reflection.y));
      environment += vec3(2.5, 2.4, 2.3) * pow(max(dot(reflection, normalize(vec3(-0.45, 0.65, -0.60))), 0.0), 8.0);
      environment += vec3(1.6) * pow(max(dot(reflection, normalize(vec3(-0.4, 0.65, 0.7))), 0.0), 14.0);
      environment += vec3(0.7, 0.75, 0.85) * pow(max(dot(reflection, normalize(vec3(0.9, 0.1, 0.4))), 0.0), 10.0);
      vec3 fresnel = material.specular + (vec3(1.0) - material.specular) * pow(1.0 - max(dot(n, view), 0.0), 5.0);
      material.diffuse = czm_pbrNeutralTonemapping(direct + environment * fresnel);
    }
  `});
  // GGX direct light plus studio reflection is computed above. UNLIT prevents a
  // second scene-light pass; this is a display material, not a physical sensor model.
}
