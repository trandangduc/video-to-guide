import copy,tempfile,unittest,zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from lxml import etree as ET
from openpyxl import Workbook
from excel_template_layout import S,D,X,A,NS,template_shapes,inject_textboxes,build_native_sheet
from excel_guide import object_schema,array_schema,string_schema,copy_cell_style

class NativeLayoutTests(unittest.TestCase):
    def test_floating_text_style_is_preserved_and_only_anchor_and_words_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);template=root/'template.xlsx';dest=root/'result.xlsx'
            sheet=f'<worksheet xmlns="{S}" xmlns:r="{D}"><drawing r:id="rId1"/></worksheet>'
            rels=f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{D}/drawing" Target="../drawings/drawing3.xml"/></Relationships>'
            drawing=f'''<x:wsDr xmlns:x="{X}" xmlns:a="{A}"><x:twoCellAnchor><x:from><x:col>1</x:col><x:colOff>99</x:colOff><x:row>14</x:row><x:rowOff>12</x:rowOff></x:from><x:to><x:col>8</x:col><x:colOff>0</x:colOff><x:row>18</x:row><x:rowOff>0</x:rowOff></x:to><x:sp><x:nvSpPr><x:cNvPr id="4" name="Instruction"/></x:nvSpPr><x:spPr/><x:txBody><a:bodyPr wrap="square"/><a:p><a:pPr algn="ctr"/><a:r><a:rPr sz="1200" b="1"/><a:t>Old instruction</a:t></a:r></a:p></x:txBody></x:sp><x:clientData/></x:twoCellAnchor></x:wsDr>'''
            parts={'xl/worksheets/sheet3.xml':sheet.encode(),'xl/worksheets/_rels/sheet3.xml.rels':rels.encode(),'xl/drawings/drawing3.xml':drawing.encode(),'untouched.bin':b'original content'}
            for path in (template,dest):
                with zipfile.ZipFile(path,'w') as z:
                    for n,data in parts.items():z.writestr(n,data)
            shapes,catalog=template_shapes(template,2)
            self.assertEqual(catalog[0]['text'],'Old instruction')
            inject_textboxes(template,dest,{2:[{'shape_id':'SHAPE_000','text':'Tuốt dây 0.38in\nĐầu dây B','col':13,'end_col':21,'row':30,'end_row':34}]})
            with zipfile.ZipFile(dest) as z:
                r=ET.fromstring(z.read('xl/drawings/drawing3.xml'));anchor=r[-1]
                self.assertEqual(z.read('untouched.bin'),b'original content')
                self.assertEqual(anchor.xpath('.//a:t/text()',namespaces=NS),['Tuốt dây 0.38in','Đầu dây B'])
                self.assertEqual(anchor.find('x:from/x:row',NS).text,'29')
                self.assertEqual(anchor.find('x:from/x:col',NS).text,'13')
                self.assertEqual(anchor.find('.//a:rPr',NS).get('sz'),'1200')
                self.assertEqual(anchor.find('.//a:pPr',NS).get('algn'),'ctr')
                self.assertEqual([ET.QName(c).localname for c in anchor],['from','to','sp','clientData'])

    def test_unequal_caption_lengths_keep_both_lanes_on_shared_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            wb=Workbook();source=wb.active;target=wb.create_sheet('generated')
            source['B7']='ITEM';source['K8']='Phải';source['B9']='old part';source['R65']='sample'
            plan={'items':[{'source_id':'s1','kind':'step','text':'Short instruction','group_text':'A','image_ids':['p1']},
                           {'source_id':'s2','kind':'step','text':'A much longer instruction '*25,'group_text':'B','image_ids':['p2']},
                           {'source_id':'s3','kind':'step','text':'Next instruction','group_text':'A','image_ids':['p3']},
                           {'source_id':'n1','kind':'note','text':'Keep original note'}]}
            catalog=[{'id':'left','text':'LEFT','col':1,'row':15,'end_col':3},{'id':'right','text':'RIGHT','col':15,'row':19,'end_col':17},{'id':'caption','text':'Sample caption','col':2,'row':27,'end_col':8}]
            layout={'tables':[{'range':'B7:K11','header_end_row':8,'position':'top','keep':True,'cells':[]}],
                    'title_shape_ids':[],'general_source_ids':[],
                    'lanes':[{'heading_shape_id':'left','caption_shape_id':'caption','source_ids':['s1','s3']},
                             {'heading_shape_id':'right','caption_shape_id':'caption','source_ids':['s2']}]}
            job=SimpleNamespace(out=Path(tmp),image_map={i:{'path':i} for i in ('p1','p2','p3')})
            images=[]
            def image_at(ws,path,col,row,*args):images.append((path,col,row))
            with patch('excel_template_layout.native_layout',return_value=(copy.deepcopy(layout),catalog)):
                places=build_native_sheet(job,source,target,plan,[],(object_schema,array_schema,string_schema,None,copy_cell_style,image_at))
            instructions={p['source_id']:p for p in places if 'source_id' in p}
            self.assertEqual(instructions['s1']['row'],instructions['s2']['row'])
            self.assertEqual(instructions['s1']['end_row'],instructions['s2']['end_row'])
            self.assertEqual(images[0][2],images[1][2])
            self.assertEqual(instructions['s2']['text'],plan['items'][1]['text'])
            self.assertGreater(instructions['s3']['row'],instructions['s1']['end_row'])
            self.assertEqual(target['B7'].value,'ITEM');self.assertIsNone(target['B9'].value)
            self.assertIsNone(target['L7'].value);self.assertIsNone(target['N7'].value)
            self.assertIn('Keep original note',[p['text'] for p in places])

if __name__=='__main__':unittest.main()
