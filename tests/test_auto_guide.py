import unittest
from auto_guide import fold,term_violations,phonetic_candidates

class PureFunctions(unittest.TestCase):
    def test_fold_accents_and_letter_confusions(self):
        self.assertEqual(fold('ĐẶT'),fold('tat'))
        self.assertEqual(fold('.PAD'),fold('bat'))
        self.assertEqual(fold('ph 12!'),'f12')
        self.assertEqual(fold(''), '')

    def test_identifier_boundaries_and_absent_screen(self):
        self.assertEqual(term_violations('Mở .pad và J1',[],'.pad j1'),[])
        flags=term_violations('Mở .bat và J2',[],'.pad j1')
        self.assertEqual({f['token'] for f in flags},{'.bat','J2'})
        self.assertEqual(term_violations('J1',[],'j11'),[dict(token='J1',claim="'J1' không xuất hiện trên màn hình ở bất kỳ thời điểm nào của video, chỉ có trong lời nói (có thể ASR nghe sai)",label='insufficient',p_supported=0.0)])
        self.assertEqual(term_violations('Mở .bat',[],''),[])

    def test_extension_and_message_must_match_whole_token(self):
        self.assertTrue(term_violations('Mở .pad',[],'.padstack'))
        self.assertTrue(term_violations('Lỗi "Place Cannot Object"',[],'cannot place object'))
        self.assertEqual(term_violations('Mở .pad',[],'example.pad'),[])

    def test_sound_matching_multiword_and_numeric_identity(self):
        targets=[({'text':'Foo9','frame':'k2'},fold('Foo9'))]
        result=phonetic_candidates([dict(id='s1',text='foo 9')],targets)
        self.assertEqual(result[0]['asr'],'foo 9')
        self.assertEqual(phonetic_candidates([dict(id='s1',text='foo 8')],targets),[])

    def test_verified_mapping_and_quoted_message(self):
        t=dict(asr='sai tên',screen='correct',confidence='high',p_same_term=.9,evidence_frame_ids=['k1'])
        self.assertEqual(term_violations('sai tên',[t],'correct')[0]['label'],'contradicted')
        self.assertEqual(term_violations('sai tên khác',[dict(t,p_same_term=.2)],'correct'),[])
        self.assertTrue(term_violations('Lỗi "Cannot Load Object"',[],'cannot place object'))
        self.assertEqual(term_violations('Lỗi "Cannot Place Object"',[],'cannot place object'),[])

    def test_sound_matching_short_terms_and_deduplication(self):
        targets=[({'text':'.pad','frame':'k1'},fold('.pad'))]
        rows=[dict(id='s1',text='bat bat'),dict(id='s2',text='BAT')]
        result=phonetic_candidates(rows,targets)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['screen'],'.pad')
        self.assertEqual(result[0]['segment_ids'],['s1','s2'])
        self.assertEqual(result[0]['sound_similarity'],1)
        self.assertEqual(phonetic_candidates([dict(id='s3',text='badly')],targets),[])
        self.assertEqual(phonetic_candidates(rows,[]),[])

if __name__=='__main__':unittest.main()
