import { CameraEventType, Cartesian2, Cartesian3, ScreenSpaceEventHandler, ScreenSpaceEventType, type Viewer } from 'cesium';

/** Left pans, right orbits, wheel zooms, including in the moving follow frame. */
export class MapNavigation {
  private readonly handler:ScreenSpaceEventHandler;
  private readonly restore:()=>void;
  private readonly untrack:()=>void;
  private readonly pixel=new Cartesian2();
  private panning=false;
  private readonly cancel=()=>{this.panning=false;};
  constructor(private readonly viewer:Viewer){
    const controller=viewer.scene.screenSpaceCameraController;
    const saved={translateEventTypes:controller.translateEventTypes,rotateEventTypes:controller.rotateEventTypes,zoomEventTypes:controller.zoomEventTypes,tiltEventTypes:controller.tiltEventTypes};
    this.restore=()=>Object.assign(controller,saved);
    controller.translateEventTypes=CameraEventType.LEFT_DRAG;
    controller.zoomEventTypes=[CameraEventType.WHEEL,CameraEventType.PINCH];
    const tilt=saved.tiltEventTypes;
    controller.tiltEventTypes=[CameraEventType.RIGHT_DRAG,...(Array.isArray(tilt)?tilt:tilt===undefined?[]:[tilt])];
    const tracking=()=>{
      this.cancel();
      // Cesium's globe drag pans in a free frame, but orbits in an entity frame.
      controller.rotateEventTypes=viewer.trackedEntity?CameraEventType.RIGHT_DRAG:CameraEventType.LEFT_DRAG;
    };
    this.untrack=viewer.trackedEntityChanged.addEventListener(tracking);tracking();
    this.handler=new ScreenSpaceEventHandler(viewer.canvas);
    this.handler.setInputAction(()=>{this.panning=Boolean(viewer.trackedEntity)&&controller.enableInputs;},ScreenSpaceEventType.LEFT_DOWN);
    this.handler.setInputAction(this.cancel,ScreenSpaceEventType.LEFT_UP);
    this.handler.setInputAction((movement:{startPosition:Cartesian2;endPosition:Cartesian2})=>{
      if(!this.panning||!viewer.trackedEntity||!controller.enableInputs||!controller.enableTranslate)return;
      const camera=viewer.camera,canvas=viewer.canvas;
      if(!canvas.clientWidth||!canvas.clientHeight)return;
      const distance=Math.max(camera.frustum.near,Cartesian3.magnitude(camera.position));
      camera.frustum.getPixelDimensions(canvas.clientWidth,canvas.clientHeight,distance,1,this.pixel);
      camera.moveRight(-(movement.endPosition.x-movement.startPosition.x)*this.pixel.x);
      camera.moveUp((movement.endPosition.y-movement.startPosition.y)*this.pixel.y);
      viewer.scene.requestRender();
    },ScreenSpaceEventType.MOUSE_MOVE);
    window.addEventListener('mouseup',this.cancel);window.addEventListener('blur',this.cancel);
  }
  destroy(){
    this.cancel();this.untrack();this.handler.destroy();
    window.removeEventListener('mouseup',this.cancel);window.removeEventListener('blur',this.cancel);
    if(!this.viewer.isDestroyed())this.restore();
  }
}
