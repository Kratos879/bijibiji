/* Decorative only: no task data or credentials are sent to the video host. */
(()=>{
 const scene=document.querySelector('.scene');
 scene.innerHTML='<div class="scene-orbit"></div><div class="head-position"><div class="head-motion"><div class="head-window"><div class="head-fallback"></div><video muted playsinline preload="auto" disablepictureinpicture tabindex="-1"></video></div></div></div>';
 const launcher=document.createElement('button');launcher.id='qaLauncher';launcher.type='button';launcher.setAttribute('aria-label','打开笔记提问');launcher.setAttribute('aria-expanded','false');launcher.setAttribute('aria-controls','qaFloat');
 launcher.append(scene.querySelector('.head-position'));launcher.insertAdjacentHTML('beforeend','<span class="launcher-label">笔记提问</span>');document.body.append(launcher);
 const video=launcher.querySelector('video'),head=launcher.querySelector('.head-motion');
 const reduced=matchMedia('(prefers-reduced-motion: reduce)');
 let target=0,pointerX=.5,seeking=false,busy=false;
 function seek(){if(reduced.matches||document.hidden||seeking||!Number.isFinite(video.duration)||Math.abs(video.currentTime-target)<.035)return;seeking=true;video.currentTime=target}
 video.addEventListener('loadeddata',()=>{video.classList.add('ready');video.parentElement.classList.add('loaded');target=pointerX*Math.max(0,video.duration-.08);seek()});
 video.addEventListener('seeked',()=>{seeking=false;seek()});
 video.addEventListener('error',()=>{video.classList.remove('ready');video.parentElement.classList.remove('loaded')});
 video.src='https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260530_042513_df96a13b-6155-4f6e-8b93-c9dee66fba08.mp4';
 // Absolute viewport coordinates avoid accumulating at the clip's endpoints.
 window.addEventListener('pointermove',e=>{
  if(e.pointerType==='touch'||reduced.matches)return;
  pointerX=Math.max(0,Math.min(1,e.clientX/innerWidth));
  launcher.style.setProperty('--head-look',`${(pointerX-.5)*30}deg`);
  launcher.style.setProperty('--head-pitch',`${(.5-e.clientY/innerHeight)*16}deg`);
  if(Number.isFinite(video.duration)){target=pointerX*Math.max(0,video.duration-.08);seek()}
 },{passive:true,capture:true});
 window.bijiScene={setBusy(value){busy=!!value;launcher.dataset.busy=String(busy)}};
 document.addEventListener('visibilitychange',()=>{head.style.animationPlayState=document.hidden?'paused':'running';if(!document.hidden)seek()});
 reduced.addEventListener('change',()=>{if(reduced.matches){launcher.style.setProperty('--head-look','0deg');launcher.style.setProperty('--head-pitch','0deg')}});

})();
