"""Match description/photos and PDF illustrations into sheets 3–5 of an Excel template."""
import argparse,base64,copy,hashlib,io,json,posixpath,re,time,zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from lxml import etree as ET
import pymupdf
from PIL import Image,ImageOps,ImageDraw
from openpyxl import Workbook,load_workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker,OneCellAnchor
from openpyxl.drawing.xdr import XDRPositiveSize2D
from openpyxl.styles import Alignment,Border,Font,PatternFill,Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.pagebreak import Break
from auto_guide import Pipeline,save,digest_file
from excel_template_layout import build_native_sheet,inject_textboxes,template_shapes

S='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
R='http://schemas.openxmlformats.org/package/2006/relationships'
D='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
C='http://schemas.openxmlformats.org/package/2006/content-types'
VERSION='excel-guide-v7-native-floating-layout'
IMAGE_EXT={'.jpg','.jpeg','.png','.webp','.bmp'}

def discover(folder,template=None,description=None,pdf=None,images=None):
    folder=Path(folder).expanduser().resolve()
    if not folder.is_dir():raise ValueError('Thư mục dữ liệu không tồn tại.')
    def choose(value,extensions,label):
        if value:
            p=Path(value);p=(p if p.is_absolute() else folder/p).resolve()
            if not p.is_relative_to(folder) or not p.is_file() or p.suffix.lower() not in extensions:raise ValueError(label+' không hợp lệ.')
            return p
        found=[p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in extensions and not p.name.startswith('~$')]
        if len(found)!=1:raise ValueError('Cần chọn đúng một '+label+' (tìm được '+str(len(found))+').')
        return found[0]
    template=choose(template,{'.xlsx'},'file mẫu XLSX');description=choose(description,{'.txt'},'file mô tả TXT');pdf=choose(pdf,{'.pdf'},'file PDF')
    image_dir=(folder/images).resolve() if images else None
    if image_dir and (not image_dir.is_relative_to(folder) or not image_dir.is_dir()):raise ValueError('Thư mục ảnh không hợp lệ.')
    photos=sorted(p for p in (image_dir.rglob('*') if image_dir else folder.rglob('*')) if p.is_file() and p.suffix.lower() in IMAGE_EXT)
    if not photos:raise ValueError('Không tìm thấy ảnh trong thư mục dữ liệu.')
    return folder,template,description,pdf,photos

def source_items(text):
    blocks=[];current=[]
    for line in text.splitlines():
        line=line.strip()
        if not line:
            if current:blocks.append(' '.join(current));current=[]
        elif re.match(r'^[-•]\s+',line):
            if current:blocks.append(' '.join(current))
            current=[re.sub(r'^[-•]\s+','',line)]
        else:current.append(line)
    if current:blocks.append(' '.join(current))
    return [{'id':f'TXT_{i+1:03d}','text':v} for i,v in enumerate(blocks)]

def string_schema(limit=400):return {'type':'string','maxLength':limit}
def object_schema(properties):return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
def array_schema(items,maximum,minimum=0):return {'type':'array','items':items,'maxItems':maximum,'minItems':minimum}

def photo_url(path,size=(1200,1000)):
    with Image.open(path) as source:im=ImageOps.exif_transpose(source).convert('RGB')
    im.thumbnail(size);buffer=io.BytesIO();im.save(buffer,'JPEG',quality=92)
    return 'data:image/jpeg;base64,'+base64.b64encode(buffer.getvalue()).decode()

def xml(data):return ET.fromstring(data)
def xml_bytes(node):return ET.tostring(node,xml_declaration=True,encoding='UTF-8',standalone=True)
def resolve_part(source,target):return posixpath.normpath(posixpath.join(posixpath.dirname(source),target)) if not target.startswith('/') else target.lstrip('/')
def rel_path(part):return posixpath.join(posixpath.dirname(part),'_rels',posixpath.basename(part)+'.rels')

def template_sheets(archive):
    rels={r.get('Id'):resolve_part('xl/workbook.xml',r.get('Target')) for r in xml(archive.read('xl/_rels/workbook.xml.rels'))}
    return [(s.get('name'),rels[s.get('{'+D+'}id')]) for s in xml(archive.read('xl/workbook.xml')).find('{'+S+'}sheets')]

def transplant(template,generated,destination,preserve_header=False):
    """Preserve original workbook parts; replace only sheets 3–5 and append new style/media parts.

    Generated sheets use inline strings, leaving original shared strings and all sheet 1/2
    XML, relationships, images and drawing objects byte-for-byte unchanged.
    """
    with zipfile.ZipFile(template) as original,zipfile.ZipFile(generated) as fresh:
        parts={p:original.read(p) for p in original.namelist()};targets=template_sheets(original)
        if len(targets)<5:raise ValueError('Mẫu phải có ít nhất 5 sheet.')
        sources=template_sheets(fresh);old_styles=xml(parts['xl/styles.xml']);new_styles=xml(fresh.read('xl/styles.xml'))
        maps={}
        for group in ['fonts','fills','borders']:
            old=old_styles.find('{'+S+'}'+group);new=new_styles.find('{'+S+'}'+group)
            maps[group]={i:len(old)+i for i in range(len(new))}
            for element in new:old.append(copy.deepcopy(element))
            old.set('count',str(len(old)))
        old_nf=old_styles.find('{'+S+'}numFmts');new_nf=new_styles.find('{'+S+'}numFmts');num_map={}
        if new_nf is not None and len(new_nf):
            if old_nf is None:old_nf=ET.Element('{'+S+'}numFmts');old_styles.insert(0,old_nf)
            next_id=max([163]+[int(e.get('numFmtId')) for e in old_nf])+1
            for element in new_nf:
                item=copy.deepcopy(element);num_map[int(item.get('numFmtId'))]=next_id;item.set('numFmtId',str(next_id));old_nf.append(item);next_id+=1
            old_nf.set('count',str(len(old_nf)))
        old_xf=old_styles.find('{'+S+'}cellXfs');new_xf=new_styles.find('{'+S+'}cellXfs');style_map={}
        for i,element in enumerate(new_xf):
            item=copy.deepcopy(element)
            for attribute,group in [('fontId','fonts'),('fillId','fills'),('borderId','borders')]:item.set(attribute,str(maps[group][int(item.get(attribute,'0'))]))
            value=int(item.get('numFmtId','0'));item.set('numFmtId',str(num_map.get(value,value)));item.set('xfId','0')
            style_map[i]=len(old_xf);old_xf.append(item)
        old_xf.set('count',str(len(old_xf)));parts['xl/styles.xml']=xml_bytes(old_styles)
        mapping={sources[i][1]:targets[i+2][1] for i in range(3)}
        for name in fresh.namelist():
            if name.startswith(('xl/drawings/','xl/media/')) and '/_rels/' not in name:
                directory,base=posixpath.split(name);mapping[name]=directory+'/excel_match_'+base
        for source,target in list(mapping.items()):
            if rel_path(source) in fresh.namelist():mapping[rel_path(source)]=rel_path(target)
        for source,target in mapping.items():
            data=fresh.read(source)
            if source in [p for _,p in sources]:
                root=xml(data)
                for cell in root.findall('.//{'+S+'}c'):cell.set('s',str(style_map[int(cell.get('s','0'))]))
                data=xml_bytes(root)
            elif source.endswith('.rels'):
                root=xml(data);original_owner=source.replace('/_rels/','/').removesuffix('.rels');new_owner=target.replace('/_rels/','/').removesuffix('.rels')
                for relation in root:
                    if relation.get('TargetMode')=='External':continue
                    part=resolve_part(original_owner,relation.get('Target'));mapped=mapping.get(part)
                    if mapped is None:raise ValueError('Unexpected generated relationship: '+part)
                    relation.set('Target',posixpath.relpath(mapped,posixpath.dirname(new_owner)))
                data=xml_bytes(root)
            parts[target]=data
        if preserve_header:
            for _,target in targets[2:5]:
                source=xml(original.read(target));dest=xml(parts[target]);source_data=source.find('{'+S+'}sheetData');dest_data=dest.find('{'+S+'}sheetData')
                for row in list(dest_data):
                    if int(row.get('r'))<=4:dest_data.remove(row)
                for index,row in enumerate([r for r in source_data if int(r.get('r'))<=4]):dest_data.insert(index,copy.deepcopy(row))
                for tag in ('cols','sheetFormatPr'):
                    old=source.find('{'+S+'}'+tag);current=dest.find('{'+S+'}'+tag)
                    if current is not None:position=list(dest).index(current);dest.remove(current)
                    else:position=list(dest).index(dest_data)
                    if old is not None:dest.insert(position,copy.deepcopy(old))
                merges=dest.find('{'+S+'}mergeCells')
                if merges is None:merges=ET.Element('{'+S+'}mergeCells');dest.insert(list(dest).index(dest_data)+1,merges)
                for merge in list(merges):
                    if int(re.search(r'\d+',merge.get('ref')).group())<=4:merges.remove(merge)
                old_merges=source.find('{'+S+'}mergeCells')
                if old_merges is not None:
                    for merge in old_merges:
                        rows=[int(v) for v in re.findall(r'\d+',merge.get('ref'))]
                        if max(rows)<=4:merges.append(copy.deepcopy(merge))
                merges.set('count',str(len(merges)))
                parts[target]=xml_bytes(dest)
                old_drawing=source.find('{'+S+'}drawing');new_drawing=dest.find('{'+S+'}drawing')
                if old_drawing is None or new_drawing is None:continue
                old_rel=xml(original.read(rel_path(target)));new_rel=xml(parts[rel_path(target)])
                old_part=resolve_part(target,next(r.get('Target') for r in old_rel if r.get('Id')==old_drawing.get('{'+D+'}id')))
                new_part=resolve_part(target,next(r.get('Target') for r in new_rel if r.get('Id')==new_drawing.get('{'+D+'}id')))
                old_tree=xml(original.read(old_part));new_tree=xml(parts[new_part]);ns={'x':'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing'}
                headers=[a for a in old_tree if a.find('x:from/x:row',ns) is not None and int(a.find('x:from/x:row',ns).text)<4]
                if not headers:continue
                old_links={r.get('Id'):r for r in xml(original.read(rel_path(old_part)))}
                new_links=xml(parts[rel_path(new_part)]);link_map={}
                # Keep original header object IDs; new body object IDs need only be unique.
                for index,node in enumerate(new_tree.findall('.//x:cNvPr',ns)):node.set('id',str(10000+index))
                for anchor_index,anchor in enumerate(headers):
                    cloned=copy.deepcopy(anchor)
                    for node in cloned.iter():
                        for key,value in list(node.attrib.items()):
                            if key.startswith('{'+D+'}') and value in old_links:
                                if value not in link_map:
                                    link=copy.deepcopy(old_links[value]);ident='rIdHeader'+str(len(link_map)+1);link.set('Id',ident)
                                    if link.get('TargetMode')!='External':link.set('Target',posixpath.relpath(resolve_part(old_part,link.get('Target')),posixpath.dirname(new_part)))
                                    new_links.append(link);link_map[value]=ident
                                node.set(key,link_map[value])
                    new_tree.insert(anchor_index,cloned)
                parts[new_part]=xml_bytes(new_tree);parts[rel_path(new_part)]=xml_bytes(new_links)
        ct=xml(parts['[Content_Types].xml']);known_defaults={e.get('Extension') for e in ct if ET.QName(e).localname=='Default'};known_overrides={e.get('PartName') for e in ct if ET.QName(e).localname=='Override'}
        for element in xml(fresh.read('[Content_Types].xml')):
            item=copy.deepcopy(element)
            if ET.QName(item).localname=='Default':
                if item.get('Extension') not in known_defaults:ct.append(item);known_defaults.add(item.get('Extension'))
            else:
                part=item.get('PartName').lstrip('/')
                if part in mapping:
                    item.set('PartName','/'+mapping[part])
                    if item.get('PartName') not in known_overrides:ct.append(item);known_overrides.add(item.get('PartName'))
        parts['[Content_Types].xml']=xml_bytes(ct)
        # Print areas/titles live in workbook.xml, not worksheet XML. Keep sheet 1/2
        # names untouched and replace only local print definitions of sheets 3–5.
        workbook=xml(parts['xl/workbook.xml']);defined=workbook.find('{'+S+'}definedNames')
        if defined is None:
            defined=ET.Element('{'+S+'}definedNames');sheets_node=workbook.find('{'+S+'}sheets');workbook.insert(list(workbook).index(sheets_node)+1,defined)
        for item in list(defined):
            if item.get('name') in ('_xlnm.Print_Area','_xlnm.Print_Titles') and item.get('localSheetId') in ('2','3','4'):defined.remove(item)
        fresh_defined=xml(fresh.read('xl/workbook.xml')).find('{'+S+'}definedNames')
        if fresh_defined is not None:
            for element in fresh_defined:
                item=copy.deepcopy(element);item.set('localSheetId',str(int(item.get('localSheetId','0'))+2));defined.append(item)
        parts['xl/workbook.xml']=xml_bytes(workbook)
        modified=set(mapping.values())|{'xl/styles.xml','[Content_Types].xml','xl/workbook.xml'}
        preserved=[name for name in original.namelist() if name not in modified]
        with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as output:
            for name,data in parts.items():output.writestr(name,data)
    with zipfile.ZipFile(template) as a,zipfile.ZipFile(destination) as b:
        unchanged=all(a.read(name)==b.read(name) for name in preserved)
        if not unchanged:raise ValueError('Original workbook parts changed unexpectedly')
        for name in ['fonts','fills','borders','cellXfs']:
            before=xml(a.read('xl/styles.xml')).find('{'+S+'}'+name);after=xml(b.read('xl/styles.xml')).find('{'+S+'}'+name)
            for i,element in enumerate(before):
                if ET.tostring(element,method='c14n')!=ET.tostring(after[i],method='c14n'):raise ValueError('Original styles changed')
    return {'preserved_original_parts':len(preserved),'original_parts_byte_identical':True,'sheet_1_2_byte_identical':True,'original_styles_unchanged':True,'modified_sheet_parts':[targets[i][1] for i in (2,3,4)]}

NAVY='363636';BLUE='F3F3F3';WHITE='FFFFFF';GRAY='666666';LINE='DDDDDD'

def put(ws,area,text,fill=None,size=11,bold=False,color=NAVY):
    ws.merge_cells(area);cell=ws[area.split(':')[0]];cell.value=str(text) if text is not None else ''
    cell.data_type='s';cell.font=Font(name='Arial',size=size,bold=bold,color=color);cell.alignment=Alignment(horizontal='left',vertical='top',wrap_text=True,indent=1)
    if fill:
        for row in ws[area]:
            for c in row:c.fill=PatternFill('solid',fgColor=fill)
    return cell

def image_at(ws,path,col,row,max_width,max_height):
    with Image.open(path) as source:width,height=ImageOps.exif_transpose(source).size
    scale=min(max_width/width,max_height/height);pic=XLImage(str(path));pic.width=width*scale;pic.height=height*scale
    pic.anchor=OneCellAnchor(_from=AnchorMarker(col=col,row=row-1,colOff=int((max_width-pic.width)/2*9525)+10*9525,rowOff=10*9525),ext=XDRPositiveSize2D(int(pic.width*9525),int(pic.height*9525)))
    ws.add_image(pic)

def copy_cell_style(source,target):
    if source.has_style:
        target.font=copy.copy(source.font);target.fill=copy.copy(source.fill);target.border=copy.copy(source.border)
        target.alignment=copy.copy(source.alignment);target.number_format=source.number_format;target.protection=copy.copy(source.protection)

def base_sheet(ws,title,metadata,logo=None):
    ws.sheet_view.showGridLines=False
    for i in range(1,13):ws.column_dimensions[get_column_letter(i)].width=12
    for row in range(1,7):ws.row_dimensions[row].height=24
    if logo:image_at(ws,logo,0,1,175,65)
    put(ws,'C1:I3',title,size=20,bold=True);put(ws,'J1:L2','P/N: '+metadata.get('part_number',''),size=12,bold=True)
    put(ws,'J3:L4','Rev: '+metadata.get('revision',''),size=11)
    put(ws,'A6:L6',title,bold=True,size=12)
    ws.freeze_panes='A9';ws.sheet_properties.pageSetUpPr.fitToPage=True
    ws.page_setup.orientation='landscape';ws.page_setup.paperSize=ws.PAPERSIZE_A4;ws.page_setup.fitToWidth=1;ws.page_setup.fitToHeight=0
    ws.print_options.horizontalCentered=True;ws.print_title_rows='1:8';ws.oddFooter.center.text='Trang &P / &N';ws.oddFooter.right.text=metadata.get('part_number','')
    ws.page_margins.left=.25;ws.page_margins.right=.25;ws.page_margins.top=.35;ws.page_margins.bottom=.35

class ExcelJob:
    def __init__(self,args):
        self.args=args;self.folder,self.template,self.description,self.pdf,self.photos=discover(args.folder,args.template,args.description,args.pdf,args.images)
        self.out=Path(args.output).resolve();self.out.mkdir(parents=True,exist_ok=True);(self.out/'traces').mkdir(exist_ok=True);(self.out/'assets').mkdir(exist_ok=True)
        self.client=Pipeline.__new__(Pipeline);self.client.args=SimpleNamespace(parallel=2,api_parallel=2,base=args.base,model=args.model);self.client.init_transport(self.client.args);self.client.out=self.out;self.client.headers={'Content-Type':'application/json'}
        import os
        if os.environ.get('VIDEO_GUIDE_API_KEY'):self.client.headers['Authorization']='Bearer '+os.environ['VIDEO_GUIDE_API_KEY']
        self.sources=source_items(self.description.read_text(encoding='utf-8-sig'));self.image_map={}
        for i,path in enumerate(self.photos):
            ident=f'IMG_{i+1:03d}';destination=self.out/'assets'/(ident+'.jpg')
            with Image.open(path) as original:image=ImageOps.exif_transpose(original).convert('RGB');image.thumbnail((1800,1800));image.save(destination,'JPEG',quality=95)
            self.image_map[ident]={'id':ident,'file':str(path.relative_to(self.folder)),'path':str(destination),'order':i+1}
        signature={str(p.relative_to(self.folder)):digest_file(p) for p in [self.template,self.description,self.pdf]+self.photos}
        config={'version':VERSION,'inputs':signature,'model':args.model,'base':args.base}
        if (self.out/'config.json').exists() and json.loads((self.out/'config.json').read_text())!=config:raise ValueError('Output belongs to another dataset; choose a new directory')
        save(self.out/'config.json',config)

    def ask(self,name,content,max_tokens,validate,schema):
        # Bound arrays and prose in the actual decoding grammar, not only a prompt.
        # A ruler must not cause the model to enumerate numbers indefinitely.
        input_hash=hashlib.sha256(json.dumps({'content':content,'schema':schema},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        trace=self.out/'traces'/(name+'.json')
        if trace.exists():
            cached=json.loads(trace.read_text())
            if cached.get('input_sha256')==input_hash and cached.get('parsed') is not None:
                validate(cached['parsed']);self.client.cache_hit();return cached['parsed']
        payload={'model':self.args.model,'messages':[{'role':'user','content':content}],'temperature':0.1,'max_tokens':max_tokens,
                 'chat_template_kwargs':{'enable_thinking':False},'response_format':{'type':'json_schema','json_schema':{'name':'excel_data','strict':True,'schema':schema}}}
        last=None
        for attempt in range(3):
            started=time.monotonic()
            try:
                response=self.client.post(payload);choice=response['choices'][0]
                if choice.get('finish_reason')=='length':raise ValueError('Bounded response exceeded token budget')
                result=json.loads(choice['message']['content']);validate(result)
                logged=copy.deepcopy(payload)
                for message in logged['messages']:
                    if isinstance(message['content'],list):
                        for item in message['content']:
                            if item.get('type')=='image_url':item['image_url']['url']='sha256:'+hashlib.sha256(item['image_url']['url'].encode()).hexdigest()
                save(trace,{'input_sha256':input_hash,'request':logged,'parsed':result,'raw_response':response,'elapsed_seconds':round(time.monotonic()-started,3)})
                return result
            except Exception as error:
                last=error;print('Excel request retry',name,attempt+1,str(error)[:180],flush=True)
                if attempt==2:raise
                if 'response' in locals():save(self.out/'traces'/(name+f'_attempt_{attempt+1}.json'),{'raw_response':response,'error':str(error)})
                reminder='Trả toàn bộ JSON, giữ đúng IDs và thứ tự nguồn. Lỗi cần sửa: '+str(error)
                if isinstance(content,list):payload['messages'][0]['content']=content+[{'type':'text','text':reminder}]
                else:payload['messages'][0]['content']=content+'\n'+reminder
                time.sleep(1)
        raise last

    def read_images(self):
        entries=list(self.image_map.values());batches=[entries[i:i+2] for i in range(0,len(entries),2)]
        prompt='''Quan sát từng ảnh thực tế độc lập. Không đoán trình tự hay thông số không đọc được. Mô tả tối đa 400 ký tự. Chữ thấy rõ tối đa 10 cụm, bỏ các vạch/số thước lặp; không liệt kê dãy số hoặc suy ra số không hiện rõ. Trả JSON {"images":[{"id":"IMG_001","description":"chi tiết nhìn thấy; đầu dây, terminal, nhãn, ống, đầu nối, tổng thể hoặc chi tiết","visible_text":["chữ/số đọc được"],"view":"toàn thể hoặc cận cảnh","uncertainty":"chỗ chưa đọc rõ"}]}. Đủ mỗi ID, không thêm ID.'''
        def read(batch):
            content=[{'type':'text','text':prompt}]
            for image in batch:content += [{'type':'text','text':image['id']},{'type':'image_url','image_url':{'url':photo_url(image['path'])}}]
            def validate(d):
                if not isinstance(d.get('images'),list) or {i.get('id') for i in d['images']}!={i['id'] for i in batch} or len(d['images'])!=len(batch):raise ValueError('Cover each requested image exactly once')
                for i in d['images']:
                    if not isinstance(i.get('description'),str) or not isinstance(i.get('visible_text'),list):raise ValueError('Invalid image description')
            item_schema=object_schema({'id':{'type':'string','enum':[i['id'] for i in batch]},'description':string_schema(500),'visible_text':array_schema(string_schema(80),10),'view':string_schema(80),'uncertainty':string_schema(300)})
            schema=object_schema({'images':array_schema(item_schema,len(batch),len(batch))})
            return self.ask('images_'+batch[0]['id'],content,2200,validate,schema)['images']
        print('Reading',len(entries),'photos in',len(batches),'small batches',flush=True)
        with ThreadPoolExecutor(2) as pool:observations=[item for group in pool.map(read,batches) for item in group]
        save(self.out/'image-observations.json',observations);return observations

    def pdf_images(self):
        pages=[];clips=[]
        with pymupdf.open(self.pdf) as doc:
            for i,page in enumerate(doc):
                path=self.out/'assets'/f'pdf_page_{i+1:03d}.png';page.get_pixmap(matrix=pymupdf.Matrix(2,2)).save(path)
                pages.append({'page':i+1,'path':str(path),'text':page.get_text(),'embedded_images':len(page.get_images())})
                for j,img in enumerate(page.get_images(full=True)):
                    data=doc.extract_image(img[0]);(self.out/'assets'/f'pdf_embedded_{i+1:03d}_{j+1:03d}.{data["ext"]}').write_bytes(data['image'])
                prompt='''Xác định các vùng hình/bản vẽ và bảng quan trọng trong trang PDF, không đọc lại toàn trang thành văn bản. Trả JSON {"regions":[{"title":"tên vùng đúng nội dung nhìn thấy","bbox":[x1,y1,x2,y2],"description":"mô tả quan sát"}],"metadata":{"part_number":"mã sản phẩm đọc được hoặc rỗng","revision":"phiên bản đọc được hoặc rỗng"},"notes":["điểm nguồn chưa rõ hoặc khác mô tả nếu có"]}. Tọa độ 0–1000, tối đa 6 vùng, giữ trọn nội dung của vùng. Không tự đoán số đo.'''
                content=[{'type':'text','text':prompt},{'type':'image_url','image_url':{'url':photo_url(path,(1600,1200))}}]
                def validate(d):
                    if not isinstance(d.get('regions'),list) or len(d['regions'])>6:raise ValueError('At most 6 PDF regions')
                    for region in d['regions']:
                        b=region.get('bbox',[])
                        if len(b)!=4 or not all(isinstance(v,(int,float)) for v in b) or not (0<=b[0]<b[2]<=1000 and 0<=b[1]<b[3]<=1000):raise ValueError('Invalid PDF region')
                region_schema=object_schema({'title':string_schema(180),'bbox':array_schema({'type':'number','minimum':0,'maximum':1000},4,4),'description':string_schema(350)})
                schema=object_schema({'regions':array_schema(region_schema,6),'metadata':object_schema({'part_number':string_schema(100),'revision':string_schema(40)}),'notes':array_schema(string_schema(250),6)})
                result=self.ask(f'pdf_regions_{i+1:03d}',content,3200,validate,schema);pages[-1]['metadata']=result.get('metadata',{});pages[-1]['notes']=result.get('notes',[])
                with Image.open(path) as im:
                    for j,region in enumerate(result['regions']):
                        x1,y1,x2,y2=region['bbox'];padding=8
                        bounds=(max(0,int(x1/1000*im.width)-padding),max(0,int(y1/1000*im.height)-padding),min(im.width,int(x2/1000*im.width)+padding),min(im.height,int(y2/1000*im.height)+padding))
                        target=self.out/'assets'/f'pdf_crop_{i+1:03d}_{j+1:03d}.png';im.crop(bounds).save(target)
                        clips.append(dict(region,page=i+1,path=str(target)))
        save(self.out/'pdf-images.json',{'pages':pages,'regions':clips});return pages,clips

    def plan(self,observations,pages):
        prompt='''Ghép mô tả gốc với ảnh thực tế để tạo Work Instruction trong Excel. Không viết hướng dẫn mới, không thay số, mã hoặc đơn vị của mô tả. Phân loại mỗi đoạn nguồn đúng một lần theo thứ tự. Các tiêu đề nhóm (ví dụ đầu dây) là group, thao tác là step, thành phẩm/kết quả là result, ghi chú là note; thông tin mã/tựa đề là metadata. Với step/result, chọn tối đa 2 ảnh đúng nội dung nhìn thấy, có thể dùng lại ảnh cho nhiều đoạn nếu hợp lý; nếu không có ảnh phù hợp để [] và needs_review=true. Chọn ảnh thành phẩm từ nhóm ảnh cuối khi chúng thể hiện đúng kết quả; không mặc định ảnh cuối luôn là ảnh thành phẩm. Với result, nếu có hai góc bổ sung phù hợp thì chọn một ảnh tổng thể và một ảnh cận cảnh thành phẩm/nhãn ở nhóm cuối để minh họa kết quả đầy đủ hơn; không dùng ảnh đang đo thay cho ảnh thành phẩm. Không xác nhận loại tool, số đo, chất lượng kết nối chỉ từ ảnh không có bằng chứng. Với thao tác có số đo, ưu tiên ảnh có thước hoặc chỉ dấu tương ứng nếu có; không dùng cùng một ảnh thay cho hai kết quả khác số đo khi ảnh không minh họa được cả hai. Những chỗ không rõ hoặc khác giữa PDF, mô tả và ảnh ghi warnings, mỗi cảnh báo là một câu riêng ngắn, không chèn danh sách hay JSON vào chuỗi cảnh báo, không tự sửa nguồn.
Trả JSON {"metadata":{"part_number":"...","revision":"..."},"items":[{"source_id":"TXT_001","kind":"metadata|group|step|note|result","image_ids":["IMG_001"],"match_reason":"căn cứ thị giác ghép ảnh; hoặc lý do không có ảnh","needs_review":true,"result_description":"chỉ dùng cho kind=result: mô tả kết quả nhìn thấy, không tuyên bố đạt kiểm tra điện"}],"warnings":["điểm cần kiểm tra"]}. Cover all source IDs once, source order unchanged. Không đổi mô tả gốc.
NGUỒN MÔ TẢ:\n'''+json.dumps(self.sources,ensure_ascii=False)+'\nQUAN SÁT ẢNH (order là thứ tự tên file, chỉ gợi ý):\n'+json.dumps([dict(o,order=self.image_map[o['id']]['order']) for o in observations],ensure_ascii=False)+'\nPDF:\n'+json.dumps([{k:p.get(k) for k in ['page','text','metadata','notes']} for p in pages],ensure_ascii=False)
        def validate(d):
            items=d.get('items',[])
            if [item.get('source_id') for item in items]!=[item['id'] for item in self.sources]:raise ValueError('Cover every source ID exactly once in original order')
            for item in items:
                if item.get('kind') not in ['metadata','group','step','note','result']:raise ValueError('Invalid kind')
                ids=item.get('image_ids',[])
                if not isinstance(ids,list) or len(ids)>2 or len(set(ids))!=len(ids) or any(i not in self.image_map for i in ids):raise ValueError('Invalid image IDs')
                if not isinstance(item.get('needs_review'),bool):raise ValueError('needs_review must be boolean')
            if not any(i['kind']=='result' for i in items):raise ValueError('Need a result item with product photograph; retain its source ID')
        item_schema=object_schema({'source_id':{'type':'string','enum':[s['id'] for s in self.sources]},'kind':{'type':'string','enum':['metadata','group','step','note','result']},'image_ids':array_schema({'type':'string','enum':list(self.image_map)},2),'match_reason':string_schema(350),'needs_review':{'type':'boolean'},'result_description':string_schema(600)})
        schema=object_schema({'metadata':object_schema({'part_number':string_schema(100),'revision':string_schema(40)}),'items':array_schema(item_schema,len(self.sources),len(self.sources)),'warnings':array_schema(string_schema(260),len(self.sources)+4)})
        result=self.ask('matching_plan',prompt,6000,validate,schema)
        by_id={s['id']:s['text'] for s in self.sources}
        group=''
        for item in result['items']:
            item['text']=by_id[item['source_id']]
            if item['kind']=='group':group=item['text']
            item['group_text']=group if item['kind'] in ('step','result') else ''
        save(self.out/'matching-plan.json',result);return result

    def select_results(self,plan,pages):
        # Result photos normally occur near the end; inspect those candidates directly
        # against the PDF instead of guessing completion from catalog captions alone.
        entries=list(self.image_map.values());tail=entries[-max(8,(len(entries)+2)//3):]
        for item in [i for i in plan['items'] if i['kind']=='result']:
            chosen_ids=set(item['image_ids']);candidates=[i for i in entries if i in tail or i['id'] in chosen_ids]
            def inspect(image):
                prompt='''Ảnh 1 là ảnh thực tế ứng viên; ảnh 2 là trang bản vẽ PDF nguồn. Đối chiếu với mô tả kết quả và mô tả gốc để phân loại ảnh thực tế. Không tự thêm điều kiện hoàn thiện mà nguồn không yêu cầu; những chi tiết hoặc đầu hở đúng cấu trúc bản vẽ không tự động là chưa lắp xong. Không coi việc không đọc thấy mã định danh là bằng chứng ảnh không liên quan, nhưng phải ghi cần đối chiếu mã. stage: whole (ảnh tổng thể sản phẩm sau lắp), detail (cận cảnh thành phẩm/đầu nối/tem sau lắp), intermediate (thao tác hoặc đo đang thực hiện), unrelated (không liên quan). Trả JSON {"image_id":"...","stage":"whole|detail|intermediate|unrelated","reason":"căn cứ nhìn thấy; không đoán","needs_review":true}. Không tuyên bố kiểm tra điện đã đạt.
MÔ TẢ KẾT QUẢ: '''+item['text']+'\nMÔ TẢ GỐC:\n'+json.dumps(self.sources,ensure_ascii=False)+'\nID ẢNH 1: '+image['id']
                content=[{'type':'text','text':prompt},{'type':'image_url','image_url':{'url':photo_url(image['path'])}},{'type':'image_url','image_url':{'url':photo_url(pages[0]['path'],(1400,1000))}}]
                schema=object_schema({'image_id':{'type':'string','enum':[image['id']]},'stage':{'type':'string','enum':['whole','detail','intermediate','unrelated']},'reason':string_schema(400),'needs_review':{'type':'boolean'}})
                caption=self.ask('result_candidate_'+item['source_id']+'_'+image['id'],content,1600,lambda d:None,schema)
                caption['fit']=caption['stage'] in ('whole','detail')
                return caption
            print('Checking',len(candidates),'late result-photo candidates against the PDF',flush=True)
            with ThreadPoolExecutor(2) as pool:checked=list(pool.map(inspect,candidates))
            valid=[c for c in checked if c['stage'] in ('whole','detail')]
            if not valid:raise ValueError('Chưa tìm được ảnh kết quả phù hợp; không xuất sheet 4 trống ảnh.')
            prompt='''Chọn 1–2 ảnh kết quả đã được xem trực tiếp và đối chiếu PDF. Ưu tiên một ảnh tổng thể và một ảnh cận cảnh CHÍNH thành phẩm đã lắp (đối tượng nêu trong mô tả kết quả) ở nhóm ảnh cuối theo order, thay vì ảnh gia công từng chi tiết. Tránh hai ảnh trùng nội dung. Ảnh 1 là bảng ảnh ứng viên có IDs; ảnh 2 là bản vẽ nguồn. Kiểm tra trực tiếp hình dạng sản phẩm, không tin riêng nhãn whole/detail nếu hình không khớp. Mỗi trường mô tả/lý do chỉ 1–2 câu ngắn hoàn chỉnh. Chỉ chọn trong candidates được cung cấp. Trả JSON {"image_ids":["..."],"result_description":"kết quả quan sát đúng các ảnh đã chọn","reason":"căn cứ lựa chọn","needs_review":true}. Không đánh giá chất lượng gia công, không dùng câu xác nhận mọi bước đã hoàn tất; chỉ ghi quan sát nhìn thấy. Không khẳng định chất lượng điện. Trong result_description không lặp mã hay tên định danh lấy từ mô tả nguồn trừ khi đọc được chính chữ đó trên ảnh đã chọn; dùng tên đối tượng thị giác chung khi mã không hiện rõ.
MÔ TẢ KẾT QUẢ: '''+item['text']+'\nCANDIDATES:\n'+json.dumps([dict(v,order=self.image_map[v['image_id']]['order']) for v in valid],ensure_ascii=False)
            schema=object_schema({'image_ids':array_schema({'type':'string','enum':[v['image_id'] for v in valid]},2,1),'result_description':string_schema(500),'reason':string_schema(400),'needs_review':{'type':'boolean'}})
            def validate(d):
                if len(set(d['image_ids']))!=len(d['image_ids']):raise ValueError('Choose distinct result images')
            catalog=Image.new('RGB',(900,((len(valid)+2)//3)*360),'white');draw=ImageDraw.Draw(catalog)
            for index,candidate in enumerate(valid):
                ident=candidate['image_id'];x=index%3*300;y=index//3*360
                with Image.open(self.image_map[ident]['path']) as source:picture=source.convert('RGB');picture.thumbnail((280,320))
                catalog.paste(picture,(x+(300-picture.width)//2,y+32));draw.text((x+10,y+10),ident,fill='black')
            catalog_path=self.out/'assets'/('result_catalog_'+item['source_id']+'.jpg');catalog.save(catalog_path,quality=95)
            content=[{'type':'text','text':prompt},{'type':'image_url','image_url':{'url':photo_url(catalog_path,(1400,1200))}},{'type':'image_url','image_url':{'url':photo_url(pages[0]['path'],(1400,1000))}}]
            selection=self.ask('result_selection_'+item['source_id'],content,1800,validate,schema)
            by_id={v['image_id']:v for v in checked};item['image_ids']=selection['image_ids'];item['result_description']=selection['result_description'];item['match_reason']=selection['reason']
            item['needs_review']=selection['needs_review'] or any(by_id[i]['needs_review'] for i in item['image_ids'])
            item['checks']=[{'image_id':i,'fit':True,'needs_review':by_id[i]['needs_review'],'reason':by_id[i]['reason'],'selected_by':'qwen38'} for i in item['image_ids']]
            save(self.out/('result-candidates-'+item['source_id']+'.json'),checked)
        save(self.out/'matching-plan.json',plan)

    @staticmethod
    def copy_template_header(source,target):
        for row in range(1,5):
            for col in range(1,19):
                a=source.cell(row,col);b=target.cell(row,col)
                if a.value is not None:b.value=a.value
                copy_cell_style(a,b)
        for merged in source.merged_cells.ranges:
            if merged.min_row<=4:target.merge_cells(str(merged))
        for col,dimension in source.column_dimensions.items():target.column_dimensions[col].width=dimension.width
        for row in range(1,5):target.row_dimensions[row].height=source.row_dimensions[row].height
        target.sheet_view.showGridLines=source.sheet_view.showGridLines

    def native_wire_rows(self,plan,pages):
        source=[{'source_id':i['source_id'],'kind':i['kind'],'text':i['text'],'group':i.get('group_text','')} for i in plan['items'] if i['kind']=='step']
        fields=['item_number','part_number','color','cut_length_inches','cut_length_mm','strip_tool','strip_left_inches','strip_right_inches','strip_left_mm','strip_right_mm']
        row_fields={'source_id':{'type':'string','enum':[i['source_id'] for i in source]}}
        row_fields.update({key:string_schema(80) for key in fields})
        schema=object_schema({'rows':array_schema(object_schema(row_fields),len(source),len(source))})
        prompt='Return EXACTLY one row for each source_id in the same order, no grouping, skipping, duplicate IDs, or combining information. Use the sample headings ITEM, PART, MÀU, Cắt (In), Cắt máy (mm), Tool tuốt, Kích thước tuốt Trái/Phải (In), Trái/Phải (mm). Cut (In/mm) means cutting the wire described, not cutting another material such as tubing; leave it blank for other materials. These are independent rows; original wording is placed beside each row. Fill a field only when explicit for that wire in its source item or clearly labeled group. Keep unsupported cells empty. Do not put material replacement part numbers in wire PART cells; do not infer wire colors or convert units. Map end A/B to left/right only when PDF/source clearly shows the orientation. Return JSON rows, source_id and fields: '+', '.join(fields)+'.\nSOURCE ITEMS:\n'+json.dumps(source,ensure_ascii=False)+'\nPDF OCR metadata (may be incorrect):\n'+json.dumps(plan.get('pdf_metadata',{}),ensure_ascii=False)
        def validate(data):
            ids=[row['source_id'] for row in data['rows']]
            if ids!=[i['source_id'] for i in source]:raise ValueError('Need exactly one matching table row for each source ID, in order')
        content=[{'type':'text','text':prompt}]
        if pages:content.append({'type':'image_url','image_url':{'url':photo_url(pages[0]['path'],(1600,1200))}})
        return self.ask('native_wire_table_v4',content,3500,validate,schema)['rows']

    def pair_every_step_photo(self,plan,observations):
        """Use Qwen38 vision to assign one best available photo to each operation."""
        steps=[i for i in plan['items'] if i['kind']=='step']
        if not steps:raise ValueError('No operation steps to pair with photos')
        catalog=Image.new('RGB',(1200,((len(self.image_map)+4)//5)*210),'white');draw=ImageDraw.Draw(catalog)
        for index,image in enumerate(self.image_map.values()):
            x=index%5*240;y=index//5*210
            with Image.open(image['path']) as source:
                picture=ImageOps.exif_transpose(source).convert('RGB');picture.thumbnail((220,175))
            catalog.paste(picture,(x+(240-picture.width)//2,y+27))
            draw.text((x+8,y+7),image['id'],fill='black')
        catalog_path=self.out/'assets'/'step-photo-catalog.jpg';catalog.save(catalog_path,quality=94)
        candidates=[{'id':o['id'],'description':o.get('description',''),'visible_text':o.get('visible_text',[]),'view':o.get('view','')} for o in observations]
        source=[{'source_id':i['source_id'],'group':i.get('group_text',''),'description':i['text']} for i in steps]
        ids=list(self.image_map)
        prompt='''For every operation, choose exactly one best matching photo from the supplied contact sheet and visual catalog. Every operation row must receive an image, so select the closest visible object, state, or result even when the photo does not prove every written measurement or tool. Prefer the clearest direct visual match. Reuse an image only when it is genuinely the best match for more than one operation. Read the actual contact sheet with vision; use captions only as supporting information. Do not infer numbers, tools, or claims that are not visible. Return one row for every source_id, in source order, with exactly one image_id, a short visual reason, and needs_review=true only if no candidate is a reasonable visual match.\nOPERATIONS:\n'''+json.dumps(source,ensure_ascii=False)+'\nPHOTO CATALOG:\n'+json.dumps(candidates,ensure_ascii=False)
        row_schema=object_schema({'source_id':{'type':'string','enum':[i['source_id'] for i in steps]},'image_id':{'type':'string','enum':ids},'reason':string_schema(350),'needs_review':{'type':'boolean'}})
        schema=object_schema({'pairs':array_schema(row_schema,len(steps),len(steps))})
        def validate(data):
            pairs=data.get('pairs',[])
            if [p.get('source_id') for p in pairs]!=[i['source_id'] for i in steps]:raise ValueError('Pair every operation exactly once in source order')
            if any(p.get('image_id') not in self.image_map for p in pairs):raise ValueError('Each operation needs a valid photo ID')
        content=[{'type':'text','text':prompt},{'type':'image_url','image_url':{'url':photo_url(catalog_path,(1600,1400))}}]
        pairs=self.ask('best_step_photo_pairs_v1',content,3000,validate,schema)['pairs']
        by_id={i['source_id']:i for i in steps}
        for pair in pairs:
            item=by_id[pair['source_id']];ident=pair['image_id']
            check={'image_id':ident,'fit':True,'needs_review':pair['needs_review'],
                   'reason':pair['reason'],'selected_by':'qwen38-best-per-step'}
            item['image_ids']=[ident];item['checks']=[check]
            item['match_reason']=check['reason'];item['needs_review']=check['needs_review']
        save(self.out/'matching-plan.json',plan)

    def final_warnings(self,plan,pages):
        evidence=[{k:i.get(k) for k in ('source_id','text','kind','image_ids','needs_review','match_reason','result_description','checks')} for i in plan['items']]
        for i in evidence:
            i['checks']=[{k:c.get(k) for k in ('image_id','fit','reason')} for c in i.get('checks') or []]
        prompt='Viết các cảnh báo ngắn cho kết quả ghép ảnh do Qwen38 chọn. Mỗi bước đều đã có một ảnh được chọn; không ghi là thiếu ảnh. Nêu riêng chi tiết số đo/tool/mã chưa thể xác nhận bằng hình nếu cần; không khẳng định có sai khác vật lý nếu chỉ không đọc rõ. Metadata PDF là kết quả đọc tự động, chưa xác minh: nếu khác nguồn, ghi cần đọc lại chứ không coi mã OCR là mã đúng. Không sửa mô tả nguồn. Trả JSON {"warnings":["..."]}, tối đa 12 câu ngắn, không nhét danh sách hay JSON vào chuỗi.\nKẾT QUẢ CUỐI:\n'+json.dumps(evidence,ensure_ascii=False)+'\nPDF đọc tự động:\n'+json.dumps([p.get('metadata',{}) for p in pages],ensure_ascii=False)
        schema=object_schema({'warnings':array_schema(string_schema(260),12)})
        plan['warnings']=self.ask('qwen_final_warnings',prompt,2000,lambda d:None,schema)['warnings']
        save(self.out/'matching-plan.json',plan)

    def workbook(self,plan,pages,clips):
        if any(i['kind']=='result' and not i['image_ids'] for i in plan['items']):raise ValueError('Sheet kết quả phải có ảnh phù hợp trước khi xuất.')
        original=load_workbook(self.template);names=original.sheetnames
        if len(names)<5:raise ValueError('Mẫu cần ít nhất 5 sheet')
        wb=Workbook();wb.remove(wb.active);sheets=[wb.create_sheet(names[i]) for i in (2,3,4)]
        metadata=plan.get('metadata',{});source3=original.worksheets[2];source4=original.worksheets[3]
        ws=sheets[0];self.copy_template_header(source3,ws)
        placements=build_native_sheet(self,source3,ws,plan,pages,(object_schema,array_schema,string_schema,photo_url,copy_cell_style,image_at))
        ws=sheets[1];self.copy_template_header(source4,ws)
        ws.page_setup.orientation=source4.page_setup.orientation;ws.page_setup.paperSize=source4.page_setup.paperSize
        ws.page_setup.fitToWidth=1;ws.page_setup.fitToHeight=0;ws.sheet_properties.pageSetUpPr.fitToPage=True
        _,result_shapes=template_shapes(self.template,3)
        result_placements=[];row=6
        for item in [i for i in plan['items'] if i['kind']=='result']:
            text='\n'.join(filter(None,[item['text'],item.get('result_description','')]))
            if result_shapes:
                result_placements.append({'shape_id':max(result_shapes,key=lambda s:len(s['text']))['id'],'text':text,'col':1,'end_col':11,'row':row,'end_row':row+5})
            else:
                ws.merge_cells(start_row=row,start_column=2,end_row=row+4,end_column=11)
                ws.cell(row,2,text).alignment=Alignment(vertical='top',wrap_text=True)
            for ident in item['image_ids']:
                image_row=row+6
                for r in range(row,image_row+13):ws.row_dimensions[r].height=18
                image_at(ws,self.image_map[ident]['path'],1,image_row,610,270)
                row=image_row+14
        ws.print_area=f'A1:L{row}'
        ws=sheets[2];ws.page_setup.paperSize=ws.PAPERSIZE_A3;row=8
        for page in pages:
            if row>8:ws.row_breaks.append(Break(id=row-1))
            put(ws,f'A{row}:L{row+1}',f'Trang PDF {page["page"]} — bản đầy đủ',fill=NAVY,bold=True,color=WHITE);row+=2
            with Image.open(page['path']) as im:height=1050*im.height/im.width
            rows=int(height/28)+2
            for r in range(row,row+rows):ws.row_dimensions[r].height=21
            image_at(ws,page['path'],0,row,1050,height);row+=rows+1
            for clip in [c for c in clips if c['page']==page['page']]:
                ws.row_breaks.append(Break(id=row-1))
                put(ws,f'A{row}:L{row+1}',clip['title'],fill=BLUE,bold=True);row+=2
                with Image.open(clip['path']) as im:height=min(520,1050*im.height/im.width)
                rows=int(height/28)+2
                for r in range(row,row+rows):ws.row_dimensions[r].height=21
                image_at(ws,clip['path'],0,row,1050,height);row+=rows
                put(ws,f'A{row}:L{row+2}',clip.get('description',''),size=10);row+=4
        ws.print_area=f'A1:L{row}'
        generated=self.out/'generated-sheets.xlsx';wb.save(generated);destination=self.out/(self.folder.name+'_huong_dan.xlsx')
        preservation=transplant(self.template,generated,destination,preserve_header=True)
        inject_textboxes(self.template,destination,{2:placements,3:result_placements})
        check=load_workbook(destination)
        if check.sheetnames!=original.sheetnames:raise ValueError('Sheet order changed')
        for index in (0,1):
            a=original.worksheets[index];b=check.worksheets[index]
            if [(c.coordinate,c.value) for row in a for c in row if c.value is not None]!=[(c.coordinate,c.value) for row in b for c in row if c.value is not None]:raise ValueError('Sheet 1/2 cell values changed')
            if len(a._images)!=len(b._images):raise ValueError('Sheet 1/2 images changed')
        save(self.out/'preservation-check.json',preservation);save(self.out/'matching-plan.json',plan)
        return destination

    def item_card(self,ws,row,item,number):
        for r in range(row,row+13):ws.row_dimensions[r].height=22
        put(ws,f'A{row}:A{row+11}',number,fill=BLUE,bold=True,size=16)
        put(ws,f'B{row}:F{row+11}',item['text'],size=12)
        if item['image_ids']:
            width=510/len(item['image_ids'])
            for i,ident in enumerate(item['image_ids']):image_at(ws,self.image_map[ident]['path'],6+i*3 if len(item['image_ids'])==2 else 6,row,width-12,322)
        for col in range(1,13):ws.cell(row+11,col).border=Border(bottom=Side(style='thin',color=LINE))

    def run(self):
        start=time.monotonic();status={'status':'running','version':VERSION};save(self.out/'excel-result.json',status)
        try:
            observations=self.read_images();pages,clips=self.pdf_images();plan=self.plan(observations,pages)
            print('Matching source descriptions with selected photos via Qwen38',flush=True);self.select_results(plan,pages);self.pair_every_step_photo(plan,observations);self.final_warnings(plan,pages)
            print('Building aligned Excel sheets and preserving original parts',flush=True);destination=self.workbook(plan,pages,clips)
            status.update(status='completed',file=destination.name,matching_method='Qwen38 vision',steps=sum(i['kind']=='step' for i in plan['items']),results=sum(i['kind']=='result' for i in plan['items']),photos=len(self.photos),pdf_pages=len(pages),needs_review=sum(i['needs_review'] for i in plan['items'] if i['kind'] in ('step','result')),warnings=plan.get('warnings',[]))
            print('EXCEL_RESULT',json.dumps(status,ensure_ascii=False),flush=True)
        except BaseException as error:status.update(status='failed',error=type(error).__name__+': '+str(error));raise
        finally:status['elapsed_seconds']=round(time.monotonic()-start,3);save(self.out/'excel-result.json',status);save(self.out/'performance.json',self.client.performance)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--folder',required=True);parser.add_argument('--output',required=True)
    for name in ['template','description','pdf','images']:parser.add_argument('--'+name)
    parser.add_argument('--base',default='http://127.0.0.1:8000/v1');parser.add_argument('--model',default='qwen38')
    ExcelJob(parser.parse_args()).run()
