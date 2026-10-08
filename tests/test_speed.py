import json,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from PIL import Image
from auto_guide import Pipeline,save,same_screen

class SpeedTests(unittest.TestCase):
    def pipeline(self,out,parallel=3):
        p=Pipeline.__new__(Pipeline);p.args=SimpleNamespace(parallel=parallel,api_parallel=2,base='http://test',model='test',no_screen_reuse=False)
        p.init_transport(p.args);p.out=Path(out);(p.out/'traces').mkdir(exist_ok=True)
        return p

    def test_small_local_text_change_prevents_reuse(self):
        image=Image.new('RGB',(1600,900),'white')
        self.assertTrue(same_screen(image,image.copy()))
        other=image.copy()
        for x in range(100,108):other.putpixel((x,100),(0,0,0))
        self.assertFalse(same_screen(image,other))
        self.assertFalse(same_screen(image,image.resize((800,450))))

    def test_atomic_save_concurrent_writers(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'shared.json'
            with ThreadPoolExecutor(8) as pool:list(pool.map(lambda n:save(path,{'n':n,'data':[n]*200}),range(30)))
            result=json.loads(path.read_text());self.assertEqual(result['data'],[result['n']]*200)
            self.assertEqual(list(Path(root).glob('*.tmp')),[])

    def test_parallel_workflows_order_and_full_stages(self):
        with tempfile.TemporaryDirectory() as root:
            p=self.pipeline(root);barrier=threading.Barrier(3);events=[];guard=threading.Lock()
            p.screen_corpus=lambda:''
            def author(section,n):
                barrier.wait(timeout=5)
                with guard:events.append(('author',n))
                return {'number':n,'title':section['title']}
            def audit(step):
                with guard:events.append(('audit',step['number']))
                return [{'point':'missing'}]
            def finalize(step,n):
                with guard:events.append(('finalize',n))
                self.assertEqual(step['missing_points'],['missing']);step['verification']={};return step
            p.author_section=author;p.audit_section=audit;p.finalize_section=finalize
            doc=p.process_sections({'sections':[{'title':str(n)} for n in range(3)]},{'steps':[]})
            self.assertEqual([s['number'] for s in doc['steps']],[1,2,3])
            for n in range(1,4):self.assertEqual([e for e,k in events if k==n],['author','audit','finalize'])
            self.assertEqual(json.loads((Path(root)/'document.partial.json').read_text())['processing']['completed_sections'],[1,2,3])

    def test_no_candidates_skips_asr_even_with_glossary(self):
        with tempfile.TemporaryDirectory() as root:
            p=self.pipeline(root);p.phonetic_candidates=lambda:[]
            p.run_asr=lambda *a:self.fail('ASR must not run')
            self.assertFalse(p.second_pass([{'screen':'known','p_same_term':1}]))
            self.assertEqual(json.loads((p.out/'asr_second_pass.json').read_text())['reason'],'no_phonetic_candidates')

    def test_request_prefix_and_same_trace_deduplication(self):
        with tempfile.TemporaryDirectory() as root:
            p=self.pipeline(root);calls=[]
            def post(payload):
                calls.append(payload)
                return {'choices':[{'message':{'content':'{"ok":true}'},'finish_reason':'stop'}]}
            p.post=post
            prompt='TASK\n'+p.RULES+'\n'+p.SCHEMA+'\nSOURCE'
            with ThreadPoolExecutor(4) as pool:results=list(pool.map(lambda _:p.request('same',prompt),range(4)))
            self.assertEqual(len(calls),1);self.assertEqual(len(results),4)
            content=calls[0]['messages'][0]['content'];self.assertTrue(content.startswith(p.RULES+'\nSCHEMA:\n'+p.SCHEMA))
            self.assertEqual(content.count(p.RULES),1);self.assertIn('TASK',content);self.assertIn('SOURCE',content)

    def test_reused_observation_keeps_frame_id_and_is_independent(self):
        with tempfile.TemporaryDirectory() as root:
            p=self.pipeline(root);p.frames=[]
            for n in range(3):
                path=Path(root)/f'{n}.png';im=Image.new('RGB',(128,96),'white')
                if n==2:
                    for x in range(8):im.putpixel((x,20),(0,0,0))
                im.save(path);p.frames.append({'id':f'k{n}','time':n*20,'path':path.name,'periodic':n>0})
            def request(name,content,*args):
                ids=[f['id'] for f in p.frames if any(i.get('type')=='text' and i['text'].startswith('Ảnh '+f['id']+' ') for i in content)]
                return {'observations':[{'frame_id':i,'visible_text':['text'],'technical_terms':[],'visible_errors':[],'description':'view'} for i in ids]}
            p.request=request;p.read_screens()
            self.assertEqual(p.screen['k1']['frame_id'],'k1');self.assertEqual(p.screen['k1']['reused_from'],'k0')
            self.assertNotIn('reused_from',p.screen['k2']);p.screen['k1']['visible_text'].append('new')
            self.assertEqual(p.screen['k0']['visible_text'],['text'])

    def test_unreadable_representative_does_not_suppress_later_read(self):
        with tempfile.TemporaryDirectory() as root:
            p=self.pipeline(root);Image.new('RGB',(64,64),'white').save(p.out/'frame.png')
            p.frames=[{'id':f'k{n}','path':'frame.png','time':20*n,'periodic':bool(n)} for n in range(2)]
            calls=[]
            def request(name,content,*args):
                calls.append(name)
                if name=='screen2_k0':return {'observations':[]}
                return {'observations':[{'frame_id':'k1','visible_text':['readable'],'technical_terms':[],'visible_errors':[]}]}
            p.request=request;p.read_single=lambda *a:{'unreadable':True,'visible_text':[]}
            p.read_screens()
            self.assertIn('screen2_k1',calls);self.assertEqual(p.screen['k1']['visible_text'],['readable'])
            self.assertEqual(json.loads((p.out/'screen_reuse.json').read_text())['reused'],{})

    def test_failure_checkpoint_only_has_finished_sections(self):
        with tempfile.TemporaryDirectory() as root:
            p=self.pipeline(root,parallel=1);p.screen_corpus=lambda:''
            p.author_section=lambda s,n:dict(number=n,title=s['title'])
            p.audit_section=lambda s:[]
            def finalize(step,n):
                if n==2:raise ValueError('broken')
                step['verification']={};return step
            p.finalize_section=finalize
            with self.assertRaisesRegex(RuntimeError,'Section 2 failed'):
                p.process_sections({'sections':[{'title':str(n)} for n in range(3)]},{'steps':[]})
            doc=json.loads((p.out/'document.partial.json').read_text())
            self.assertEqual(doc['processing']['failed_sections'],[2]);self.assertTrue(all('verification' in s for s in doc['steps']))

class ConcurrencyLimits(unittest.TestCase):
    pipeline=SpeedTests.pipeline
    def test_api_global_limit(self):
        with tempfile.TemporaryDirectory() as root:
            p=self.pipeline(root);p.headers={};active=0;maximum=0;guard=threading.Lock();release=threading.Event();entered=threading.Event()
            class Response:
                def __enter__(self):return self
                def __exit__(self,*args):
                    nonlocal active
                    with guard:active-=1
                def read(self,*args):return b'{"usage":{"prompt_tokens":4,"completion_tokens":2}}'
            def open_url(*args,**kwargs):
                nonlocal active,maximum
                with guard:
                    active+=1;maximum=max(maximum,active)
                    if active==2:entered.set()
                if not release.wait(5):raise TimeoutError('test release')
                return Response()
            with patch('auto_guide.urllib.request.urlopen',open_url):
                with ThreadPoolExecutor(6) as pool:
                    futures=[pool.submit(p.post,{}) for _ in range(6)]
                    try:self.assertTrue(entered.wait(5))
                    finally:release.set()
                    for f in futures:f.result()
            self.assertEqual(maximum,2);self.assertEqual(p.performance['api']['requests'],6)
            self.assertEqual(p.performance['api']['prompt_tokens'],24)

    def test_classifier_preserves_shared_evidence_prefix(self):
        with tempfile.TemporaryDirectory() as root:
            p=self.pipeline(root);calls=[]
            def post(payload):
                calls.append(payload)
                return {'choices':[{'logprobs':{'content':[{'top_logprobs':[{'token':'A','logprob':0}]}]}}]}
            p.post=post;options={'A':'supported','B':'unsupported'}
            p.choose('one','shared evidence','question one',options)
            p.choose('two','shared evidence','question two',options)
            one=calls[0]['messages'][1]['content'];two=calls[1]['messages'][1]['content']
            self.assertEqual(one.split('CÂU HỎI:')[0],two.split('CÂU HỎI:')[0])
            self.assertLess(one.index('A. supported'),one.index('shared evidence'))
            self.assertLess(one.index('shared evidence'),one.index('question one'))

    def test_asr_and_screen_preparation_overlap(self):
        with tempfile.TemporaryDirectory() as root:
            p=self.pipeline(root);barrier=threading.Barrier(2);events=[]
            p.transcribe=lambda:barrier.wait(5)
            p.keyframes=lambda:barrier.wait(5)
            p.read_screens=lambda:events.append('screen')
            p.recheck_rare_text=lambda:events.append('recheck')
            def stop():raise ValueError('prepared')
            p.invalidate_evidence_caches=stop
            with self.assertRaisesRegex(ValueError,'prepared'):p.run_pipeline()
            self.assertEqual(events,['screen','recheck'])
            self.assertIn('asr_first_pass',p.performance['stages'])

    def test_revision_and_scrub_rounds_are_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            p=self.pipeline(root);p.args.verify_rounds=2
            fields=['title','explanation','preconditions','why','actions','examples','expected_result','diagnostics','uncertain_terms','review_note']
            draft={k:[] for k in fields};step=dict(draft);calls=[]
            p.deepen=lambda *a:(draft,'sources')
            p.verify=lambda s,n,r:(calls.append(r) or [],[{'token':'bad'}],None)
            p.revise=lambda *a:draft
            p.scrub=lambda *a:None
            p.finalize_section(step,1)
            self.assertEqual(calls,[1,2,3,'scrub1','scrub2','scrub3'])

if __name__=='__main__':unittest.main()
