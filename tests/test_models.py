import os, tempfile, unittest, json
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('KEJING_DATA',tempfile.mkdtemp(prefix='kejing-model-tests-'))
import httpx
from app.core import chat, DEFAULTS, DATA, normalize_link, save_job, settings
from app.pipeline import transcribe
class ModelAdapterTests(unittest.TestCase):
    def test_chat_posts_vision_content(self):
        requests=[]
        def handler(req):
            requests.append(req)
            return httpx.Response(200,json={'choices':[{'message':{'content':'画面分析'},'finish_reason':'stop'}]})
        original=httpx.Client
        with patch('app.core.httpx.Client',side_effect=lambda **kw:original(transport=httpx.MockTransport(handler),**kw)):
            result=chat({'base_url':'https://provider.test/v1','model':'vision-model','api_key':'secret'},[{'role':'user','content':[{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,test'}}]}])
        self.assertEqual(result,'画面分析');self.assertEqual(str(requests[0].url),'https://provider.test/v1/chat/completions');self.assertEqual(requests[0].headers['Authorization'],'Bearer secret')
        self.assertEqual(json.loads(requests[0].content)['messages'][0]['content'][0]['type'],'image_url')
    def test_truncated_model_not_silently_saved(self):
        original=httpx.Client
        with patch('app.core.httpx.Client',side_effect=lambda **kw:original(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'choices':[{'message':{'content':'partial'},'finish_reason':'length'}]})),**kw)):
            with self.assertRaisesRegex(ValueError,'长度上限'):chat({'base_url':'https://provider.test/v1','model':'x'},[])
    def test_asr_fallback_and_timestamp_offset(self):
        jid='d'*32;folder=DATA/'jobs'/jid;audio=folder/'audio';audio.mkdir(parents=True,exist_ok=True)
        for n in range(2):(audio/f'{n:04d}.mp3').write_bytes(b'audio-test')
        save_job({'id':jid,'status':'running','cancel_requested':False})
        requests=[]
        def handler(req):
            requests.append(req)
            if b'verbose_json' in req.content:return httpx.Response(400,json={'error':'unsupported format'})
            return httpx.Response(200,json={'text':'这是测试转写文本'})
        cfg=settings();cfg['prefer_subtitles']=False;cfg['asr']={'base_url':'https://provider.test/v1','model':'asr','api_key':'test-secret'}
        original=httpx.Client
        with patch('app.pipeline.run_cmd'),patch('app.pipeline.httpx.Client',side_effect=lambda **kw:original(transport=httpx.MockTransport(handler),**kw)):
            transcript=transcribe(jid,folder,{'video':'unused.mp4','duration':700},cfg)
        self.assertEqual(len(requests),4);self.assertEqual(transcript['precision'],'chunk');self.assertEqual(transcript['segments'][1]['start'],480);self.assertEqual(transcript['segments'][1]['end'],700)
        self.assertIn('multipart/form-data',requests[0].headers['Content-Type'])
        self.assertNotIn('Cookie',requests[0].headers)
if __name__=='__main__':unittest.main()
