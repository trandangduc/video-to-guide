"""Build a reviewable illustrated guide from a completed timestamped transcript."""
import base64, html, json, math, re, time, urllib.request, urllib.error
from pathlib import Path
import av
from PIL import Image, ImageStat, ImageFilter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as PDFImage, PageBreak, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.units import cm

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'output'/'layout_netlist_guide'
SOURCE=ROOT/'B_i 7 -  Ph_n 1  Gi_i thi_u file Layout_ s_a l_i khi import netlist v_o Layout.mp4'
API='http://127.0.0.1:8000/v1/chat/completions'
MODEL='qwen38'

def dump(path,data):
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)

def stamp(t):
    t=int(t);return f'{t//60:02d}:{t%60:02d}'

def llm(messages,max_tokens=6000):
    payload={'model':MODEL,'messages':messages,'temperature':0.15,'max_tokens':max_tokens,'chat_template_kwargs':{'enable_thinking':False}}
    for attempt in range(3):
        try:
            req=urllib.request.Request(API,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(req,timeout=360) as response: data=json.load(response)
            raw=data['choices'][0]['message']['content'] or ''
            if data['choices'][0].get('finish_reason')=='length':raise ValueError('Model response truncated')
            match=re.search(r'```(?:json)?\s*(.*?)\s*```',raw,re.S)
            if match:raw=match.group(1)
            else:
                start=raw.find('{');end=raw.rfind('}')
                if start>=0 and end>start:raw=raw[start:end+1]
            return json.loads(raw)
        except Exception as error:
            if attempt==2:raise
            print('Retry',attempt+1,type(error).__name__,str(error)[:180],flush=True)
            time.sleep(2)

def make_steps():
    cache=OUT/'steps.draft.json'
    if cache.exists():return json.loads(cache.read_text())
    rows=json.loads((OUT/'transcript.raw.json').read_text());by_id={r['id']:r for r in rows}
    transcript='\n'.join(f"{r['id']} [{stamp(r['start'])}-{stamp(r['end'])}] {r['text']}" for r in rows)
    prompt='''Bạn biên soạn tài liệu hướng dẫn tiếng Việt từ lời giảng video về OrCAD/Cadence PCB Layout. Hãy viết nội dung đủ để người đọc làm theo, có cả giải thích quan trọng ở đầu. Phần mềm cụ thể phải dựa trên lời giảng, không tự đổi thành sản phẩm khác.
Chia thành khoảng 20–35 bước/mục hợp lý theo nội dung; tránh gộp một thao tác dài với thao tác khác và không chia thành từng câu nói. Bao phủ toàn bộ video. Sắp xếp theo thời gian, gộp lời lặp, bỏ câu đệm. Chỉ ghi thao tác và đường dẫn menu được nguồn nói rõ; không thêm các bước từ kiến thức ngoài. ASR có thể sai từ tiếng Anh, phần mở rộng: đánh dấu thuật ngữ cần đối chiếu ảnh thay vì đoán chắc chắn. Không bịa số đo, tên file cụ thể, phím tắt hoặc lỗi. Những phần lý thuyết vẫn là một mục giải thích với ảnh minh họa.
Trả JSON thuần: {"title":"...", "summary":"2–3 câu về nội dung thực tế", "steps":[{"title":"...","instruction":"2–5 câu tiếng Việt rõ ràng; chỉ dựa trên nguồn", "source_segment_ids":["seg_0001"], "terms_to_review":["thuật ngữ chưa chắc nếu có"]}]}.
Mỗi mục giữ IDs nguồn liên tiếp cho cả cửa sổ thao tác. Mỗi segment có nội dung hữu ích phải được bao phủ. Không tạo timestamps riêng.
TRANSCRIPT:\n'''+transcript
    doc=llm([{'role':'user','content':prompt}],12000)
    steps=doc.get('steps',[])
    if not steps or len(steps)>60:raise ValueError('Unexpected step count')
    last=-1
    used=set()
    for i,s in enumerate(steps,1):
        ids=s.get('source_segment_ids',[])
        if not ids or any(x not in by_id for x in ids):raise ValueError('Invalid source IDs')
        s['id']=f'step_{i:03d}';s['number']=i
        s['start']=min(by_id[x]['start'] for x in ids);s['end']=max(by_id[x]['end'] for x in ids)
        if s['start']<last:raise ValueError('Steps not chronological')
        last=s['start'];used.update(ids)
        s['source_text']=' '.join(by_id[x]['text'] for x in ids)
    doc['uncovered_segment_ids']=[r['id'] for r in rows if r['id'] not in used]
    dump(cache,doc)
    print('Built',len(steps),'steps; uncovered segments:',len(doc['uncovered_segment_ids']),flush=True)
    return doc

def extract_frame(container,t,path):
    container.seek(int(t*av.time_base))
    for frame in container.decode(video=0):
        if frame.time is not None and frame.time>=t:
            im=frame.to_image()
            raw_path=path.parent/(path.stem+'_original.jpg');im.save(raw_path,quality=92)
            # Retain the application while reducing source-video black margins.
            w,h=im.size;box=(0,int(h*0.067),int(w*0.906),int(h*0.926))
            cropped=im.crop(box);cropped.thumbnail((1500,1000));cropped.save(path,quality=92)
            small=cropped.convert('L').resize((64,36));detail=ImageStat.Stat(small.filter(ImageFilter.FIND_EDGES)).var[0]
            return {'time':round(frame.time,3),'path':str(path.relative_to(OUT)),'original_path':str(raw_path.relative_to(OUT)),'crop_bounds':box,'detail_score':round(detail,2)}
    return None

def select_images(doc):
    frames=OUT/'frames';frames.mkdir(exist_ok=True)
    duration=json.loads((OUT/'media.json').read_text())['duration']
    checkpoint=OUT/'steps.selected.json'
    if checkpoint.exists():
        old=json.loads(checkpoint.read_text());prior={s['id']:s for s in old['steps']}
        for i,s in enumerate(doc['steps']):
            if prior.get(s['id'],{}).get('selection_complete'):doc['steps'][i]=prior[s['id']]
    with av.open(str(SOURCE)) as container:
        for step in doc['steps']:
            if step.get('selection_complete'):continue
            a=max(0,step['start']-3);b=min(duration-0.2,step['end']+3)
            times=[a+(b-a)*fraction for fraction in (0.08,0.24,0.40,0.56,0.72,0.90)]
            candidates=[]
            for j,t in enumerate(times,1):
                path=frames/f"{step['id']}_c{j}.jpg"
                result=extract_frame(container,t,path)
                if result:result['id']=f'c{j}';candidates.append(result)
            if not candidates:raise ValueError('No decodable frames for '+step['id'])
            content=[{'type':'text','text':'''Chọn ảnh minh họa cho một bước trong tài liệu hướng dẫn phần mềm, dựa trên 6 ảnh ứng viên có timestamp.
Trả JSON thuần {"selected_ids":["c1"],"captions":["Chú thích ảnh tiếng Việt cụ thể"],"instruction":"Câu hướng dẫn đã đối chiếu ảnh, 2–5 câu", "title":"Tiêu đề rõ ràng", "terms_to_review":[], "match_status":"matched hoặc partial hoặc no_match", "match_reason":"Bằng chứng nhìn thấy"}.
Chọn 1 ảnh tốt nhất, hoặc 2 ảnh khi thể hiện hai trạng thái/thao tác khác nhau cần thiết. Ưu tiên hộp thoại/lệnh/kết quả khớp nội dung bước, ảnh rõ, không bị menu không liên quan che. Một ảnh sơ đồ vẽ trong Paint có thể hữu ích cho phần giải thích.
Không đoán thao tác từ ảnh tĩnh. Chỉ sửa từ ASR sai hoặc tên menu/phần mở rộng nếu chữ trong ảnh cho phép đối chiếu rõ. Không tự thêm lệnh, số hoặc kiến thức ngoài. Nếu không thấy đúng thao tác, dùng partial/no_match, chọn ảnh bối cảnh và chú thích trung thực. Không viết các câu 'trong ảnh này' vào instruction; viết như tài liệu người dùng. Không biến nội dung chưa rõ thành khẳng định chắc chắn.
BƯỚC: '''+json.dumps({k:step.get(k) for k in ['title','instruction','source_text','terms_to_review']},ensure_ascii=False)}]
            for c in candidates:
                image=Image.open(OUT/c['path']);image.thumbnail((1280,800))
                import io
                buf=io.BytesIO();image.save(buf,format='JPEG',quality=87)
                content.extend([{'type':'text','text':f"Ảnh {c['id']} tại {stamp(c['time'])}"},{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(buf.getvalue()).decode()}}])
            print('Selecting',step['number'],'/',len(doc['steps']),step['title'],stamp(a),stamp(b),flush=True)
            try:
                result=llm([{'role':'user','content':content}],1800)
                lookup={c['id']:c for c in candidates};ids=result.get('selected_ids',[])
                if not ids or len(ids)>2 or len(set(ids))!=len(ids) or any(x not in lookup for x in ids):raise ValueError('Invalid selected IDs')
                chosen=[]
                for k,id_ in enumerate(ids):
                    c=lookup[id_].copy();caps=result.get('captions',[]);c['caption']=caps[k] if k<len(caps) else 'Khung hình tại '+stamp(c['time']);chosen.append(c)
                step['selected_frames']=chosen
                for key in ['instruction','title','terms_to_review','match_status','match_reason']:
                    if key in result:step[key]=result[key]
                step['review_status']='needs_review' if step.get('terms_to_review') or step.get('match_status')!='matched' else 'draft'
            except Exception as error:
                print('Selection fallback:',step['id'],str(error)[:180],flush=True)
                c=candidates[len(candidates)//2].copy();c['caption']='Ảnh bối cảnh tại '+stamp(c['time'])+'; cần kiểm tra lựa chọn ảnh.'
                step['selected_frames']=[c];step['match_status']='no_match';step['review_status']='needs_review';step['selection_error']=str(error)
            step['candidates']=candidates;step['selection_complete']=True
            dump(checkpoint,doc)
    return doc

def export(doc, basename='huong-dan-layout-netlist'):
    title=doc['title'];steps=doc['steps'];summary=doc.get('summary','');duration=json.loads((OUT/'media.json').read_text())['duration']
    toc=''.join(f'<a href="#{s["id"]}"><b>{s["number"]:02d}</b> {html.escape(s["title"])}</a>' for s in steps)
    cards=[]
    for s in steps:
        pictures=[]
        for f in s['selected_frames']:
            data=base64.b64encode((OUT/f['path']).read_bytes()).decode()
            pictures.append(f'<figure><a href="data:image/jpeg;base64,{data}" download="{s["id"]}.jpg"><img src="data:image/jpeg;base64,{data}" alt="{html.escape(f["caption"])}"></a><figcaption>{html.escape(f["caption"])} · {stamp(f["time"])}</figcaption></figure>')
        review=''
        if s.get('review_note'):review='<p class="review">'+html.escape(s['review_note'])+'</p>'
        if s.get('terms_to_review'):review+='<p class="review">Cần đối chiếu thuật ngữ: '+html.escape('; '.join(s['terms_to_review']))+'</p>'
        if s.get('match_status')!='matched':review+='<p class="review">Ảnh minh họa cần kiểm tra thêm với đoạn video gốc.</p>'
        cards.append(f'<article id="{s["id"]}"><div class="meta">BƯỚC {s["number"]:02d} <span>{stamp(s["start"])}–{stamp(s["end"])}</span></div><h2>{html.escape(s["title"])}</h2><p class="instruction">{html.escape(s["instruction"])}</p>{review}{"".join(pictures)}<details><summary>Lời giảng gốc để đối chiếu</summary><p>{html.escape(s["source_text"])}</p></details></article>')
    css='''*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#f2f5f8;color:#17243b;font:18px/1.65 "Times New Roman",Times,serif}header{background:#102b48;color:white;padding:54px max(6vw,24px)}header .eyebrow{color:#87d5de;font-size:13px;letter-spacing:2px}h1{font-size:38px;line-height:1.25;max-width:1000px}header p{max-width:1000px;color:#d4e2ee}header .actions a{display:inline-block;margin:10px 12px 0 0;padding:10px 18px;border:1px solid #6d8baa;border-radius:6px;color:white;text-decoration:none}main{display:grid;grid-template-columns:280px minmax(0,1100px);gap:32px;margin:32px auto;padding:0 24px;max-width:1450px}nav{position:sticky;top:20px;align-self:start;max-height:94vh;overflow:auto;padding:16px;background:white;border-radius:10px}nav h3{margin-top:0}nav a{display:block;font-size:13px;padding:9px 4px;border-bottom:1px solid #eef2f5;color:#214561;text-decoration:none}nav b{color:#0d8c98;margin-right:5px}article{background:white;padding:32px;margin-bottom:26px;border-radius:12px;box-shadow:0 3px 14px #17243b08;scroll-margin-top:20px}.meta{color:#08818b;font-size:12px;font-weight:bold;letter-spacing:1px}.meta span{float:right;color:#64778b}h2{font-size:25px;line-height:1.35;margin:12px 0}.instruction{white-space:pre-line}figure{margin:22px 0}img{width:100%;height:auto;max-height:650px;object-fit:contain;border-radius:5px;border:1px solid #d4dde5}figcaption{font-size:13px;color:#61768a;margin-top:6px}.review{background:#fff4d8;border-left:3px solid #dda52a;padding:9px 12px;font-size:13px}details{font-size:13px;color:#61768a;margin-top:16px}.notice{font-size:14px;padding:15px 20px;border:1px solid #cfdee9;background:#eaf2f8;border-radius:8px;margin-bottom:24px}@media(max-width:900px){main{display:block;padding:0 14px}nav{position:static;max-height:250px;margin-bottom:20px}article{padding:20px}h1{font-size:29px}}@media print{body{background:white}header{padding:20px;color:#17243b;background:white}header p{color:#17243b}header .actions,nav,details{display:none}main{display:block;padding:0;margin:0}article{break-inside:avoid;box-shadow:none;border-radius:0;padding:12px 0}h1{font-size:25px}h2{font-size:20px}img{max-height:360px;object-fit:contain}}'''
    font_dir=Path.home()/'.local/share/fonts/video-guide-times'
    font_css=[]
    for weight,file in [(400,'Times.TTF'),(700,'Timesbd.TTF')]:
        payload=base64.b64encode((font_dir/file).read_bytes()).decode()
        font_css.append('@font-face{font-family:"Times New Roman";font-style:normal;font-weight:'+str(weight)+';src:url(data:font/ttf;base64,'+payload+') format("truetype");}')
    css=''.join(font_css)+css
    document=f'<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>{css}</style></head><body><header><div class="eyebrow">HƯỚNG DẪN CÓ HÌNH ẢNH</div><h1>{html.escape(title)}</h1><p>{html.escape(summary)}</p><p>{len(steps)} bước/mục · Video nguồn {stamp(duration)} · Ảnh trích từ video</p><div class="actions"><a href="{basename}.pdf">Mở bản PDF</a><a href="#step_001">Bắt đầu đọc</a></div></header><main><nav><h3>Mục lục</h3>{toc}</nav><section><div class="notice">Bản nháp để kiểm tra chất lượng. Mỗi bước có mốc video và lời giảng gốc; bạn có thể đối chiếu các thuật ngữ được đánh dấu.</div>{"".join(cards)}</section></main></body></html>'
    (OUT/f'{basename}.html').write_text(document,encoding='utf-8')
    md=['# '+title,'',summary,'',f'Video nguồn: {stamp(duration)}. Bản nháp cần đối chiếu.','']
    for s in steps:
        md.extend([f'## {s["number"]}. {s["title"]} [{stamp(s["start"])}–{stamp(s["end"])}]','',s['instruction'],''])
        for f in s['selected_frames']:md.extend([f'![{f["caption"]}]({f["path"]})','',f'{f["caption"]} — {stamp(f["time"])}',''])
        if s.get('terms_to_review'):md.extend(['Cần đối chiếu: '+'; '.join(s['terms_to_review']),''])
    (OUT/f'{basename}.md').write_text('\n'.join(md),encoding='utf-8')
    dump(OUT/'steps.json',doc)
    for name,file in [('TNR','Times.TTF'),('TNR-Bold','Timesbd.TTF')]:pdfmetrics.registerFont(TTFont(name,str(font_dir/file)))
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='BodyVI',fontName='TNR',fontSize=12,leading=17,textColor=colors.HexColor('#17243b'),spaceAfter=10))
    styles.add(ParagraphStyle(name='TitleVI',fontName='TNR-Bold',fontSize=23,leading=32,textColor=colors.HexColor('#102b48'),spaceAfter=18))
    styles.add(ParagraphStyle(name='StepVI',fontName='TNR-Bold',fontSize=16,leading=23,textColor=colors.HexColor('#102b48'),spaceAfter=12))
    styles.add(ParagraphStyle(name='CaptionVI',fontName='TNR',fontSize=10,leading=13,textColor=colors.HexColor('#587089'),spaceAfter=10))
    styles.add(ParagraphStyle(name='MetaVI',fontName='TNR-Bold',fontSize=9,leading=14,textColor=colors.HexColor('#078590'),spaceAfter=9))
    story=[Spacer(1,1.5*cm),Paragraph('HƯỚNG DẪN CÓ HÌNH ẢNH',styles['MetaVI']),Paragraph(html.escape(title),styles['TitleVI']),Paragraph(html.escape(summary),styles['BodyVI']),Spacer(1,0.5*cm),Paragraph(f'{len(steps)} bước/mục · Video nguồn {stamp(duration)}',styles['MetaVI']),Paragraph('Bản nháp để kiểm tra chất lượng. Nội dung được biên soạn từ lời giảng; ảnh lấy từ video. Đối chiếu thuật ngữ được đánh dấu và sử dụng mốc thời gian khi cần xem lại.',styles['BodyVI'])]
    cover=steps[min(3,len(steps)-1)]['selected_frames'][0];im=Image.open(OUT/cover['path']);w=17*cm;h=w*im.height/im.width
    story.extend([Spacer(1,0.7*cm),PDFImage(str(OUT/cover['path']),width=w,height=h),PageBreak(),Paragraph('Mục lục',styles['TitleVI'])])
    for s in steps:story.append(Paragraph(f'{s["number"]:02d}. {html.escape(s["title"])} <font color="#587089">({stamp(s["start"])})</font>',styles['BodyVI']))
    for s in steps:
        story.extend([PageBreak(),Paragraph(f'BƯỚC {s["number"]:02d} · {stamp(s["start"])}–{stamp(s["end"])}',styles['MetaVI']),Paragraph(html.escape(s['title']),styles['StepVI']),Paragraph(html.escape(s['instruction']).replace('\n','<br/>'),styles['BodyVI'])])
        if s.get('review_note'):story.append(Paragraph(html.escape(s['review_note']),styles['CaptionVI']))
        if s.get('terms_to_review'):story.append(Paragraph('Cần đối chiếu: '+html.escape('; '.join(s['terms_to_review'])),styles['CaptionVI']))
        if s.get('match_status')!='matched':story.append(Paragraph('Ảnh minh họa cần kiểm tra thêm với đoạn video gốc.',styles['CaptionVI']))
        for f in s['selected_frames']:
            im=Image.open(OUT/f['path']);w=17*cm;h=w*im.height/im.width
            # Two screenshots share a page; retain enough space for the instruction.
            max_h=(6.1 if len(s['selected_frames'])>=2 else 9.5)*cm
            if h>max_h:w=w*(max_h/h);h=max_h
            story.extend([Spacer(1,0.15*cm),PDFImage(str(OUT/f['path']),width=w,height=h),Paragraph(html.escape(f['caption'])+' · '+stamp(f['time']),styles['CaptionVI'])])
    def footer(canvas,document):
        canvas.saveState();canvas.setFont('TNR',8);canvas.setFillColor(colors.HexColor('#587089'));canvas.drawString(1.8*cm,1.05*cm,'Hướng dẫn từ video');canvas.drawRightString(19.2*cm,1.05*cm,str(document.page));canvas.restoreState()
    pdf=SimpleDocTemplate(str(OUT/f'{basename}.pdf'),pagesize=(21*cm,29.7*cm),rightMargin=2*cm,leftMargin=2*cm,topMargin=1.8*cm,bottomMargin=1.8*cm,title=title,author='Video to Guide')
    pdf.build(story,onFirstPage=footer,onLaterPages=footer)
    from pypdf import PdfReader
    reader=PdfReader(OUT/f'{basename}.pdf')
    metrics={'steps':len(steps),'selected_images':sum(len(s['selected_frames']) for s in steps),'pages':len(reader.pages),'needs_review':[s['id'] for s in steps if s['review_status']=='needs_review'],'uncovered_segment_ids':doc.get('uncovered_segment_ids',[])}
    dump(OUT/'guide_metrics.json',metrics)
    print('EXPORTED',json.dumps(metrics,ensure_ascii=False),flush=True)

if __name__=='__main__':
    started=time.monotonic()
    if (OUT/'steps.reviewed.json').exists():
        doc=json.loads((OUT/'steps.reviewed.json').read_text())
    else:
        doc=make_steps();doc=select_images(doc)
    export(doc)
    print('Finished in',round(time.monotonic()-started,1),'seconds',flush=True)
