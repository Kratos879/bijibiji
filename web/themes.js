/* Browser-local appearance settings. No API keys or note data are stored here. */
(() => {
 const presets = {
  paper:{name:'雾白',bg:'#edf0f7',accent:'#4056c8'},
  sand:{name:'米杏',bg:'#f2ece1',accent:'#955020'},
  green:{name:'浅绿',bg:'#e7efea',accent:'#256c51'},
  ink:{name:'石墨',bg:'#171b25',accent:'#a9b9ff'}
 };
 const defaults={preset:'paper',...presets.paper,opacity:96,font:105,glow:true};
 const validHex=v=>typeof v==='string'&&/^#[0-9a-f]{6}$/i.test(v);
 const rgb=h=>[1,3,5].map(i=>parseInt(h.slice(i,i+2),16));
 const luminance=h=>rgb(h).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4}).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);
 const contrast=(a,b)=>(Math.max(luminance(a),luminance(b))+.05)/(Math.min(luminance(a),luminance(b))+.05);
 let saved={};try{saved=JSON.parse(localStorage.getItem('bijibiji-theme-v1'))||{}}catch{}
 let theme={...defaults,...saved};
 theme.bg=validHex(theme.bg)?theme.bg:defaults.bg;theme.accent=validHex(theme.accent)?theme.accent:defaults.accent;
 theme.opacity=Math.max(85,Math.min(100,Number(theme.opacity)||96));theme.font=Math.max(100,Math.min(120,Number(theme.font)||105));theme.glow=theme.glow!==false;
 function apply(save=false){
  const dark=luminance(theme.bg)<.3;const ink=dark?'#f4f6fc':'#182235',muted=dark?'#c0c9da':'#4e5c70';const panel=dark?'#232a38':'#ffffff';
  const link=contrast(theme.accent,panel)>=4.5?theme.accent:ink;
  const values={'--page':theme.bg,'--page-ink':contrast('#ffffff',theme.bg)>=contrast('#111827',theme.bg)?'#ffffff':'#111827','--ink':ink,'--muted':muted,'--accent':theme.accent,'--accent-ink':contrast('#ffffff',theme.accent)>=contrast('#111827',theme.accent)?'#ffffff':'#111827','--link':link,'--panel-rgb':rgb(panel).join(','),'--panel-opacity':theme.opacity/100,'--solid':panel,'--soft':dark?'#2d3647':'#f4f6fa','--line':dark?'#485366':'#ccd3df','--error':dark?'#ffb7ab':'#a82a21','--type-scale':theme.font/100,'--glow-opacity':theme.glow?'.12':'0'};
  const el=document.documentElement;el.classList.add('theme-changing');clearTimeout(apply.timer);apply.timer=setTimeout(()=>el.classList.remove('theme-changing'),250);for(const [k,v] of Object.entries(values))el.style.setProperty(k,v);
  el.dataset.appearance=dark?'dark':'light';el.style.colorScheme=dark?'dark':'light';
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content',theme.bg);
  if(save)try{localStorage.setItem('bijibiji-theme-v1',JSON.stringify(theme))}catch{}
 }
 apply();
 document.addEventListener('DOMContentLoaded',()=>{
  const $=id=>document.getElementById(id),dialog=$('themeDialog');
  $('themePresets').innerHTML=Object.entries(presets).map(([key,p])=>`<button type="button" data-theme="${key}" class="theme-preset"><span class="theme-swatch" style="--swatch:${p.bg};--swatch-accent:${p.accent}"><i></i><i></i></span><strong>${p.name}</strong></button>`).join('');
  function sync(){document.querySelectorAll('[data-theme]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.theme===theme.preset)));$('themeAccent').value=theme.accent;$('themeBackground').value=theme.bg;$('themeOpacity').value=theme.opacity;$('themeFont').value=theme.font;$('themeGlow').checked=theme.glow;$('opacityValue').textContent=theme.opacity+'%';$('fontValue').textContent=theme.font+'%'}
  function update(){apply(true);sync()}
  document.querySelectorAll('[data-theme]').forEach(b=>b.onclick=()=>{theme={...theme,...presets[b.dataset.theme],preset:b.dataset.theme};update()});
  for(const [id,key] of [['themeAccent','accent'],['themeBackground','bg'],['themeOpacity','opacity'],['themeFont','font']])$(id).addEventListener('input',()=>{theme[key]=['opacity','font'].includes(key)?Number($(id).value):$(id).value;if(['accent','bg'].includes(key))theme.preset='custom';update()});
  $('themeGlow').onchange=()=>{theme.glow=$('themeGlow').checked;update()};
  $('resetTheme').onclick=()=>{theme={...defaults};update()};
  $('openTheme').onclick=()=>{sync();dialog.showModal()};$('closeTheme').onclick=$('doneTheme').onclick=()=>dialog.close();sync();
 });
})();
