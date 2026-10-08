import math
import unittest
from semif_score import option_scores,accepted

class SemIfTests(unittest.TestCase):
    def test_conditional_softmax_and_observed_mass(self):
        scores,mass=option_scores([{'token':'A','logprob':math.log(.3)},{'token':'B','logprob':math.log(.1)},{'token':'other','logprob':math.log(.6)}],2)
        self.assertAlmostEqual(scores['A'],.75)
        self.assertAlmostEqual(mass,.4)
        self.assertTrue(accepted(scores,mass))

    def test_absent_and_nonexact_tokens_cannot_pass(self):
        scores,mass=option_scores([{'token':' A','logprob':-.01}],3)
        self.assertEqual(mass,0)
        self.assertFalse(accepted(scores,mass))
        self.assertFalse(accepted({'A':.99,'B':.01},.0001))

    def test_group_score_does_not_override_rejection_winner(self):
        self.assertFalse(accepted({'A':.33,'B':.33,'C':.34},.9,('A','B')))
        self.assertFalse(accepted({'A':.6,'B':.4},.9))
        self.assertTrue(accepted({'A':.4,'B':.5,'C':.1},.9,('A','B')))

class ExcelMatchingTests(unittest.TestCase):
    def test_qwen38_selects_result_without_semif_gate(self):
        import tempfile
        from pathlib import Path
        from PIL import Image
        from unittest.mock import patch
        from excel_guide import ExcelJob
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);photo=root/'photo.png';Image.new('RGB',(90,60),'white').save(photo);(root/'assets').mkdir()
            job=ExcelJob.__new__(ExcelJob);job.client=None;job.sources=[];job.out=root
            job.image_map={'IMG_001':{'id':'IMG_001','path':str(photo),'order':1}}
            item={'source_id':'TXT_001','kind':'result','text':'finished assembly','image_ids':['IMG_001']}
            def ask(name,*args,**kwargs):
                if name.startswith('result_candidate_'):
                    return {'image_id':'IMG_001','stage':'whole','needs_review':False,'reason':'The assembled cable is visible.'}
                return {'image_ids':['IMG_001'],'result_description':'A cable assembly is visible.','reason':'The full assembly is shown.','needs_review':False}
            with patch.object(job,'ask',side_effect=ask),patch('excel_guide.photo_url',return_value='image'):
                job.select_results({'items':[item]},[{'path':str(photo)}])
            self.assertEqual(item['image_ids'],['IMG_001'])
            self.assertEqual(item['checks'][0]['selected_by'],'qwen38')
