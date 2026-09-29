import io, json, os, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
os.environ['KEJING_DATA']=tempfile.mkdtemp(prefix='kejing-tests-')
from fastapi.testclient import TestClient
from app.core import normalize_link, settings, put_value, save_job, get_job, templates, DATA
from app.main import app
from app.pipeline import get_subtitles, extract_frames, process, dump

BV='BV1xx411c7mD'
class LinkTests(unittest.TestCase):
    def test_bilibili_variants(self):
        cases=[(BV,1),('https://www.bilibili.com/video/'+BV+'?p=3&spm_id_from=333',3),('https://www.bilibili.com/list/watchlater?bvid='+BV+'&p=2',2),('https://www.bilibili.com/watchlater/#/'+BV+'/p4',1),('https://www.bilibili.com/watchlater/#/list?bvid='+BV+'&p=4',4),('【课程分享】 https://m.bilibili.com/video/'+BV+'?p=2',2),('https://www.bilibili.com/medialist/play/watchlater?bvid='+BV+'&p=7',7),('https://www.bilibili.com/list/ml123?oid=99&bvid='+BV,1)]
        cases=[(link,4 if '/p4' in link else part) for link,part in cases]
        for link,part in cases:
            with self.subTest(link=link):
                r=normalize_link(link);self.assertEqual(r['bvid'],BV);self.assertEqual(r['part'],part)
    def test_aid(self):self.assertEqual(normalize_link('https://www.bilibili.com/watchlater/#/av123?p=2')['bvid'],'av123')
    def test_watchlater_oid(self):
        self.assertEqual(normalize_link('https://www.bilibili.com/list/watchlater?oid=123456&otype=2&p=2')['url'],'https://www.bilibili.com/video/av123456?p=2')
    def test_invalid(self):
        for link in ['https://www.bilibili.com/list/watchlater','https://evil.com/'+BV,'https://bilibili.com.evil.com/video/'+BV,'https://127.0.0.1/'+BV,'https://user:pass@bilibili.com/video/'+BV,'https://bilibili.com:8123/video/'+BV,'https://bilibili.com/video/'+BV+'?p=0']:
            with self.assertRaises(ValueError):normalize_link(link)
    def test_short_redirect(self):
        import httpx
        transport=httpx.MockTransport(lambda r:httpx.Response(302,headers={'location':'https://www.bilibili.com/video/'+BV+'?p=2'}))
        original=httpx.Client
        with patch('app.core.httpx.Client',side_effect=lambda **kw:original(transport=transport,**kw)):
            self.assertEqual(normalize_link('https://b23.tv/abcdef')['part'],2)
    def test_short_redirect_blocks_private(self):
        import httpx
        transport=httpx.MockTransport(lambda r:httpx.Response(302,headers={'location':'http://127.0.0.1/admin'}))
        original=httpx.Client
        with patch('app.core.httpx.Client',side_effect=lambda **kw:original(transport=transport,**kw)):
            with self.assertRaises(ValueError):normalize_link('https://b23.tv/abcdef')

class APITests(unittest.TestCase):
    def setUp(self):self.client=TestClient(app)
    def test_secrets_masked_and_preserved(self):
        r=self.client.put('/api/settings',json={'text':{'base_url':'https://example.com/v1','model':'x','api_key':'test-secret'},'cookie':'SESSDATA=test-cookie'})
        self.assertEqual(r.status_code,200);self.assertNotIn('test-secret',r.text);self.assertNotIn('test-cookie',r.text)
        self.client.put('/api/settings',json={'text':{'api_key':''}})
        self.assertEqual(settings()['text']['api_key'],'test-secret')
        self.client.put('/api/settings',json={'text':{'clear_key':True},'clear_cookie':True})
        self.assertEqual(settings()['text']['api_key'],'');self.assertEqual(settings()['cookie'],'')
    def test_cross_origin_write_blocked(self):
        self.assertEqual(self.client.put('/api/settings',json={},headers={'Origin':'https://evil.com'}).status_code,403)
    def test_remote_access_requires_token(self):
        self.assertEqual(self.client.get('/api/settings',headers={'Host':'evil.com'}).status_code,403)
    def test_media_traversal(self):self.assertEqual(self.client.get('/media/not-a-job/frames/secret.jpg').status_code,404)
    def test_creation_requires_real_config(self):
        put_value('settings',__import__('app.core',fromlist=['DEFAULTS']).DEFAULTS)
        self.assertEqual(self.client.post('/api/jobs',json={'text':BV}).status_code,400)
    def test_export_contains_local_images_and_chapters(self):
        jid='a'*32;folder=DATA/'jobs'/jid/'frames';folder.mkdir(parents=True,exist_ok=True)
        (folder/'0000000000.jpg').write_bytes(b'testimage')
        save_job({'id':jid,'status':'done','title':'测试','source':normalize_link(BV),'template':templates()[0],'markdown':f'# 课程\n\n## 第一章\n![画面](/media/{jid}/frames/0000000000.jpg)','frames':[{'file':'0000000000.jpg','url':f'/media/{jid}/frames/0000000000.jpg'}],'transcript':{'segments':[{'start':0,'end':1,'text':'转写'}]},'visual':[]})
        r=self.client.get(f'/api/jobs/{jid}/export');self.assertEqual(r.status_code,200)
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            self.assertIn('images/0000000000.jpg',z.namelist());self.assertIn('images/',z.read('笔记.md').decode());self.assertIn('../images/',z.read('章节/02.md').decode())
    def test_template_validations(self):
        self.assertEqual(self.client.put('/api/templates',json=[]).status_code,400)
        t=templates()[0];self.assertEqual(self.client.put('/api/templates',json=[t,t]).status_code,400)

class PipelineTests(unittest.TestCase):
    def test_srt_subtitles(self):
        meta={'subtitles':{'zh-CN':[{'ext':'srt','data':'1\n00:00:01,000 --> 00:00:03,000\n这是一段足够长的课程字幕用于测试，关键概念是梯度下降。\n\n'}]}}
        t=get_subtitles(meta);self.assertIsNotNone(t);self.assertEqual(t['segments'][0]['start'],1)
    def test_real_ffmpeg_and_mock_model_pipeline(self):
        import subprocess
        jid='b'*32;folder=DATA/'jobs'/jid;folder.mkdir(parents=True)
        video=folder/'source.mp4'
        subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=size=640x360:rate=5','-t','3','-pix_fmt','yuv420p',str(video)],check=True)
        dump(folder/'metadata.json',{'video':str(video),'title':'测试课程','duration':3})
        dump(folder/'transcript.json',{'source':'测试字幕','precision':'segment','segments':[{'start':0,'end':3,'text':'测试课程的原始字幕'}]})
        save_job({'id':jid,'source':normalize_link(BV),'template':templates()[0],'instructions':'','status':'queued','cancel_requested':False})
        with patch('app.pipeline.chat',side_effect=['[00:00:00] 测试画面说明','# 测试课程\n\n## 第一章\n测试内容\n\n## 待核对事项\n测试模型输出，不是真实课程。']) as model:
            process(jid)
        job=get_job(jid);self.assertEqual(job['status'],'done',job.get('error'));self.assertTrue(job['frames']);self.assertEqual(model.call_count,2)
        with patch('app.pipeline.chat',return_value='# 换模板后笔记') as model:
            process(jid)
        self.assertEqual(model.call_count,1,'重试必须复用音画分析缓存')
    def test_failure_is_visible(self):
        jid='c'*32;save_job({'id':jid,'status':'queued','cancel_requested':False})
        with patch('app.pipeline.download',side_effect=ValueError('B站不可用')):process(jid)
        self.assertEqual(get_job(jid)['status'],'error');self.assertEqual(get_job(jid)['error'],'解析 B站视频：B站不可用')

if __name__=='__main__':unittest.main()
