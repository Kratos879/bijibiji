"""Bilibili normalization, local persistence and model adapters."""
import base64, copy, html, json, os, re, sqlite3, time, uuid
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlsplit
import httpx

ROOT = Path(__file__).resolve().parent.parent
if (ROOT / '.tools').is_dir():
    os.environ['PATH'] = str(ROOT / '.tools') + os.pathsep + os.environ.get('PATH', '')
DATA = Path(os.environ.get('KEJING_DATA', ROOT / 'data')).resolve()
DATA.mkdir(parents=True, exist_ok=True)
os.chmod(DATA, 0o700)
DB = DATA / 'kejing.sqlite3'
DEFAULTS = {
    'text': {'base_url': '', 'model': '', 'api_key': ''},
    'vision': {'base_url': '', 'model': '', 'api_key': ''},
    'asr': {'base_url': '', 'model': '', 'api_key': ''},
    'cookie': '', 'frame_interval': 30, 'max_frames': 48,
    'prefer_subtitles': True, 'glossary': '',
}
TEMPLATES = [
    {'id':'lecture','name':'课程讲义','tag':'完整知识脉络','prompt':'生成详细课程讲义。按主题划分章节，每章保留定义、解释、例子、推导和结论。不要把课程压缩成只有要点的摘要。'},
    {'id':'tutorial','name':'实操教程','tag':'一步一步，学会应用','prompt':'生成可跟做的教程。包含目标、前置条件、操作步骤、对应截图、注意事项和常见问题。只写材料支持的操作，不虚构按钮、命令或参数。'},
    {'id':'academic','name':'学术报告','tag':'论据与结论并重','prompt':'生成学术报告风格的笔记，结构为问题、背景、方法、论据、结论和局限。区分讲者观点与事实。没有提供的方法、数据、文献或局限标为未提及，禁止补造引用。'},
    {'id':'review','name':'复习提纲','tag':'把重点留在眼前','prompt':'生成精简复习笔记：核心概念、知识关系、关键公式、易错点、复习问题。复习题标为AI生成，答案必须有材料依据。'},
]

def connect():
    c = sqlite3.connect(DB, timeout=30)
    c.execute('PRAGMA journal_mode=WAL')
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    os.chmod(DB, 0o600)

def get_value(key, default):
    with connect() as c: row = c.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else copy.deepcopy(default)

def put_value(key, value):
    with connect() as c: c.execute('INSERT OR REPLACE INTO kv VALUES (?,?)', (key, json.dumps(value, ensure_ascii=False)))

def settings(): return get_value('settings', DEFAULTS)
def templates():
    data=get_value('templates', TEMPLATES)
    if not get_value('templates_v2_migrated',False):
        old=['完整知识脉络','一步一步，学会应用','论据与结论并重','把重点留在眼前']
        new=['按知识点整理，保留解释和例子','按步骤整理，附操作截图','整理问题、方法、论据和结论','提取重点、术语和易错点']
        for t in data:
            if t.get('tag') in old:t['tag']=new[old.index(t['tag'])]
        data=[t for t in data if t.get('mode')!='selftest']
        put_value('templates',data);put_value('templates_v2_migrated',True)
    return data

def save_job(job):
    with connect() as c: c.execute('INSERT OR REPLACE INTO jobs VALUES (?,?)', (job['id'], json.dumps(job, ensure_ascii=False)))

def get_job(jid):
    with connect() as c: row = c.execute('SELECT payload FROM jobs WHERE id=?', (jid,)).fetchone()
    if not row: raise ValueError('找不到这份笔记')
    return json.loads(row[0])

def jobs():
    with connect() as c: rows = c.execute('SELECT payload FROM jobs ORDER BY rowid DESC').fetchall()
    return [json.loads(r[0]) for r in rows]

def update_job(jid, **values):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT payload FROM jobs WHERE id=?',(jid,)).fetchone()
        if not row:raise ValueError('找不到这份笔记')
        j=json.loads(row[0]);j.update(values);j['updated_at']=time.time()
        c.execute('UPDATE jobs SET payload=? WHERE id=?',(json.dumps(j,ensure_ascii=False),jid))
    return j

BVID = r'BV[1-9A-HJ-NP-Za-km-z]{10}'
ALLOWED = {'bilibili.com','www.bilibili.com','m.bilibili.com','space.bilibili.com','b23.tv','www.b23.tv'}

def normalize_link(raw, resolve_short=True):
    raw = html.unescape(raw.strip()).replace('\\_', '_').replace('\\&', '&')
    if len(raw)>12000: raise ValueError('链接内容太长，请只粘贴分享文字或视频链接')
    m = re.search(r'https?://[^\s<>"\]）]+', raw)
    if not m:
        if re.fullmatch(BVID, raw): return {'bvid':raw, 'part':1,'url':f'https://www.bilibili.com/video/{raw}?p=1'}
        if re.fullmatch(r'av\d+', raw, re.I): return {'bvid':raw.lower(),'part':1,'url':f'https://www.bilibili.com/video/{raw.lower()}?p=1'}
        if re.match(r'(?:www\.|m\.)?bilibili\.com/|b23\.tv/', raw): raw = 'https://' + raw; m = re.search(r'https?://\S+',raw)
        else: raise ValueError('请粘贴 B站视频链接、分享文字或 BV / av 号')
    candidate = m.group(0).rstrip('。，,;）)')
    u = urlsplit(candidate)
    if u.hostname not in ALLOWED or u.username or u.password or u.port not in (None,80,443): raise ValueError('目前只支持哔哩哔哩链接')
    if u.hostname in {'b23.tv','www.b23.tv'}:
        if not resolve_short: return {'short_url':candidate}
        with httpx.Client(timeout=20, follow_redirects=False, trust_env=True) as client:
            for _ in range(6):
                u = urlsplit(candidate)
                if u.hostname not in ALLOWED or u.username or u.password or u.port not in (None,80,443): raise ValueError('短链接跳转到了不支持的地址')
                if u.hostname not in {'b23.tv','www.b23.tv'}: return normalize_link(candidate, False)
                r = client.get(candidate, headers={'User-Agent':'Mozilla/5.0'})
                if r.is_redirect: candidate = urljoin(candidate, r.headers['location'])
                else: break
        raise ValueError('短链接解析失败，请稍后重试或从视频播放页复制链接')
    decoded = unquote(candidate)
    parts = urlsplit(decoded)
    params = parse_qs(parts.query)
    fragment = parts.fragment
    if '?' in fragment: params.update(parse_qs(fragment.split('?',1)[1]))
    elif '=' in fragment: params.update(parse_qs(fragment))
    ids = params.get('bvid', [])
    bvid = next((x for x in ids if re.fullmatch(BVID,x)), None)
    if not bvid:
        match = re.search(BVID, parts.path + '/' + fragment)
        if match: bvid = match.group(0)
    if not bvid:
        aid = (params.get('aid') or [''])[0]
        # List playback pages can use oid for a video aid (otype=2).
        if not aid and (params.get('otype') == ['2'] or parts.path.rstrip('/') == '/list/watchlater'):
            aid = (params.get('oid') or [''])[0]
        match = re.search(r'(?:/|#|^)av(\d+)(?:\D|$)', parts.path + '/' + fragment, re.I)
        if aid.isdigit(): bvid = 'av' + aid
        elif match: bvid = 'av' + match.group(1)
    if not bvid: raise ValueError('这个链接是列表页面，没有指定视频。请在“稍后再看”或收藏夹中打开某个视频，再复制播放页地址。')
    path_part = re.search(r'/p(\d+)(?:/|$|\?)', parts.path + '/' + fragment)
    try: part = int((params.get('p') or [path_part.group(1) if path_part else '1'])[0])
    except ValueError: raise ValueError('分 P 参数无效')
    if not 1 <= part <= 10000: raise ValueError('分 P 参数超出范围')
    return {'bvid':bvid,'part':part,'url':f'https://www.bilibili.com/video/{bvid}?p={part}'}

def stamp(seconds):
    n = int(float(seconds)); return f'{n//3600:02d}:{n//60%60:02d}:{n%60:02d}'

def endpoint(config, suffix):
    base = config.get('base_url','').strip().rstrip('/')
    u = urlsplit(base)
    if u.scheme not in ('http','https') or not u.hostname or u.username or u.password or u.query or u.fragment: raise ValueError('API 地址需要是有效的 http(s) 基础地址，如 https://服务商/v1')
    if not config.get('model'): raise ValueError('请在设置中填写模型名称')
    return base + '/' + suffix

class OutputLimitError(ValueError):
    pass

def chat(config, messages, max_tokens=8000):
    url = endpoint(config,'chat/completions')
    headers = {'Authorization':'Bearer ' + config.get('api_key','')} if config.get('api_key') else {}
    payload={'model':config['model'],'messages':messages,'max_tokens':max_tokens}
    # Official DeepSeek defaults to thinking, which shares the output budget.
    # Extraction and note writing use explicit non-thinking mode; other providers stay unchanged.
    if urlsplit(url).hostname=='api.deepseek.com' and config['model'] in {'deepseek-flash','deepseek-v4-pro','deepseek-v4-flash','deepseek-v4-flash-vision-exp'}:
        payload['thinking']={'type':'disabled'}
    length_retried=False
    for attempt in range(4):
        try:
            with httpx.Client(timeout=httpx.Timeout(240, connect=20)) as c:
                r = c.post(url, headers=headers,json=payload)
            if r.status_code in (429,500,502,503,504) and attempt<2: time.sleep(2**attempt); continue
            if r.status_code >= 400: raise ValueError(f'模型接口返回 HTTP {r.status_code}，请检查模型、地址、额度和密钥')
            result = r.json(); choice = result['choices'][0]
            if choice.get('finish_reason') == 'length':
                if not length_retried and payload['max_tokens']<32000:
                    length_retried=True
                    payload['max_tokens']=min(32000,payload['max_tokens']*2)
                    continue
                raise OutputLimitError('模型输出达到长度上限，自动扩容后仍未完成；已保存的材料可继续复用')
            content = choice['message'].get('content')
            if not isinstance(content,str) or not content.strip(): raise ValueError('模型返回了空内容，请检查模型是否支持此任务')
            return content
        except (httpx.TimeoutException,httpx.ConnectError) as e:
            if attempt==3: raise ValueError('模型服务连接失败或超时，请检查网络与 API 地址') from e
            time.sleep(2**attempt)

    raise ValueError('模型请求未完成，请继续处理重试')

def image_data(path): return 'data:image/jpeg;base64,' + base64.b64encode(Path(path).read_bytes()).decode()

init_db()
