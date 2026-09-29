import io,json,unittest,zipfile
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.core import templates,save_job,get_job,update_job,DATA,normalize_link
from app.main import app
from app.study import validate_quiz,generate_quiz
from app.pipeline import generate_note
RAW={'questions':[{'question':'训练误差下降是否代表模型更好？','origin':'explicit','answer':'不一定，还需要检查验证集表现。','explanation':'训练集表现不能代表对新数据的泛化能力。','timestamp':10,'evidence':'训练误差降低，泛化会更好吗？','image':None},{'question':'怎样检查模型是否过拟合？','origin':'generated','answer':'比较训练集和验证集表现。','explanation':'','timestamp':20,'evidence':'课程比较了两条误差曲线。','image':None}]}
class StudyTests(unittest.TestCase):
 def test_validate_structure_and_provenance(self):
  q=validate_quiz(json.dumps(RAW),30,[])
  self.assertEqual(q['questions'][0]['origin'],'explicit');self.assertEqual(q['questions'][1]['origin'],'generated')
  self.assertEqual(q['questions'][0]['id'],'q1');self.assertTrue(q['version'])
 def test_reject_out_of_range_and_missing_evidence(self):
  with self.assertRaises(ValueError):validate_quiz(json.dumps(RAW),5,[])
  with self.assertRaises(ValueError):validate_quiz(json.dumps({'questions':[dict(RAW['questions'][0],evidence='')]}),30,[])
 def test_disallow_arbitrary_image(self):
  q=validate_quiz(json.dumps({'questions':[dict(RAW['questions'][0],image='https://evil.test/a.png')]}),30,[])
  self.assertIsNone(q['questions'][0]['image'])
 def test_invalid_generation_retries_once(self):
  with patch('app.study.chat',side_effect=['not json',json.dumps(RAW)]) as model:
   quiz=generate_quiz({},'课程材料：训练误差降低，泛化会更好吗？','测试',30,[],'模板','')
  self.assertEqual(len(quiz['questions']),2);self.assertEqual(model.call_count,2)
 def test_persist_answer_and_version_conflict(self):
  jid='e'*32;quiz=validate_quiz(json.dumps(RAW),30,[]);save_job({'id':jid,'status':'done','quiz':quiz})
  c=TestClient(app);r=c.put(f'/api/jobs/{jid}/study/q1',json={'version':quiz['version'],'answer':'我的回答','revealed':True,'mastery':'review'})
  self.assertEqual(r.status_code,200);self.assertEqual(get_job(jid)['quiz']['responses']['q1']['answer'],'我的回答')
  self.assertEqual(c.put(f'/api/jobs/{jid}/study/q1',json={'version':'old'}).status_code,409)
  self.assertEqual(c.put(f'/api/jobs/{jid}/study/unknown',json={'version':quiz['version']}).status_code,404)
 def test_note_finishes_before_optional_study_and_export_separates_answers(self):
  jid='f'*32;folder=DATA/'jobs'/jid;folder.mkdir(parents=True,exist_ok=True)
  source=normalize_link('BV1xx411c7mD');template=templates()[0]
  save_job({'id':jid,'status':'running','source':source,'template':template,'title':'测试课程','instructions':'','cancel_requested':False})
  with patch('app.pipeline.chat',return_value='## 训练误差与泛化\n训练误差降低不一定代表泛化更好。'):
   generate_note(jid,folder,{'title':'测试课程','duration':30},{'source':'字幕','segments':[{'start':0,'end':30,'text':'训练误差降低，泛化会更好吗？'}]},[],[],{'text':{},'glossary':''})
  job=get_job(jid);self.assertEqual(job['status'],'done');self.assertIsNone(job.get('quiz'))
  with patch('app.main.settings',return_value={'text':{'base_url':'https://example.test/v1','model':'test'}}),patch('app.main.POOL.submit') as submit:
   response=TestClient(app).post(f'/api/jobs/{jid}/study/generate')
  self.assertEqual(response.status_code,200);self.assertEqual(get_job(jid)['quiz_status'],'running');submit.assert_called_once()
  update_job(jid,quiz=validate_quiz(json.dumps(RAW),30,[]),quiz_status='done')
  r=TestClient(app).get(f'/api/jobs/{jid}/export');self.assertEqual(r.status_code,200)
  with zipfile.ZipFile(io.BytesIO(r.content)) as z:
   self.assertIn('自测问题.md',z.namelist());self.assertIn('参考答案.md',z.namelist())
   self.assertNotIn('不一定，还需要',z.read('自测问题.md').decode());self.assertIn('不一定，还需要',z.read('参考答案.md').decode())
 def test_only_note_templates_are_allowed(self):
  c=TestClient(app);r=c.put('/api/templates',json=templates());self.assertEqual(r.status_code,200)
  self.assertTrue(all(x['mode']=='note' for x in r.json()))
  archived={'id':'old-quiz','name':'旧自测','tag':'先答题','prompt':'根据材料出题','mode':'selftest'}
  self.assertEqual(c.put('/api/templates',json=[archived]).status_code,400)
if __name__=='__main__':unittest.main()
