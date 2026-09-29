import unittest, uuid, json
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from app.core import DATA, save_job, get_job, settings, templates, chat
from app.pipeline import process, dump
from app.main import app

class ModeTests(unittest.TestCase):
    def test_audio_skips_vision_and_does_not_reuse_cached_visual(self):
        jid=uuid.uuid4().hex
        folder=DATA/'jobs'/jid;folder.mkdir(parents=True)
        dump(folder/'visual.json',[{'text':'旧画面'}])
        save_job({'id':jid,'status':'queued','analyze_video':False,'cancel_requested':False})
        transcript={'source':'B站字幕','segments':[]}
        with patch('app.pipeline.shutil.which',return_value='/bin/tool'),patch('app.pipeline.download',return_value={'title':'播客','duration':10}),patch('app.pipeline.transcribe',return_value=transcript),patch('app.pipeline.extract_frames') as frames,patch('app.pipeline.analyze_frames') as vision,patch('app.pipeline.generate_note') as note:
            process(jid)
        frames.assert_not_called();vision.assert_not_called()
        self.assertEqual(note.call_args.args[4:6],([],[]))
        self.assertEqual(get_job(jid)['visual'],[])
        self.assertTrue((folder/'visual.json').exists())

    def test_audio_creation_needs_no_vision_config(self):
        cfg=settings();cfg['text']={'base_url':'https://test.invalid','model':'test'};cfg['vision']={'base_url':'','model':''};cfg['prefer_subtitles']=True
        with patch('app.main.settings',return_value=cfg),patch('app.main.jobs',return_value=[]),patch('app.main.POOL.submit'):
            response=TestClient(app).post('/api/jobs',json={'text':'BV18ue16YErL','template_id':templates()[0]['id'],'analyze_video':False})
        self.assertEqual(response.status_code,200,response.text)
        self.assertFalse(response.json()['analyze_video'])

    def test_mode_change_clears_material_not_frame_cache(self):
        jid=uuid.uuid4().hex;folder=DATA/'jobs'/jid;folder.mkdir(parents=True)
        dump(folder/'material-0.json','旧画面');dump(folder/'visual.json',[])
        save_job({'id':jid,'status':'error','analyze_video':True})
        with patch('app.main.POOL.submit'):
            response=TestClient(app).post(f'/api/jobs/{jid}/retry',json={'analyze_video':False})
        self.assertEqual(response.status_code,200,response.text)
        self.assertFalse((folder/'material-0.json').exists());self.assertTrue((folder/'visual.json').exists())

    def test_deepseek_disables_thinking_and_retries_length_once(self):
        payloads=[]
        def handler(req):
            payloads.append(json.loads(req.content))
            return httpx.Response(200,json={'choices':[{'message':{'content':'正文'},'finish_reason':'length' if len(payloads)==1 else 'stop'}]})
        original=httpx.Client
        with patch('app.core.httpx.Client',side_effect=lambda **kw:original(transport=httpx.MockTransport(handler),**kw)):
            self.assertEqual(chat({'base_url':'https://api.deepseek.com','model':'deepseek-flash'},[],4500),'正文')
        self.assertEqual([p['max_tokens'] for p in payloads],[4500,9000])
        self.assertEqual(payloads[0]['thinking'],{'type':'disabled'})

    def test_visual_truncation_splits_batch(self):
        from app.core import OutputLimitError
        from app.pipeline import analyze_frames
        jid=uuid.uuid4().hex;folder=DATA/'jobs'/jid;folder.mkdir(parents=True)
        save_job({'id':jid,'status':'running','cancel_requested':False})
        frames=[{'time':i,'file':f'{i}.jpg'} for i in range(4)]
        sizes=[]
        def model(config,messages,budget):
            n=sum(x['type']=='image_url' for x in messages[-1]['content']);sizes.append(n)
            if n>2:raise OutputLimitError('length')
            return '画面描述'
        with patch('app.pipeline.image_data',return_value='data:image/jpeg;base64,test'),patch('app.pipeline.chat',side_effect=model):
            result=analyze_frames(jid,folder,frames,{'segments':[]},settings())
        self.assertEqual(sizes,[4,2,2]);self.assertEqual(len(result),2)

    def test_other_provider_bounded_retry_without_thinking_parameter(self):
        from app.core import OutputLimitError
        payloads=[]
        def handler(req):
            payloads.append(json.loads(req.content))
            return httpx.Response(200,json={'choices':[{'message':{'content':'partial'},'finish_reason':'length'}]})
        original=httpx.Client
        with patch('app.core.httpx.Client',side_effect=lambda **kw:original(transport=httpx.MockTransport(handler),**kw)):
            with self.assertRaises(OutputLimitError):chat({'base_url':'https://custom.invalid/v1','model':'deepseek-flash'},[],4500)
        self.assertEqual(len(payloads),2);self.assertNotIn('thinking',payloads[0])
