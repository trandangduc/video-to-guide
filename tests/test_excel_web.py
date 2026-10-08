import json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from openpyxl import Workbook
from PIL import Image
import web_app

class ExcelWebJobs(unittest.TestCase):
    def test_launch_arguments_and_job_recovery(self):
        with tempfile.TemporaryDirectory(dir=web_app.OUTPUT) as temporary:
            root=Path(temporary);folder=root/'dataset';folder.mkdir()
            wb=Workbook()
            for index in range(4):wb.create_sheet('Page '+str(index+2))
            wb.save(folder/'template.xlsx');(folder/'description.txt').write_text('ABC123\n- Một thao tác.');(folder/'drawing.pdf').write_bytes(b'test PDF placeholder')
            Image.new('RGB',(40,50),'white').save(folder/'photo.jpg')
            process=Mock();process.pid=123456;process.poll.return_value=None
            with patch.object(web_app,'OUTPUT',root/'results'),patch.dict(web_app.JOBS,{},clear=True),patch.object(web_app,'busy',return_value=False),patch.object(web_app.subprocess,'Popen',return_value=process) as spawn:
                job_id=web_app.launch_excel({'folder':str(folder)})
                command=spawn.call_args.args[0]
                self.assertEqual(command[0],str(web_app.ROOT/'.venv/bin/python'));self.assertEqual(command[1],str(web_app.ROOT/'excel_guide.py'))
                self.assertEqual(command[command.index('--folder')+1],str(folder))
                self.assertEqual(web_app.job_status(job_id)['status'],'running')
                out=web_app.JOBS[job_id]['output'];wb.save(out/'result.xlsx')
                (out/'excel-result.json').write_text(json.dumps({'status':'completed','file':'result.xlsx','elapsed_seconds':9}))
                web_app.JOBS.clear()
                recovered=web_app.job_status(job_id)
                self.assertEqual(recovered['kind'],'excel');self.assertEqual(recovered['status'],'completed')
                self.assertEqual(recovered['elapsed_seconds'],9);self.assertIn('xlsx',recovered['files'])

if __name__=='__main__':unittest.main()
