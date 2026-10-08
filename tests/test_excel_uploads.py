import io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from openpyxl import Workbook
from PIL import Image
import pymupdf
import web_app

class ExcelUploads(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=web_app.ROOT/'output');self.addCleanup(self.temp.cleanup)
        self.patcher=patch.object(web_app,'OUTPUT',Path(self.temp.name));self.patcher.start();self.addCleanup(self.patcher.stop)
        self.token=web_app.create_excel_upload()['upload_id']

    def upload(self,role,name,data):return web_app.receive_excel_file(self.token,role,name,io.BytesIO(data),len(data))

    def test_upload_new_files_and_complete_without_existing_dataset(self):
        workbook=Workbook()
        for i in range(4):workbook.create_sheet('Page '+str(i))
        out=io.BytesIO();workbook.save(out);self.upload('template','mẫu.xlsx',out.getvalue())
        self.upload('description','mô tả.txt','Bộ mới\n- Thao tác mới\n- Kết quả'.encode())
        pdf=pymupdf.open();pdf.new_page();self.upload('pdf','nguồn.pdf',pdf.tobytes());pdf.close()
        picture=io.BytesIO();Image.new('RGB',(40,50),'red').save(picture,'JPEG')
        for name in ['hình.jpg','hình.jpg']:self.upload('image',name,picture.getvalue())
        ready=web_app.complete_excel_upload(self.token)
        self.assertEqual(ready['photos'],2);self.assertIn('Bộ mới',ready['description_text'])
        self.assertEqual(ready['images'],'images');self.assertNotIn('tests/794940',ready['folder'])
        with self.assertRaisesRegex(ValueError,'hoàn tất'):self.upload('image','extra.jpg',picture.getvalue())

    def test_invalid_files_paths_partial_uploads_and_missing_files(self):
        for name in ['../outside.txt','..\\outside.txt']:
            with self.assertRaises(ValueError):self.upload('description',name,b'description')
        with self.assertRaises(ValueError):self.upload('image','script.py',b'bad')
        with self.assertRaises(ValueError):self.upload('image','bad.jpg',b'bad image')
        with self.assertRaisesRegex(ValueError,'chưa hoàn tất'):
            web_app.receive_excel_file(self.token,'description','source.txt',io.BytesIO(b'a'),10)
        with self.assertRaisesRegex(ValueError,'Cần upload'):web_app.complete_excel_upload(self.token)
        self.assertEqual(json.loads((web_app.upload_directory(self.token)/'upload.json').read_text())['files'],[])
