import copy, io, json, unittest, uuid, zipfile
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import qa
from app.core import save_job, get_job, settings, put_value
from app.main import app

class QATests(unittest.TestCase):
 def setUp(self):
  self.jid=uuid.uuid4().hex
  self.job={'id':self.jid,'status':'done','title':'学习率课程','markdown':'# 学习率\n学习率决定每次更新参数的步长。','source':{'bvid':'BV1xx411c7mD','part':1,'url':'https://www.bilibili.com/video/BV1xx411c7mD?p=1'},'transcript':{'segments':[{'start':0,'end':20,'text':'学习率决定每次更新参数的步长。'},{'start':20,'end':40,'text':'过大的学习率可能使训练不稳定。'}]},'visual':[]}
  save_job(self.job);cfg=settings();cfg['text']={'model':'test-model','base_url':'https://example.test/v1','api_key':'secret-not-for-browser'};put_value('settings',cfg)
  self.client=TestClient(app)
 def ask(self,question='为什么学习率过大会不稳定？',selection='',scope='course'):
  mid=uuid.uuid4().hex
  with patch.object(qa.POOL,'submit') as queued:
   r=self.client.post(f'/api/jobs/{self.jid}/qa',json={'question':question,'selection':selection,'scope':scope,'request_id':mid})
  self.assertEqual(r.status_code,200,r.text)
  return mid,queued.call_args.args
 def long(self):
  self.job['transcript']['segments']=[{'start':i*10,'end':i*10+10,'text':('学习率影响梯度下降收敛。' if i==300 else '这段讲述训练数据清洗与数据集划分。')*12} for i in range(400)]
  save_job(self.job)
 def execute(self,args,result='补充解释：可以把学习率理解为迈出的步长。[S1]'):
  with patch('app.qa.chat',return_value=result) as model:args[0](*args[1:])
  return model
 def test_generation_and_reading_do_not_build_or_call_models(self):
  with patch('app.qa.chat') as model:
   r=self.client.get(f'/api/jobs/{self.jid}/qa').json()
  self.assertEqual(r['index_status'],'none');self.assertNotIn('index',r);model.assert_not_called()
 def test_short_course_direct_and_citations(self):
  _,args=self.ask();model=self.execute(args);state=qa.public(self.jid)
  self.assertEqual(state['index_status'],'none');self.assertEqual(state['messages'][-1]['status'],'done')
  self.assertEqual(state['messages'][-1]['route'],'完整课程材料');self.assertIn('t=0',state['messages'][-1]['sources'][0]['url'])
  self.assertIn('过大的学习率',model.call_args.args[1][1]['content']);self.assertNotIn('secret-not',json.dumps(state))
 def test_long_auto_build_reuse_and_semantic_material_update(self):
  self.long();_,args=self.ask();self.execute(args);first=qa.read(self.jid)['index'];self.assertIsNotNone(first)
  self.assertTrue(any('学习率影响' in s['excerpt'] for s in qa.public(self.jid)['messages'][-1]['sources']))
  self.job['markdown']='更新后的模板笔记';save_job(self.job)
  self.assertEqual(qa.public(self.jid)['index_status'],'ready')
  _,args=self.ask('再举个例子')
  with patch('app.qa.make_index',side_effect=AssertionError('should reuse')):self.execute(args)
  self.assertEqual(qa.read(self.jid)['index']['fingerprint'],first['fingerprint'])
  self.job['transcript']['segments'][0]['text']='材料改变';save_job(self.job)
  self.assertEqual(qa.public(self.jid)['index_status'],'none')
 def test_selection_and_general_do_not_build_long_course(self):
  self.long();_,args=self.ask(selection='学习率影响梯度下降收敛。');self.execute(args)
  self.assertIsNone(qa.read(self.jid)['index'])
  _,args=self.ask(scope='general');model=self.execute(args)
  self.assertIsNone(qa.read(self.jid)['index']);self.assertEqual(qa.public(self.jid)['messages'][-1]['sources'],[])
  self.assertIn('通用解释',model.call_args.args[1][1]['content'])
 def test_off_ignores_existing_index_and_limits_context(self):
  self.long();qa.build(self.jid);qa.set_mode(self.jid,'off');_,args=self.ask();model=self.execute(args)
  self.assertIn('笔记前 12000 字',qa.public(self.jid)['messages'][-1]['route'])
  self.assertNotIn('学习率影响梯度下降收敛',model.call_args.args[1][1]['content'])
 def test_prepare_runs_locally_without_model(self):
  self.long()
  with patch.object(qa.POOL,'submit') as queued,patch('app.qa.chat') as model:
   r=self.client.put(f'/api/jobs/{self.jid}/qa/retrieval',json={'mode':'prepare'})
   self.assertEqual(r.json()['index_status'],'building');qa.build(self.jid)
  model.assert_not_called();self.assertEqual(qa.public(self.jid)['index_status'],'ready')
 def test_duplicate_and_busy_guard_and_restart(self):
  mid,args=self.ask()
  with patch.object(qa.POOL,'submit') as queued:
   duplicate=self.client.post(f'/api/jobs/{self.jid}/qa',json={'question':'same','request_id':mid})
   self.assertEqual(duplicate.status_code,200);queued.assert_not_called()
   self.assertEqual(self.client.post(f'/api/jobs/{self.jid}/qa',json={'question':'second','request_id':uuid.uuid4().hex}).status_code,400)
  self.assertEqual(self.client.delete(f'/api/jobs/{self.jid}/qa').status_code,400)
  qa.recover();self.assertEqual(qa.public(self.jid)['messages'][-1]['status'],'error')
 def test_failure_redacted_and_clear_preserves_index(self):
  qa.build(self.jid);_,args=self.ask()
  with patch('app.qa.chat',side_effect=ValueError('secret-not-for-browser')):args[0](*args[1:])
  self.assertNotIn('secret-not-for-browser',json.dumps(qa.public(self.jid)))
  qa.clear(self.jid);self.assertEqual(qa.public(self.jid)['messages'],[]);self.assertEqual(qa.public(self.jid)['index_status'],'ready')
 def test_history_is_bounded_and_course_isolation(self):
  _,args=self.ask();self.execute(args)
  _,args=self.ask('能换一个例子吗？');model=self.execute(args)
  self.assertTrue(any('迈出的步长' in m['content'] for m in model.call_args.args[1]))
  other=copy.deepcopy(self.job);other['id']=uuid.uuid4().hex;save_job(other)
  self.assertEqual(qa.public(other['id'])['messages'],[])
 def test_chunks_retain_all_text_and_timestamps_not_global_start(self):
  self.long();docs=qa.chunks(self.job)
  self.assertGreater(docs[-1]['start'],3000);self.assertTrue(all(len(d['text'])<=1360 for d in docs))
  self.assertTrue(any('学习率影响' in d['text'] for d in docs))
 def test_invalid_scope_mode_and_incomplete_job(self):
  self.assertEqual(self.client.put(f'/api/jobs/{self.jid}/qa/retrieval',json={'mode':'bad'}).status_code,422)
  self.assertEqual(self.client.post(f'/api/jobs/{self.jid}/qa',json={'question':'q','scope':'bad','request_id':'12345678'}).status_code,422)
  self.job['status']='running';save_job(self.job)
  self.assertEqual(self.client.post(f'/api/jobs/{self.jid}/qa',json={'question':'q','request_id':'12345678'}).status_code,400)

 def test_export_contains_conversation_and_video_sources(self):
  self.job['template']={'id':'lecture','name':'课程讲义'};save_job(self.job)
  _,args=self.ask();self.execute(args)
  r=self.client.get(f'/api/jobs/{self.jid}/export');self.assertEqual(r.status_code,200)
  with zipfile.ZipFile(io.BytesIO(r.content)) as z:
   text=z.read('课程答疑.md').decode()
   self.assertIn('迈出的步长',text);self.assertIn('&t=0',text);self.assertIn('test-model',text)
   self.assertIn('课程答疑.json',z.namelist())
