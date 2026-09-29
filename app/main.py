import copy, hmac, io, json, os, re, secrets, shutil, threading, time, uuid, zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .core import DATA, DEFAULTS, ROOT, chat, get_job, jobs, normalize_link, put_value, save_job, settings, stamp, templates, update_job
from .pipeline import process
from . import qa

POOL=ThreadPoolExecutor(max_workers=1)
LOCK=threading.Lock()
TOKEN=os.environ.get('KEJING_ACCESS_TOKEN','')

@asynccontextmanager
async def lifespan(app):
    qa.recover()
    for job in jobs():
        if job['status'] in ('queued','running'):
            update_job(job['id'],status='error',stage='上次处理被中断',error='服务重新启动，可点击重试从缓存继续')
        if job.get('quiz_status')=='running':
            update_job(job['id'],quiz_status='error',quiz_error='上次自测生成被中断，请点击重试自测')
    yield
    POOL.shutdown(wait=False,cancel_futures=True)
    qa.POOL.shutdown(wait=False,cancel_futures=True)

app=FastAPI(title='哔记 BijiBiji',lifespan=lifespan)

@app.middleware('http')
async def security(request:Request,call_next):
    host=request.headers.get('host','')
    hostname=urlsplit('//'+host).hostname
    if not TOKEN and hostname not in ('127.0.0.1','localhost','::1','testserver'):
        return JSONResponse({'detail':'远程访问需要先设置 KEJING_ACCESS_TOKEN'},status_code=403)
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin')
        if origin and urlsplit(origin).netloc!=host:return JSONResponse({'detail':'禁止跨站提交'},status_code=403)
    if request.url.path.startswith(('/api/','/media/')) and TOKEN:
        supplied=request.headers.get('authorization','').removeprefix('Bearer ') or request.cookies.get('kejing_session','')
        if not hmac.compare_digest(supplied,TOKEN):return JSONResponse({'detail':'需要输入访问口令'},status_code=401)
    r=await call_next(request)
    r.headers['X-Content-Type-Options']='nosniff'
    r.headers['Referrer-Policy']='no-referrer'
    r.headers['X-Frame-Options']='DENY'
    r.headers['Content-Security-Policy']="default-src 'self'; media-src 'self' https://d8j0ntlcm91z4.cloudfront.net; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
    if request.url.path.startswith(('/api/','/media/')):r.headers['Cache-Control']='no-store'
    return r

@app.exception_handler(ValueError)
async def value_error(request,exc):return JSONResponse({'detail':str(exc)},status_code=400)

@app.post('/session')
async def session(request:Request):
    data=await request.json()
    if TOKEN and not hmac.compare_digest(str(data.get('token','')),TOKEN):raise HTTPException(401,'访问口令不正确')
    response=JSONResponse({'ok':True})
    response.set_cookie('kejing_session',TOKEN,httponly=True,samesite='strict',secure=request.url.scheme=='https',max_age=86400)
    return response

@app.get('/api/health')
def health():return {'ok':True,'ffmpeg':bool(shutil.which('ffmpeg')),'ffprobe':bool(shutil.which('ffprobe')),'configured':all(settings()[k]['base_url'] and settings()[k]['model'] for k in ('text','vision'))}

@app.get('/api/settings')
def read_settings():
    cfg=copy.deepcopy(settings())
    for k in ('text','vision','asr'):cfg[k]['has_key']=bool(cfg[k]['api_key']);cfg[k]['api_key']=''
    cfg['has_cookie']=bool(cfg['cookie']);cfg['cookie']=''
    return cfg

@app.put('/api/settings')
async def write_settings(request:Request):
    data=await request.json();cfg=settings()
    for k in ('text','vision','asr'):
        section=data.get(k,{})
        for field in ('base_url','model','api_key'):
            if field in section:
                value=str(section[field]).strip()
                if len(value)>4000:raise ValueError('配置字段过长')
                if field!='api_key' or value:cfg[k][field]=value
        if section.get('clear_key'):cfg[k]['api_key']=''
        if k == 'asr':
            provider=section.get('provider',cfg[k].get('provider','openai'))
            if provider not in ('openai','doubao'):raise ValueError('未知语音服务')
            auth=section.get('auth_mode',cfg[k].get('auth_mode','api_key'))
            if auth not in ('api_key','app_token'):raise ValueError('未知认证方式')
            # Switching credential types must not silently reuse the old provider key.
            if (provider != cfg[k].get('provider','openai') or auth != cfg[k].get('auth_mode','api_key')) and not section.get('api_key'):
                cfg[k]['api_key']=''
            cfg[k].update(provider=provider,auth_mode=auth,app_id=str(section.get('app_id',cfg[k].get('app_id',''))).strip()[:100])
            if provider=='doubao':
                cfg[k]['base_url']='https://openspeech.bytedance.com/api/v3/auc/bigmodel'
                cfg[k]['model']='volc.seedasr.auc'
        base=cfg[k]['base_url']
        if base:
            u=urlsplit(base)
            if u.scheme not in ('http','https') or not u.hostname or u.username or u.password or u.query or u.fragment:raise ValueError('API 基础地址格式不正确')
    if data.get('cookie'):cfg['cookie']=str(data['cookie']).strip()[:16000]
    if data.get('clear_cookie'):cfg['cookie']=''
    cfg['frame_interval']=max(5,min(120,int(data.get('frame_interval',cfg['frame_interval']))))
    cfg['max_frames']=max(8,min(120,int(data.get('max_frames',cfg['max_frames']))))
    cfg['prefer_subtitles']=bool(data.get('prefer_subtitles',cfg['prefer_subtitles']))
    cfg['glossary']=str(data.get('glossary',cfg['glossary']))[:4000]
    put_value('settings',cfg);return read_settings()

@app.get('/api/templates')
def list_templates():return [t for t in templates() if t.get('mode')!='selftest']

@app.put('/api/templates')
async def write_templates(request:Request):
    data=await request.json()
    if not isinstance(data,list) or not 1<=len(data)<=20:raise ValueError('模板数量需在 1–20 个之间')
    seen=set();clean=[]
    for t in data:
        tid=str(t.get('id',''))
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,60}',tid) or tid in seen:raise ValueError('模板标识无效或重复')
        name=str(t.get('name','')).strip();prompt=str(t.get('prompt','')).strip()
        if not name or not prompt or len(prompt)>6000 or len(name)>40:raise ValueError('请填写模板名称和要求，要求最长 6000 字')
        mode=t.get('mode','note')
        if mode!='note':raise ValueError('自测已改为笔记生成后的可选步骤，模板仅能用于生成笔记')
        seen.add(tid);clean.append({'id':tid,'name':name,'prompt':prompt,'tag':str(t.get('tag','自定义笔记'))[:60],'mode':mode})
    put_value('templates',clean);return clean

class LinkInput(BaseModel):text:str=Field(max_length=12000)
@app.post('/api/resolve')
def resolve(data:LinkInput):return normalize_link(data.text)

class CreateInput(BaseModel):
    text:str=Field(max_length=12000)
    template_id:str='lecture'
    analyze_video:bool=True
    instructions:str=Field(default='',max_length=4000)

@app.post('/api/jobs')
def create(data:CreateInput):
    cfg=settings()
    for key,label in ([('text','笔记生成'),('vision','画面理解')] if data.analyze_video else [('text','笔记生成')]):
        if not cfg[key]['base_url'] or not cfg[key]['model']:raise ValueError(f'请先在设置中配置{label} API 和模型')
    if not cfg['prefer_subtitles'] and (not cfg['asr']['base_url'] or not cfg['asr']['model']):raise ValueError('关闭字幕优先后，需要配置语音转写服务')
    template=next((t for t in templates() if t['id']==data.template_id),None)
    if not template:raise ValueError('请选择有效模板')
    if template.get('mode')=='selftest':raise ValueError('请先生成课程笔记，再从笔记页点击「生成自测」')
    source=normalize_link(data.text)
    with LOCK:
        active=[j for j in jobs() if j['status'] in ('queued','running')]
        if len(active)>=10:raise ValueError('队列已满，请等已有任务完成')
        if any(j['source']==source for j in active):raise ValueError('这个视频正在处理，请在历史记录中查看')
        jid=uuid.uuid4().hex
        job={'id':jid,'source':source,'title':source['bvid'],'template':template,'instructions':data.instructions,'analyze_video':data.analyze_video,'status':'queued','stage':'等待处理','progress':0,'created_at':time.time(),'updated_at':time.time(),'markdown':'','frames':[],'transcript':None,'visual':[],'error':None,'cancel_requested':False}
        save_job(job);POOL.submit(process,jid)
    return job

@app.get('/api/jobs')
def list_jobs():return [{k:v for k,v in j.items() if k not in ('markdown','transcript','visual','frames','quiz')} for j in jobs()]

@app.get('/api/jobs/{jid}')
def detail(jid:str):return get_job(jid)

def generate_study_for_job(jid):
    try:
        from .study import generate_quiz_from_note
        job=get_job(jid);cfg=settings()
        quiz=generate_quiz_from_note(cfg['text'],job['title'],job['markdown'],job.get('duration',0),job.get('frames',[]))
        update_job(jid,quiz=quiz,quiz_status='done',quiz_error=None,stage='自测已生成')
    except Exception as exc:
        update_job(jid,quiz_status='error',quiz_error=str(exc)[:1000],stage='自测生成失败')

@app.post('/api/jobs/{jid}/study/generate')
def generate_study(jid:str):
    with LOCK:
        job=get_job(jid)
        if job['status']!='done' or not job.get('markdown'):raise ValueError('请先完成笔记生成，再创建自测')
        if job.get('quiz_status')=='running':return {'status':'running'}
        if not settings()['text'].get('base_url') or not settings()['text'].get('model'):raise ValueError('请先配置笔记生成模型')
        if job.get('quiz'):
            folder=DATA/'jobs'/jid/'versions';folder.mkdir(parents=True,exist_ok=True)
            (folder/f'{int(time.time()*1000)}-study.json').write_text(json.dumps(job['quiz'],ensure_ascii=False))
        update_job(jid,quiz=None,quiz_status='running',quiz_error=None,stage='正在根据笔记生成自测')
        POOL.submit(generate_study_for_job,jid)
    return {'status':'running'}

@app.post('/api/jobs/{jid}/cancel')
def cancel(jid:str):
    with LOCK:
        j=get_job(jid)
        if j['status'] not in ('queued','running'):raise ValueError('此任务已结束')
        return update_job(jid,cancel_requested=True,stage='正在停止，当前模型请求完成后生效')

class RetryInput(BaseModel):
    template_id:str|None=None
    instructions:str|None=Field(default=None,max_length=4000)
    refresh_analysis:bool=False
    analyze_video:bool|None=None

@app.post('/api/jobs/{jid}/retry')
def retry(jid:str,data:RetryInput):
    with LOCK:
        j=get_job(jid)
        if j['status'] in ('running','queued'):raise ValueError('任务仍在处理中')
        if j.get('quiz_status')=='running':raise ValueError('自测生成过程中暂时不能重新生成笔记')
        if j.get('template',{}).get('mode')=='selftest':j['template']=next((t for t in templates() if t.get('mode')!='selftest'),templates()[0])
        if data.template_id:
            template=next((t for t in templates() if t['id']==data.template_id),None)
            if not template:raise ValueError('模板不存在')
            if template.get('mode')=='selftest':raise ValueError('自测已改为笔记生成后的可选步骤')
            j['template']=template
        if data.instructions is not None:j['instructions']=data.instructions
        folder=DATA/'jobs'/jid
        if data.analyze_video is not None:
            if data.analyze_video and not all(settings()['vision'].get(k) for k in ('base_url','model')):raise ValueError('开启画面分析需要配置画面理解模型')
            if data.analyze_video!=j.get('analyze_video',True):
                for cached in folder.glob('material-*.json'):cached.unlink()
            j['analyze_video']=data.analyze_video
        if j.get('markdown'):
            history=folder/'versions';history.mkdir(parents=True,exist_ok=True)
            (history/f'{int(time.time()*1000)}.md').write_text(j['markdown'])
        if j.get('quiz'):
            history=folder/'versions';history.mkdir(parents=True,exist_ok=True)
            (history/f'{int(time.time()*1000)}-study.json').write_text(json.dumps(j['quiz'],ensure_ascii=False))
        if data.refresh_analysis:
            for p in folder.glob('*.json'):
                if p.name!='metadata.json':p.unlink()
            shutil.rmtree(folder/'audio',ignore_errors=True)
            shutil.rmtree(folder/'frames',ignore_errors=True)
            j.update(frames=[],transcript=None,visual=[])
        j.update(status='queued',stage='等待重新生成',progress=0,cancel_requested=False,error=None,quiz=None,quiz_status=None,quiz_error=None)
        save_job(j);POOL.submit(process,jid)
    return j

class NoteInput(BaseModel):markdown:str=Field(max_length=300000)
@app.put('/api/jobs/{jid}/note')
def edit(jid:str,data:NoteInput):
    j=get_job(jid)
    if j['status'] in ('running','queued'):raise ValueError('生成过程中不能编辑笔记')
    if j.get('quiz_status')=='running':raise ValueError('自测生成过程中暂时不能编辑笔记')
    folder=DATA/'jobs'/jid;folder.mkdir(parents=True,exist_ok=True)
    if j.get('markdown'):
        history=folder/'versions';history.mkdir(exist_ok=True)
        (history/f'{int(time.time()*1000)}.md').write_text(j['markdown'])
    (folder/'note.md').write_text(data.markdown)
    changes={'markdown':data.markdown}
    if j.get('quiz'):
        history=folder/'versions';history.mkdir(parents=True,exist_ok=True)
        (history/f'{int(time.time()*1000)}-study.json').write_text(json.dumps(j['quiz'],ensure_ascii=False))
        changes.update(quiz=None,quiz_status=None,quiz_error=None)
    return update_job(jid,**changes)

class StudyResponse(BaseModel):
    version:str
    answer:str=Field(default='',max_length=12000)
    revealed:bool=False
    mastery:str='unmarked'

@app.put('/api/jobs/{jid}/study/{qid}')
def save_study_response(jid:str,qid:str,data:StudyResponse):
    with LOCK:
        j=get_job(jid);quiz=j.get('quiz')
        if j['status']!='done' or not quiz or quiz['version']!=data.version:
            raise HTTPException(409,'这份自测已更新，请刷新后作答')
        if not any(q['id']==qid for q in quiz['questions']):raise HTTPException(404,'题目不存在')
        if data.mastery not in ('unmarked','mastered','review'):raise ValueError('掌握状态无效')
        quiz.setdefault('responses',{})[qid]={'answer':data.answer,'revealed':data.revealed,'mastery':data.mastery,'saved_at':time.time()}
        update_job(jid,quiz=quiz)
    return quiz['responses'][qid]

class RetrievalInput(BaseModel):
    mode:Literal['auto','prepare','off']

class QuestionInput(BaseModel):
    question:str=Field(min_length=1,max_length=4000)
    selection:str=Field(default='',max_length=4000)
    scope:Literal['course','general']='course'
    request_id:str=Field(pattern=r'^[a-zA-Z0-9_-]{8,80}$')

@app.get('/api/jobs/{jid}/qa')
def qa_status(jid:str):return qa.public(jid)

@app.put('/api/jobs/{jid}/qa/retrieval')
def qa_retrieval(jid:str,data:RetrievalInput):return qa.set_mode(jid,data.mode)

@app.post('/api/jobs/{jid}/qa')
def qa_ask(jid:str,data:QuestionInput):
    if not data.question.strip():raise ValueError('请输入问题')
    return qa.submit(jid,data.question.strip(),data.selection,data.scope,data.request_id)

@app.delete('/api/jobs/{jid}/qa')
def qa_clear(jid:str):return qa.clear(jid)

@app.get('/api/jobs/{jid}/export')
def export(jid:str):
    j=get_job(jid)
    if not j.get('markdown'):raise ValueError('笔记尚未生成')
    md=j['markdown'];folder=DATA/'jobs'/jid
    for f in j.get('frames',[]):md=md.replace(f['url'],'images/'+f['file'])
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('笔记.md',md)
        conversation=qa.public(jid)
        if conversation['messages']:
            z.writestr('课程答疑.json',json.dumps(conversation,ensure_ascii=False,indent=2))
            z.writestr('课程答疑.md',qa.export_markdown(conversation))
        z.writestr('来源.json',json.dumps({'title':j['title'],'source':j['source'],'template':j['template'],'models':j.get('models_used',{})},ensure_ascii=False,indent=2))
        if j.get('quiz'):
            from .study import study_markdown
            z.writestr('自测问题.md',study_markdown(j['quiz'],j['title'],j['source']['url'],False))
            answers=study_markdown(j['quiz'],j['title'],j['source']['url']).split('## 参考答案',1)[1]
            for f in j.get('frames',[]):answers=answers.replace(f['url'],'images/'+f['file'])
            z.writestr('参考答案.md','# 参考答案\n'+answers)
            z.writestr('我的作答.json',json.dumps(j['quiz'].get('responses',{}),ensure_ascii=False,indent=2))
        segments=(j.get('transcript') or {}).get('segments',[])
        z.writestr('转写文本.md','\n\n'.join(f"[{stamp(s['start'])}] {s['text']}" for s in segments))
        z.writestr('转写时间轴.json',json.dumps(j.get('transcript'),ensure_ascii=False,indent=2))
        z.writestr('画面观察.md','\n\n'.join(v['text'] for v in j.get('visual',[])))
        sections=re.split(r'(?=^## )',md,flags=re.M)
        for i,section in enumerate(sections):
            if section.strip():z.writestr(f'章节/{i+1:02d}.md',section.replace('images/','../images/'))
        for f in j.get('frames',[]):
            path=folder/'frames'/f['file']
            if path.exists():z.write(path,'images/'+f['file'])
    return Response(output.getvalue(),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="bijibiji-{jid[:8]}.zip"'})

@app.get('/media/{jid}/frames/{name}')
def media(jid:str,name:str):
    if not re.fullmatch(r'[a-f0-9]{32}',jid) or not re.fullmatch(r'\d{10}\.jpg',name):raise HTTPException(404)
    path=DATA/'jobs'/jid/'frames'/name
    if not path.is_file():raise HTTPException(404)
    return FileResponse(path)

@app.get('/')
def index():return FileResponse(ROOT/'web'/'index.html',headers={'Cache-Control':'no-cache, must-revalidate'})
app.mount('/static',StaticFiles(directory=ROOT/'web'),name='static')
