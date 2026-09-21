// Observe frames actually presented by the scene, including the rendered model matrix.
new Promise(resolve => {
  const viewer=window.__g5Map.viewer,frames=[];
  let model;
  function find(p){
    if(p?.id?.id==='aircraft:400' && p.modelMatrix)model=p;
    if(typeof p?.get==='function' && typeof p.length==='number')for(let i=0;i<p.length;i++)find(p.get(i));
  }
  find(viewer.scene.primitives);
  // Measure in the FINAL rendered camera, not just ECEF model coordinates.
  const multiply=(m,a)=>[0,1,2,3].map(i=>m[i]*a[0]+m[i+4]*a[1]+m[i+8]*a[2]+m[i+12]*a[3]);
  const project=p=>{
    const clip=multiply(viewer.camera.frustum.projectionMatrix,multiply(viewer.camera.viewMatrix,[...p,1]));
    return [(clip[0]/clip[3]+1)*viewer.canvas.clientWidth/2,(1-clip[1]/clip[3])*viewer.canvas.clientHeight/2];
  };
  const remove=viewer.scene.postRender.addEventListener(()=>{
    if(frames.length>=512)return;
    const state=window.__g5Entities.inspect(),pose=state.objects['400'];
    if(pose && model?.ready)frames.push({wall:performance.now(),clock:state.displayClock,followed:state.followed,
      time:pose.time,lower:pose.lower,upper:pose.upper,fraction:pose.fraction,position:pose.position,
      rendered:[model.modelMatrix[12],model.modelMatrix[13],model.modelMatrix[14]],
      screen:project(pose.position),scale:model.scale,expectedScale:pose.scale,screenPixels:state.screenPixels,
      cameraLocal:[viewer.camera.position.x,viewer.camera.position.y,viewer.camera.position.z],
      cameraDirection:[viewer.camera.direction.x,viewer.camera.direction.y,viewer.camera.direction.z],
      trailPoints:pose.trailPoints});
  });
  setTimeout(()=>{remove();resolve(frames);},3000);
})
