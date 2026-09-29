import unittest, uuid
from unittest.mock import patch
from app.core import DATA, save_job, get_job, normalize_link
from app.pipeline import generate_note, dump

class ChapterNoteTests(unittest.TestCase):
    def test_regeneration_ignores_old_material_and_preserves_transcript(self):
        jid=uuid.uuid4().hex;folder=DATA/'jobs'/jid;folder.mkdir(parents=True)
        dump(folder/'material-0.json','OLD_SECOND_BY_SECOND_NOTES')
        template={'id':'lecture','name':'课程讲义','prompt':'保留解释和例子'}
        save_job({'id':jid,'status':'running','cancel_requested':False,'source':normalize_link('BV18ue16YErL'),'template':template,'analyze_video':False})
        transcript={'source':'B站字幕','segments':[{'start':i*3,'end':i*3+3,'text':'课程概念与例子。'*20} for i in range(140)]}
        calls=[]
        def model(cfg,messages,budget):
            calls.append(messages[-1]['content'])
            return '主题材料' if budget==5000 else '# 课程\n\n## 一个主题 [00:00:00](https://www.bilibili.com/video/BV18ue16YErL?p=1&t=0)\n连续解释。'
        with patch('app.pipeline.chat',side_effect=model):
            generate_note(jid,folder,{'title':'课程','duration':700},transcript,[],[],{'text':{},'glossary':''})
        self.assertGreater(len(calls),1)
        self.assertTrue(all('OLD_SECOND_BY_SECOND_NOTES' not in p for p in calls))
        self.assertIn('建议3–5个主要章节',calls[-1])
        self.assertIn('正文段落、列表、子标题不要逐条加时间',calls[-1])
        self.assertEqual(get_job(jid)['transcript'],transcript)
        self.assertEqual(get_job(jid)['status'],'done')
