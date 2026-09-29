import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from app.doubao import transcribe_file, RESOURCE

class DoubaoTests(unittest.TestCase):
    def test_submit_poll_and_resume(self):
        with tempfile.TemporaryDirectory() as d:
            audio=Path(d)/'0.mp3';audio.write_bytes(b'audio')
            calls=[]
            def post(url,**kw):
                calls.append((url,kw))
                if url.endswith('/submit'):
                    return httpx.Response(200,headers={'X-Api-Status-Code':'20000000'},json={})
                return httpx.Response(200,headers={'X-Api-Status-Code':'20000000'},json={'result':{'text':'hello','utterances':[{'start_time':1500,'end_time':3200,'text':'hello'}]}})
            with patch('app.doubao.httpx.Client') as c:
                c.return_value.__enter__.return_value.post.side_effect=post
                cfg={'api_key':'test','provider':'doubao'}
                r=transcribe_file(audio,cfg)
                self.assertEqual(r['segments'][0]['start'],1.5)
                self.assertEqual(calls[0][1]['headers']['X-Api-Resource-Id'],RESOURCE)
                self.assertEqual(calls[0][1]['headers']['X-Api-Key'],'test')
                self.assertNotIn('language',calls[0][1]['json']['audio'])
                transcribe_file(audio,cfg)
                self.assertEqual(sum(u.endswith('/submit') for u,_ in calls),1)
    def test_auth_failure_redacted(self):
        with tempfile.TemporaryDirectory() as d:
            audio=Path(d)/'0.mp3';audio.write_bytes(b'audio')
            with patch('app.doubao.httpx.Client') as c:
                c.return_value.__enter__.return_value.post.return_value=httpx.Response(403,text='secret-token')
                with self.assertRaises(ValueError) as err:transcribe_file(audio,{'api_key':'secret-token'})
                self.assertNotIn('secret-token',str(err.exception))
    def test_app_token_requires_id(self):
        with self.assertRaisesRegex(ValueError,'APP ID'):
            transcribe_file(Path('unused'),{'auth_mode':'app_token','api_key':'token'})

    def test_settings_force_endpoint_and_hide_secret(self):
        import copy
        from fastapi.testclient import TestClient
        from app.main import app
        from app.core import DEFAULTS
        cfg=copy.deepcopy(DEFAULTS)
        with patch('app.main.settings',return_value=cfg),patch('app.main.put_value'):
            r=TestClient(app).put('/api/settings',json={'asr':{'provider':'doubao','api_key':'test-secret','base_url':'https://console.volcengine.com/','model':'Doubao'}})
            self.assertEqual(r.status_code,200)
            self.assertEqual(r.json()['asr']['model'],RESOURCE)
            self.assertEqual(r.json()['asr']['api_key'],'')
            self.assertTrue(r.json()['asr']['has_key'])
