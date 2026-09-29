/* Course-scoped conversation. Provider calls run on the server, survive refresh. */
(() => {
 const $=s=>document.querySelector(s);
 let jid=null,data=null,timer=null,selected='',quote='',loading=false,epoch=0;
 const panel=document.createElement('section');panel.id='qaFloat';panel.hidden=true;panel.setAttribute('role','region');panel.setAttribute('aria-label','笔记提问');
 panel.innerHTML='<header class="qa-float-header"><div><strong>笔记提问</strong><small id="qaCourseTitle">先生成或打开一份笔记</small></div><button type="button" id="closeQAFloat" aria-label="关闭笔记提问">×</button></header><p id="qaUnavailable">生成笔记后，或从历史记录打开一份已完成的笔记，就可以在这里提问。</p>';
 $('.work-grid').append(panel);panel.append($('#qaContent'));$('#qaContent').hidden=false;
 function open(){panel.hidden=false;document.body.classList.add('qa-docked');$('#qaLauncher').setAttribute('aria-expanded','true');if(jid){load();$('#qaQuestion').focus()}else $('#closeQAFloat').focus()}
 function close(){panel.hidden=true;document.body.classList.remove('qa-docked');$('#qaLauncher').setAttribute('aria-expanded','false');$('#qaLauncher').focus()}
 $('#qaLauncher').onclick=()=>panel.hidden?open():close();$('#closeQAFloat').onclick=close;
 panel.addEventListener('keydown',e=>{if(e.key==='Escape'){e.stopPropagation();close()}});
 function availability(job){$('#qaCourseTitle').textContent=job?.title||'先生成或打开一份笔记';$('#qaUnavailable').hidden=!!jid;$('#qaContent').hidden=!jid;$('#qaQuestion').disabled=!jid;$('#qaSend').disabled=!jid||busy()||loading;}
 const drafts=new Map();
 const busy=()=>data?.messages.some(m=>m.status==='running');
 function renderStatus(){
  if(!data)return;
  $('#retrievalMode').value=data.mode;
  $('#retrievalMode').disabled=busy();
  $('#retrievalStatus').textContent=({none:'未建立',building:'正在准备',ready:`已就绪 · ${data.chunk_count} 个片段`,error:'准备失败'}[data.index_status]||'未建立')+(data.mode==='off'?' · 当前不使用':'')+(data.index_error?' · '+data.index_error:'');
  $('#retryRetrieval').hidden=data.index_status!=='error';
  $('#qaSend').disabled=busy()||loading;$('#clearQA').disabled=busy();
  $('#qaHint').textContent=busy()?'正在回答，可以切换笔记或离开页面；刷新后会恢复。':'使用笔记生成模型回答，会产生模型调用费用。';
 }
 function render(){
  if(!data)return;
  const box=$('#qaMessages'),nearBottom=box.scrollHeight-box.scrollTop-box.clientHeight<90;
  const signature=JSON.stringify(data.messages);
  if(box.dataset.signature!==signature){
   box.dataset.signature=signature;
   box.innerHTML=data.messages.length?data.messages.map(m=>{
    if(m.role==='user')return `<section class="qa-message qa-user"><strong>你</strong>${m.selection?`<blockquote>${escape(m.selection)}</blockquote>`:''}<p>${escape(m.content)}</p></section>`;
    return `<section class="qa-message qa-assistant"><div class="qa-answer-meta"><strong>回答</strong><span>${escape(m.model||'')}</span></div>${m.route?`<p class="qa-route">${escape(m.route)}</p>`:''}${m.status==='running'?`<p class="qa-running">${escape(m.stage)}…</p>`:`<div class="prose">${markdown(m.content)}</div>`}${m.status==='error'?`<button class="secondary-button" data-reask="${escape(m.id)}">重新发送</button>`:''}${m.sources?.length?`<details class="qa-sources"><summary>本次参考材料 · ${m.sources.length} 段</summary>${m.sources.map(s=>`<a href="${escape(safeUrl(s.url))}" target="_blank" rel="noopener noreferrer"><strong>[${escape(s.id)}] ${escape(s.kind)}${s.start!=null?' · '+stamp(s.start):''} ↗</strong><span>${escape(s.excerpt)}</span></a>`).join('')}</details>`:''}</section>`;
   }).join(''):'<div class="qa-empty"><h3>哪里还没理解？</h3><p>可以让我补充基础、换个例子，或者解释笔记中的一句话。</p><p>先在笔记里选中文字，再点“解释所选内容”。</p></div>';
   if(nearBottom)box.scrollTop=box.scrollHeight;
   box.querySelectorAll('[data-reask]').forEach(b=>b.onclick=()=>{const i=data.messages.findIndex(m=>m.id===b.dataset.reask),u=data.messages[i-1];if(!u)return;$('#qaQuestion').value=u.content;quote=u.selection||'';$('#qaScope').value=u.scope||'course';renderQuote();$('#qaQuestion').focus();$('#qaForm').requestSubmit()});
  }
  renderStatus();
 }
 function renderQuote(){const el=$('#qaSelection');el.hidden=!quote;el.querySelector('span').textContent=quote;}
 async function load(){
  if(!jid)return;const target=jid,version=epoch;
  try{const result=await api(`/api/jobs/${target}/qa`);if(jid!==target||epoch!==version)return;data=result;render();clearTimeout(timer);if(busy()||data.index_status==='building')timer=setTimeout(load,1400)}catch(e){if(jid===target){toast(e.message);clearTimeout(timer);timer=setTimeout(load,5000)}}
 }
 function setJob(job){
  const next=job?.status==='done'?job.id:null;if(next===jid){availability(job);return;}
  if(jid)drafts.set(jid,{question:$('#qaQuestion').value,quote,scope:$('#qaScope').value});
  jid=next;availability(job);epoch++;data=null;clearTimeout(timer);selected='';loading=false;
  const draft=drafts.get(jid);quote=draft?.quote||'';$('#qaQuestion').value=draft?.question||'';$('#qaScope').value=draft?.scope||'course';renderQuote();$('#qaMessages').dataset.signature='';$('#qaMessages').innerHTML='';
  $('#qaModel').textContent='使用当前笔记生成模型';if(jid)load();
 }
 $('#openRetrieval').onclick=async()=>{await load();if(jid)$('#retrievalDialog').showModal()};
 async function mode(value){if(!jid)return;const target=jid;$('#retrievalMode').disabled=true;try{const result=await api(`/api/jobs/${target}/qa/retrieval`,{method:'PUT',body:JSON.stringify({mode:value})});if(target!==jid)return;data=result;render();if(data.index_status==='building')load()}catch(e){toast(e.message)}finally{if(target===jid)renderStatus()}}
 $('#retrievalMode').onchange=()=>mode($('#retrievalMode').value);$('#retryRetrieval').onclick=()=>mode('prepare');
 $('#qaForm').onsubmit=async event=>{
  event.preventDefault();if(!jid||busy()||loading)return;const question=$('#qaQuestion').value.trim();if(!question)return;
  const target=jid,request_id=crypto.randomUUID();loading=true;renderStatus();
  try{const result=await api(`/api/jobs/${target}/qa`,{method:'POST',body:JSON.stringify({question,selection:quote,scope:$('#qaScope').value,request_id})});drafts.delete(target);if(target!==jid)return;data=result;$('#qaQuestion').value='';quote='';renderQuote();render();$('#qaMessages').scrollTop=$('#qaMessages').scrollHeight;load()}catch(e){if(target===jid)toast(e.message)}finally{if(target===jid){loading=false;renderStatus()}}
 };
 $('#qaQuestion').onkeydown=e=>{if(e.key==='Enter'&&(e.metaKey||e.ctrlKey)){e.preventDefault();$('#qaForm').requestSubmit()}};
 $('#removeQASelection').onclick=()=>{quote='';renderQuote()};
 $('#clearQA').onclick=async()=>{if(!jid||!confirm('清空当前视频的答疑记录？笔记和检索索引会保留。可先通过导出笔记保存对话。'))return;const target=jid;try{const result=await api(`/api/jobs/${target}/qa`,{method:'DELETE'});if(target===jid){data=result;render()}}catch(e){toast(e.message)}};
 document.addEventListener('selectionchange',()=>{
  const selection=window.getSelection(),article=$('#noteContent');
  if(!jid||state.tab!=='note'||!selection?.rangeCount)return;
  if(article.contains(selection.anchorNode)&&article.contains(selection.focusNode)){
   selected=selection.toString().trim().slice(0,4000);$('#explainBar').hidden=!selected;
  }
 });
 $('#explainSelection').onclick=()=>{if(!selected)return;quote=selected;renderQuote();setTab('qa');$('#qaQuestion').value='请解释这段内容，必要时补充基础知识并举例。';$('#qaQuestion').focus()};
 window.courseQA={setJob,load,open};setJob(state.job);
})();
