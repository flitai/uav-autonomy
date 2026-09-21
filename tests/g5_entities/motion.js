// Observe frames actually presented by the scene, including the rendered model matrix.
new Promise(resolve => {
  const viewer=window.__g5Map.viewer,frames=[];
  let model;
  function find(p){
    if(p?.id?.id==='aircraft:400' && p.modelMatrix)model=p;
    if(typeof p?.get==='function' && typeof p.length==='number')for(let i=0;i<p.length;i++)find(p.get(i));
  }
  find(viewer.scene.primitives);
  const remove=viewer.scene.postRender.addEventListener(()=>{
    if(frames.length>=512)return;
    const state=window.__g5Entities.inspect(),pose=state.objects['400'];
    if(pose && model?.ready)frames.push({wall:performance.now(),clock:state.displayClock,followed:state.followed,
      time:pose.time,lower:pose.lower,upper:pose.upper,fraction:pose.fraction,position:pose.position,
      rendered:[model.modelMatrix[12],model.modelMatrix[13],model.modelMatrix[14]]});
  });
  setTimeout(()=>{remove();resolve(frames);},3000);
})
