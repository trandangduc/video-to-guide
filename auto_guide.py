"""Video -> audio transcript -> Qwen-authored illustrated guide, verified claim by claim, without editorial edits.

Nothing in this file is specific to one video or one software product: terminology is reconciled from text the
model reads on screen, and every published claim is checked against the transcript and screen evidence.
"""
import argparse,base64,copy,difflib,hashlib,io,json,math,os,re,subprocess,time,unicodedata,urllib.request,wave,threading,tempfile,functools
from concurrent.futures import ThreadPoolExecutor,as_completed
from contextlib import contextmanager
from pathlib import Path
import av,imageio_ffmpeg,numpy as np
from PIL import Image
import build_guide_local as renderer

VERSION='auto-v6-speed'
LABELS={'A':'supported','B':'contradicted','C':'insufficient','D':'overgeneralized'}

def save(path,data):
    # Unique temporary files keep concurrent writers from replacing each other's temporary file.
    path=Path(path)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,prefix=path.name+'.',suffix='.tmp',delete=False) as f:
        temporary=Path(f.name)
        try:json.dump(data,f,ensure_ascii=False,indent=2)
        except BaseException:temporary.unlink(missing_ok=True);raise
    try:temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)

def serialized_trace(method):
    @functools.wraps(method)
    def wrapped(self,name,*args,**kwargs):
        with self._trace_guard:lock=self._trace_locks.setdefault(name,threading.RLock())
        with lock:return method(self,name,*args,**kwargs)
    return wrapped

def same_screen(a,b):
    """Conservative full-resolution comparison: do not hide small local text changes.

    A few compression pixels may differ, but a changed tile rejects reuse. Compare with
    the last actually read representative, never chain increasingly different frames.
    """
    if a.size!=b.size:return False
    delta=np.abs(np.asarray(a.convert('RGB'),dtype=np.int16)-np.asarray(b.convert('RGB'),dtype=np.int16))
    changed=delta.max(axis=2)>20
    if delta.mean()>1 or changed.mean()>0.0001:return False
    for y in range(0,changed.shape[0],32):
        for x in range(0,changed.shape[1],32):
            if changed[y:y+32,x:x+32].sum()>4:return False
    return True

def digest_file(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def norm(text):
    return unicodedata.normalize('NFC',str(text)).casefold().strip()

def fold(text):
    """Rough sound key: drop diacritics and merge consonants that ASR and Vietnamese letter names confuse (b/p, d/t, g/k/c/j...)."""
    t=unicodedata.normalize('NFD',str(text).casefold().replace('đ','d'))
    t=''.join(ch for ch in t if unicodedata.category(ch)!='Mn')
    t=re.sub(r'ph','f',t)
    t=re.sub(r'[^a-z0-9]','',t)
    return t.translate(str.maketrans('bdgcjqvzxy','ptkkkkfssi'))

def stamp(t):
    t=int(t);return f'{t//60:02d}:{t%60:02d}'

def phonetic_candidates(rows,targets):
    """Pure sound matching; targets are (screen metadata, folded sound) pairs."""
    found=[]
    for r in rows:
        words=r['text'].split()
        for n in (1,2,3):
            for i in range(len(words)-n+1):
                phrase=' '.join(words[i:i+n]);key=fold(phrase)
                if len(key)<2:continue
                for t,k in targets:
                    if abs(len(k)-len(key))>2 or k[0]!=key[0]:continue
                    score=difflib.SequenceMatcher(None,k,key).ratio()
                    if score>=(1.0 if len(k)<=4 else 0.85):found.append({'asr':phrase,'screen':t['text'],'frame':t['frame'],'segment_id':r['id'],'sound_similarity':round(score,2)})
    best={}
    for c in found:
        key=(norm(c['asr']),norm(c['screen']))
        if key not in best:best[key]=dict(c,segment_ids=[c['segment_id']])
        elif c['segment_id'] not in best[key]['segment_ids'] and len(best[key]['segment_ids'])<5:best[key]['segment_ids'].append(c['segment_id'])
    result=[{k:v for k,v in c.items() if k!='segment_id'} for c in best.values()][:300]
    return result


def term_violations(text,terms,corpus):
    """Pure terminology gate over verified mappings and screen evidence."""
    found=[];low=norm(text)
    for t in terms:
        if t.get('confidence')!='high' or t.get('p_same_term',0)<0.8:continue
        asr=norm(t['asr'])
        # Same word stem on both sides (e.g. a generic 'file X' vs a specific 'name.X') is not a misuse.
        alnum=lambda x:re.sub(r'[^a-z0-9]','',norm(x))
        shares_stem=any(w[:5] in norm(t['screen']) for w in re.findall(r'[a-z0-9]{3,}',asr)) or alnum(asr)==alnum(t['screen'])
        if len(asr)>=2 and not shares_stem and re.search(r'(?<![\w.])'+re.escape(asr)+r'(?!\w)',low) and norm(t['screen']) not in asr:
            found.append({'claim':f"Dùng '{t['asr']}' trong khi màn hình cho thấy '{t['screen']}'",'label':'contradicted','p_supported':0.0,'evidence_frame_ids':t['evidence_frame_ids']})
    # Exact identifiers (file extensions, codes mixing letters and digits) must be visible somewhere in the video.
    if corpus:
        extensions=sorted(set(re.findall(r'(?<![\w])\.[a-z][a-z0-9]{1,5}(?![\w])',corpus)))
        seen=set()
        for token in re.findall(r'(?<![\w])\.[A-Za-z][A-Za-z0-9]{1,5}(?![\w])|(?<![\w.])(?=[A-Za-z0-9_-]*[A-Za-z])(?=[A-Za-z0-9_-]*[0-9])[A-Za-z0-9_-]{2,}(?![\w])|(?<![\w.])[A-Z]{2,5}(?![\w])',text):
            key=norm(token)
            present=re.search(re.escape(key)+r'(?![\w])',corpus) if token.startswith('.') else re.search(r'(?<![\w])'+re.escape(key)+r'(?![\w])',corpus)
            if key in seen or present:continue
            seen.add(key)
            hint=('; đuôi file thấy trên màn hình: '+', '.join(extensions[:20])) if token.startswith('.') and extensions else ''
            found.append({'token':token,'claim':f"'{token}' không xuất hiện trên màn hình ở bất kỳ thời điểm nào của video, chỉ có trong lời nói (có thể ASR nghe sai){hint}",'label':'insufficient','p_supported':0.0})
        # Quoted interface strings and messages (menus, dialogs, errors) must be readable on screen, not reconstructed from speech.
        for quoted in re.findall(r"['\"“‘]([A-Za-z][A-Za-z0-9 _./:>-]{3,60})['\"”’]",text):
            words=[w for w in re.findall(r'[a-z]{3,}',norm(quoted))]
            missing=[w for w in words if w not in corpus]
            if words and norm(quoted) not in corpus and norm(quoted) not in seen:
                seen.add(norm(quoted))
                found.append({'token':quoted,'claim':f"Chuỗi giao diện/thông báo '{quoted}' không thấy trên màn hình (không có nguyên cụm chữ này); chỉ có trong lời nói",'label':'insufficient','p_supported':0.0})
    return found

def text_region(image):
    """Find the largest bright connected canvas without knowing application or text."""
    small=np.asarray(image.convert('RGB').resize((160,90)))
    mask=(small.min(axis=2)>210)&((small.max(axis=2).astype(int)-small.min(axis=2))<30)
    seen=set();regions=[]
    for y,x in zip(*np.where(mask)):
        if (y,x) in seen:continue
        todo=[(int(y),int(x))];seen.add((y,x));points=[]
        while todo:
            yy,xx=todo.pop();points.append((yy,xx))
            for ny,nx in ((yy-1,xx),(yy+1,xx),(yy,xx-1),(yy,xx+1)):
                if 0<=ny<90 and 0<=nx<160 and mask[ny,nx] and (ny,nx) not in seen:
                    seen.add((ny,nx));todo.append((ny,nx))
        if len(points)>160*90*.04:
            ys,xs=zip(*points);regions.append((len(points),(min(xs),min(ys),max(xs)+1,max(ys)+1)))
    if not regions:return image.copy()
    _,(x0,y0,x1,y1)=max(regions)
    if (x1-x0)*(y1-y0)>160*90*.85:return image.copy()
    w,h=image.size
    return image.crop((max(0,int((x0-2)*w/160)),max(0,int((y0-2)*h/90)),min(w,int((x1+2)*w/160)),min(h,int((y1+2)*h/90))))

class Pipeline:
    def __init__(self,args):
        self.init_transport(args)
        self.args=args;self.video=Path(args.video).expanduser().resolve();self.out=Path(args.output).expanduser().resolve()
        self.out.mkdir(parents=True,exist_ok=True);(self.out/'traces').mkdir(exist_ok=True);(self.out/'frames').mkdir(exist_ok=True)
        if not self.video.is_file():raise ValueError('Video does not exist')
        with av.open(str(self.video)) as c:
            if not c.streams.video:raise ValueError('This pipeline requires a video stream')
            self.has_audio=bool(c.streams.audio)
            self.duration=c.duration/av.time_base
        source_hash=digest_file(self.video)
        config={'version':VERSION,'video':str(self.video),'sha256':source_hash,'api':args.base,'model':args.model,'asr_model':args.asr_model,
                'parallel':args.parallel,'api_parallel':args.api_parallel,'reuse_screens':not args.no_screen_reuse,
                'language':args.language,'asr_second_pass':args.asr_second_pass,'scene_threshold':args.scene_threshold,'max_frame_gap':args.max_frame_gap,
                'transcript_sha256':digest_file(Path(args.transcript)) if args.transcript else None}
        config_path=self.out/'config.json'
        if config_path.exists() and json.loads(config_path.read_text())!=config:
            raise ValueError('Output belongs to different input/config; choose another output directory')
        save(config_path,config);save(self.out/'media.json',{'source':str(self.video),'sha256':source_hash,'duration':self.duration})
        self.headers={'Content-Type':'application/json'}
        if os.environ.get('VIDEO_GUIDE_API_KEY'):self.headers['Authorization']='Bearer '+os.environ['VIDEO_GUIDE_API_KEY']

    def init_transport(self,args):
        self._trace_guard=threading.Lock();self._trace_locks={};self._stats_lock=threading.Lock()
        self._api_slots=threading.BoundedSemaphore(args.api_parallel)
        self.performance={'stages':{},'api':{'requests':0,'failed':0,'cache_hits':0,'service_seconds':0.0,'queue_seconds':0.0,'prompt_tokens':0,'completion_tokens':0,'cached_prompt_tokens':0,'cached_prompt_tokens_available':False},'parallel':args.parallel,'api_parallel':args.api_parallel}

    # ---------- model transport ----------
    @contextmanager
    def stage(self,name):
        started=time.monotonic()
        try:yield
        finally:
            with self._stats_lock:self.performance['stages'][name]=round(time.monotonic()-started,3)

    def cache_hit(self):
        with self._stats_lock:self.performance['api']['cache_hits']+=1

    def post(self,payload):
        queued=time.monotonic()
        with self._api_slots:
            started=time.monotonic();result=None
            try:
                request=urllib.request.Request(self.args.base.rstrip('/')+'/chat/completions',data=json.dumps(payload).encode(),headers=self.headers)
                with urllib.request.urlopen(request,timeout=600) as response:result=json.load(response)
                return result
            finally:
                with self._stats_lock:
                    stats=self.performance['api'];stats['requests']+=1;stats['failed']+=int(result is None)
                    stats['queue_seconds']+=started-queued;stats['service_seconds']+=time.monotonic()-started
                    usage=(result or {}).get('usage') or {}
                    for key in ['prompt_tokens','completion_tokens']:stats[key]+=usage.get(key,0) or 0
                    details=usage.get('prompt_tokens_details') or {}
                    if details.get('cached_tokens') is not None:
                        stats['cached_prompt_tokens_available']=True;stats['cached_prompt_tokens']+=details['cached_tokens']

    @serialized_trace
    def request(self,name,content,max_tokens=6000):
        trace_path=self.out/'traces'/(name+'.json')
        # Reuse a trace only when the prompt is identical, so resuming after a code/input change cannot mix stale answers.
        if isinstance(content,str) and self.RULES in content and self.SCHEMA in content:
            content=self.RULES+'\nSCHEMA:\n'+self.SCHEMA+'\n'+content.replace(self.RULES,'').replace(self.SCHEMA,'')
        input_sha=hashlib.sha256(json.dumps(content,ensure_ascii=False).encode()).hexdigest()
        if trace_path.exists():
            cached=json.loads(trace_path.read_text())
            if cached.get('parsed') is not None and cached.get('input_sha256')==input_sha:
                self.cache_hit();return cached['parsed']
        # JSON mode makes the server constrain decoding to valid JSON, so malformed output cannot stop the job.
        payload={'model':self.args.model,'messages':[{'role':'user','content':content}],'temperature':0.1,'max_tokens':max_tokens,
                 'response_format':{'type':'json_object'},'chat_template_kwargs':{'enable_thinking':False}}
        # Save image references rather than duplicating their base64 bytes in the trace.
        logged=copy.deepcopy(payload)
        if isinstance(logged['messages'][0]['content'],list):
            for item in logged['messages'][0]['content']:
                if item.get('type')=='image_url':
                    url=item['image_url']['url'];item['image_url']['url']='sha256:'+hashlib.sha256(url.encode()).hexdigest()
        for attempt in range(3):
            started=time.monotonic()
            try:
                result=self.post(payload)
                choice=result['choices'][0];raw=choice['message'].get('content') or ''
                save(trace_path,{'request':logged,'raw_response':result,'elapsed_seconds':round(time.monotonic()-started,2)})
                if choice.get('finish_reason')=='length':
                    payload['max_tokens']=min(18000,payload['max_tokens']*2);logged['max_tokens']=payload['max_tokens']
                    raise ValueError('Truncated response; increasing output token budget')
                fenced=re.search(r'```(?:json)?\s*(.*?)\s*```',raw,re.S)
                if fenced:raw=fenced.group(1)
                elif not raw.lstrip().startswith('{'):
                    a,b=raw.find('{'),raw.rfind('}')
                    if a>=0 and b>a:raw=raw[a:b+1]
                parsed=json.loads(raw)
                if not isinstance(parsed,dict):raise ValueError('Expected JSON object')
                save(trace_path,{'request':logged,'input_sha256':input_sha,'raw_response':result,'parsed':parsed,'elapsed_seconds':round(time.monotonic()-started,2)})
                return parsed
            except Exception as error:
                print('Request retry',name,attempt+1,type(error).__name__,str(error)[:150],flush=True)
                if attempt==2:raise
                time.sleep(2)

    def request_valid(self,name,content,max_tokens,validate):
        """Ask the model, and on schema errors ask it to repair its own JSON (traced as separate requests)."""
        result=self.request(name,content,max_tokens)
        for attempt in range(3):
            try:validate(result);return result
            except (ValueError,TypeError,KeyError,AttributeError) as error:
                if attempt==2:raise
                print('Qwen repairing schema',name,str(error)[:120],flush=True)
                text=content if isinstance(content,str) else content[0]['text']
                result=self.request(f'{name}_repair_{attempt+1}',text+'\nBẢN TRẢ VỀ CẦN SỬA SCHEMA:\n'+json.dumps(result,ensure_ascii=False)+'\nLỖI VALIDATION: '+str(error)+'\nTrả lại toàn bộ JSON đúng schema. Không tự tạo IDs, ảnh hoặc bằng chứng.',max_tokens)

    @serialized_trace
    def choose(self,name,evidence,question,options,image=None):
        """SemIf-style classification: read next-token probabilities of option letters instead of free text."""
        trace_path=self.out/'traces'/(name+'.json')
        letters=list(options)
        # Shared options first, then section evidence, and finally the changing claim/question.
        # Putting the changing claim before evidence would destroy useful per-section prefix reuse.
        user='CÁC ĐÁP ÁN:\n'+'\n'.join(f'{k}. {v}' for k,v in options.items())+'\nChỉ trả lời đúng một chữ cái: '+', '.join(letters)+'.\nBẰNG CHỨNG:\n'+evidence+'\n\nCÂU HỎI: '+question
        images=[] if image is None else image if isinstance(image,list) else [image]
        if images:user=[{'type':'image_url','image_url':{'url':u}} for u in images]+[{'type':'text','text':user}]
        payload={'model':self.args.model,'messages':[{'role':'system','content':'Bạn là bộ phân loại. Chỉ trả lời bằng một chữ cái.'},{'role':'user','content':user}],
                 'max_tokens':1,'temperature':0,'logprobs':True,'top_logprobs':20,'chat_template_kwargs':{'enable_thinking':False}}
        input_sha=hashlib.sha256(json.dumps(payload,ensure_ascii=False).encode()).hexdigest()
        if trace_path.exists():
            cached=json.loads(trace_path.read_text())
            if cached.get('input_sha256')==input_sha:
                self.cache_hit();return cached['scores']
        for attempt in range(3):
            try:result=self.post(payload);break
            except Exception as error:
                if attempt==2:raise
                print('Score retry',name,type(error).__name__,flush=True);time.sleep(2)
        top=result['choices'][0]['logprobs']['content'][0]['top_logprobs']
        mass={k:0.0 for k in letters}
        for item in top:
            token=item['token'].strip()
            if token in mass:mass[token]+=math.exp(item['logprob'])
        total=sum(mass.values())
        scores={k:(v/total if total else 1/len(letters)) for k,v in mass.items()}
        logged=copy.deepcopy(payload)
        for item in logged['messages'][1]['content'] if images else []:
            if item.get('type')=='image_url':item['image_url']['url']='sha256:'+hashlib.sha256(item['image_url']['url'].encode()).hexdigest()
        save(trace_path,{'request':logged,'input_sha256':input_sha,'scores':scores,'observed_option_mass':total})
        return scores

    # ---------- audio ----------
    def run_asr(self,hotwords=None):
        audio=self.out/'audio.wav'
        if not audio.exists():
            subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-y','-v','error','-i',str(self.video),'-vn','-ac','1','-ar','16000',str(audio)],check=True)
        with wave.open(str(audio),'rb') as f:samples=np.frombuffer(f.readframes(f.getnframes()),dtype=np.int16).astype(np.float32)/32768
        from faster_whisper import WhisperModel
        print('Transcribing',self.args.asr_model,self.args.device,'with screen hotwords' if hotwords else '',flush=True)
        model=WhisperModel(self.args.asr_model,device=self.args.device,device_index=self.args.gpu,compute_type='int8_float16' if self.args.device=='cuda' else 'int8',cpu_threads=8)
        stream,info=model.transcribe(samples,language=self.args.language,beam_size=5,vad_filter=True,word_timestamps=True,hotwords=hotwords or None)
        rows=[]
        for i,s in enumerate(stream,1):
            rows.append({'id':f'seg_{i:04d}','start':round(s.start,3),'end':round(s.end,3),'text':s.text.strip()})
            print('ASR',round(s.end,1),'/',round(self.duration,1),flush=True)
        del model
        return rows

    def set_rows(self,rows):
        if not rows:raise ValueError('No speech was transcribed')
        self.rows=rows;self.by_id={r['id']:r for r in rows};self.positions={r['id']:i for i,r in enumerate(rows)}
        if len(self.by_id)!=len(rows):raise ValueError('Duplicate transcript IDs')
        for r in rows:
            if not (0<=r['start']<r['end']<=self.duration+0.1) or not isinstance(r['text'],str):raise ValueError('Invalid transcript data')

    def transcribe(self):
        cache=self.out/'transcript.raw.json'
        if cache.exists():rows=json.loads(cache.read_text())
        elif self.args.transcript:
            source=Path(self.args.transcript).resolve();metadata=source.parent/'media.json'
            if not metadata.exists() or json.loads(metadata.read_text()).get('sha256')!=json.loads((self.out/'media.json').read_text())['sha256']:
                raise ValueError('Cached transcript is not associated with the input video')
            rows=json.loads(source.read_text());save(cache,rows)
            print('Reusing raw ASR transcript; no edited guide input',flush=True)
        elif self.has_audio:
            rows=self.run_asr();save(cache,rows)
        else:rows=[]
        # Whisper invents the same sentence repeatedly over silence or music; drop lines repeated 3+ times.
        counts={}
        for r in rows:counts[norm(r['text'])]=counts.get(norm(r['text']),0)+1
        self.speech_rows=[r for r in rows if r['text'].strip() and counts[norm(r['text'])]<3]
        if self.speech_rows:self.set_rows(self.speech_rows)

    def second_pass(self,glossary):
        """Re-run ASR biased toward verified screen terms; keep it only if it did not lose speech."""
        candidates=self.phonetic_candidates()
        if not candidates:
            save(self.out/'asr_second_pass.json',{'used':False,'reason':'no_phonetic_candidates'})
            print('Skipping second ASR: no phonetic candidates',flush=True);return False
        cache=self.out/'transcript.pass2.json'
        if not cache.exists():
            terms=[];seen=set()
            # Verified glossary terms, then on-screen terms the first pass never produced (SlideSpeech "low-recall" list).
            ordered=[t['screen'] for t in sorted(glossary,key=lambda t:-t.get('p_same_term',0))]+[c['screen'] for c in sorted(candidates,key=lambda c:-len(c['segment_ids']))]
            for t in ordered:
                if norm(t) not in seen and len(t)<=30:seen.add(norm(t));terms.append(t)
            # Long hotword lists make Whisper collapse into fragments, so only a short verified list is used.
            hotwords=' '.join(terms)[:200]
            if not hotwords:return False
            rows=self.run_asr(hotwords);save(cache,rows);save(self.out/'asr_hotwords.json',{'hotwords':hotwords})
        rows=json.loads(cache.read_text())
        words=lambda rs:sum(len(r['text'].split()) for r in rs)
        ratio=words(rows)/max(1,words(self.rows))
        save(self.out/'asr_second_pass.json',{'word_ratio_vs_first_pass':round(ratio,3),'used':ratio>=0.85})
        if ratio<0.85:
            print('Second ASR pass lost speech (word ratio',round(ratio,2),'); keeping first pass',flush=True);return False
        self.set_rows(rows);return True

    def format_rows(self,rows):
        text='\n'.join(f"{r['id']} [{r['start']:.2f}-{r['end']:.2f}] {r['text']}" for r in rows)
        if rows and not getattr(self,'screen_mode',False):
            original=[r for r in getattr(self,'speech_rows',[]) if rows[0]['start']<=r['end'] and r['start']<=rows[-1]['end']]
            if original and [(r['start'],r['end'],r['text']) for r in original]!=[(r['start'],r['end'],r['text']) for r in rows]:
                text+='\nASR LƯỢT ĐẦU CÙNG CỬA SỔ (chỉ đối chiếu chữ/nghĩa; source IDs vẫn lấy từ danh sách ở trên; không coi lượt hai luôn chính xác hơn):\n'+'\n'.join(f"[{r['start']:.2f}-{r['end']:.2f}] {r['text']}" for r in original)
        return text

    def expand_range(self,s):
        a=s['segment_start_id'];b=s['segment_end_id']
        if a not in self.positions or b not in self.positions or self.positions[a]>self.positions[b]:raise ValueError('Invalid section source range')
        return self.rows[self.positions[a]:self.positions[b]+1]

    # ---------- screen evidence ----------
    def keyframes(self):
        """Pick frames where the screen changed and then settled (dialogs, diagrams, folders), plus a max-gap fallback."""
        cache=self.out/'keyframes.json'
        if cache.exists():self.frames=json.loads(cache.read_text());return
        print('Detecting screen changes',flush=True)
        frames=[];kept=None;previous=None;last_time=-1e9;next_sample=0.0;pending=None
        def signature(frame):return np.asarray(frame.to_image().convert('L').resize((96,54)),dtype=np.int16)
        def changed(a,b):return float((np.abs(a-b)>25).mean())
        with av.open(str(self.video)) as c:
            stream=c.streams.video[0];stream.thread_type='AUTO'
            for frame in c.decode(stream):
                t=frame.time
                if t is None or t<next_sample:continue
                next_sample=t+0.5;sig=signature(frame)
                if kept is None:keep,score=True,1.0
                else:
                    score=changed(kept,sig);settled=previous is not None and changed(previous,sig)<0.004
                    pending=(pending or t) if score>=self.args.scene_threshold else None
                    keep=(pending is not None and (settled or t-pending>=3) and t-last_time>=1.5) or t-last_time>=self.args.max_frame_gap
                previous=sig
                if not keep:continue
                path=self.out/'frames'/f'k{len(frames)+1:04d}.jpg'
                image=frame.to_image();image.thumbnail((1600,1000));image.save(path,quality=92)
                frames.append({'id':f'k{len(frames)+1:04d}','time':round(t,3),'change':round(score,4),'path':str(path.relative_to(self.out)),'periodic':kept is not None and pending is None and t-last_time>=self.args.max_frame_gap})
                kept=sig;last_time=t;pending=None
        save(cache,frames);self.frames=frames
        print('Keyframes:',len(frames),flush=True)

    def read_screens(self):
        cache=self.out/'screen_text.json'
        if cache.exists():self.screen=json.loads(cache.read_text());return
        instructions='''Đọc các ảnh chụp màn hình video độc lập, chưa có transcript để tránh bị dẫn dắt bởi lỗi nhận dạng lời nói. Chép đúng chữ nhìn thấy, kể cả chữ viết tay hoặc ghi chú vẽ thêm trên màn hình, đặc biệt tên file và phần mở rộng, tên menu, tiêu đề hộp thoại, nút, trường thuộc tính, thông báo lỗi/trạng thái và số liệu trạng thái. Không đoán chữ mờ. Chỉ ghi điều nhìn thấy, không diễn giải quy trình. Mỗi ảnh tối đa 15 cụm chữ quan trọng, mỗi cụm chỉ ghi một lần; không chép watermark, chữ trang trí, toàn bộ thanh menu hay log dài. Description tối đa 2 câu.
Trả JSON {"observations":[{"frame_id":"k0001","visible_text":["chữ nguyên văn"],"technical_terms":["tên kỹ thuật đọc rõ"],"visible_errors":["nguyên văn lỗi/cảnh báo"],"description":"...","uncertain_text":["chữ chưa đọc rõ"]}]}. Có đúng một observation cho mỗi ảnh.'''
        def read(batch):
            ids={f['id'] for f in batch}
            content=[{'type':'text','text':instructions}]
            for f in batch:
                im=Image.open(self.out/f['path']);im.thumbnail((1400,900));buffer=io.BytesIO();im.save(buffer,format='JPEG',quality=88)
                content.extend([{'type':'text','text':f"Ảnh {f['id']} tại {stamp(f['time'])}"},{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(buffer.getvalue()).decode()}}])
            def validate(data):
                got={o['frame_id'] for o in data['observations']}
                if got!=ids:raise ValueError('Observations must cover exactly frames '+','.join(sorted(ids)))
                for o in data['observations']:
                    for k in ['visible_text','technical_terms','visible_errors']:
                        if not isinstance(o.get(k,[]),list):raise ValueError('Invalid '+k)
            try:data=self.request(f'screen2_{batch[0]["id"]}',content,2500);validate(data)
            except Exception:
                data={'observations':[dict(self.read_single(f,[content[0]]+content[1+2*j:3+2*j]),frame_id=f['id']) for j,f in enumerate(batch)]}
            return data['observations']
        unique=[];reused={};representative=None;previous_image=None
        for frame in self.frames:
            with Image.open(self.out/frame['path']) as source:current=source.convert('RGB')
            if not self.args.no_screen_reuse and frame.get('periodic') and previous_image is not None and same_screen(previous_image,current):
                reused[frame['id']]=representative['id']
            else:
                unique.append(frame);representative=frame;previous_image=current
        batches=[unique[i:i+2] for i in range(0,len(unique),2)]
        print('Qwen reading screen text in',len(batches),'batches',flush=True)
        with ThreadPoolExecutor(4) as pool:results=list(pool.map(read,batches))
        self.screen={o['frame_id']:o for group in results for o in group}
        by_frame={f['id']:f for f in self.frames}
        for frame_id,original in list(reused.items()):
            if self.screen[original].get('unreadable'):
                # An unreadable representative is not evidence; try this frame independently.
                self.screen[frame_id]=read([by_frame[frame_id]])[0];del reused[frame_id]
            else:
                self.screen[frame_id]=copy.deepcopy(self.screen[original]);self.screen[frame_id].update(frame_id=frame_id,reused_from=original)
        save(self.out/'screen_reuse.json',{'frames':len(self.frames),'read_frames':len(self.frames)-len(reused),'reused':reused,'policy':'full_resolution_tiles_v1'})
        save(cache,self.screen)

    def read_single(self,frame,content):
        try:
            o=self.request(f'screen_{frame["id"]}_single',content,1500)['observations'][0]
            if not isinstance(o,dict):raise ValueError('Observation must be an object')
            return o
        except Exception as error:
            # A frame the model cannot read (e.g. repetition loops) contributes no screen evidence rather than stopping the job.
            print('Screen text unavailable for',frame['id'],type(error).__name__,flush=True)
            return {'frame_id':frame['id'],'visible_text':[],'technical_terms':[],'visible_errors':[],'description':'','unreadable':True}

    def recheck_rare_text(self,read_filter=None):
        """Rarely seen strings (often handwriting or blur) that resemble a term read clearly elsewhere are re-read against the image itself."""
        cache=self.out/'screen_rechecks.json'
        policy=self.out/'screen_recheck_policy.txt'
        policy_value='reread7'+(':'+hashlib.sha256(json.dumps(sorted(read_filter)).encode()).hexdigest() if read_filter is not None else '')
        if cache.exists() and (not policy.exists() or policy.read_text()!=policy_value):
            archive=self.out/'cache_previous';archive.mkdir(exist_ok=True);cache.replace(archive/cache.name)
        if cache.exists():
            for c in json.loads(cache.read_text()):
                if c['accepted']:self.apply_reading(c)
            return
        counts={}
        for o in self.screen.values():
            for t in {norm(x) for x in o.get('visible_text',[]) if isinstance(x,str)}:counts[t]=counts.get(t,0)+1
        clear=[t for t,c in counts.items() if c>=3 and 2<=len(t)<=24]
        clear+=sorted(set(re.findall(r'(?<![\w])\.[a-z][a-z0-9]{1,5}(?![\w])',' '.join(clear+[self.frame_text(f['id']) for f in self.frames]))))
        groups={}
        for f in self.frames:
            for x in self.screen.get(f['id'],{}).get('visible_text',[]):
                if not isinstance(x,str) or not 2<=len(x)<=12:continue
                key=fold(x)
                score,best=max(((difflib.SequenceMatcher(None,key,fold(c)).ratio(),c) for c in clear if fold(c) and fold(c)[:1]==key[:1] and fold(c)!=key),default=(0,''))
                # Rare strings, or strings that look like a file extension written without its dot (typical of handwriting).
                # Never shorten identifiers or change their numeric identity; ordinary menu words are not spelling repairs.
                handwriting=best.startswith('.') and '.' not in x
                source_letters=re.sub(r'[^a-z0-9]','',norm(x));target_letters=re.sub(r'[^a-z0-9]','',norm(best))
                compatible=handwriting or (self.identifier_like(x) and self.identifier_like(best)
                    and ''.join(re.findall(r'\d',x))==''.join(re.findall(r'\d',best))
                    and not (source_letters!=target_letters and (source_letters.startswith(target_letters) or target_letters.startswith(source_letters))))
                if compatible and score>=0.75 and (counts.get(norm(x),0)<=2 or handwriting):
                    groups.setdefault((x,best),[]).append(f['id'])
        jobs=[{'frame_id':fid,'read':x,'candidate':best,'frames':ids} for (x,best),ids in groups.items() for fid in ids[:2]]
        if read_filter is not None:jobs=[j for j in jobs if j['read'] in read_filter]
        options={'A':'Cùng nhãn; cách viết chuẩn hóa được nét chữ và ngữ cảnh ảnh hỗ trợ','B':'Nhãn khác; không nên ghép','C':'Chữ quá mờ để xác nhận'}
        def check(job):
            frame=next(f for f in self.frames if f['id']==job['frame_id'])
            im=Image.open(self.out/frame['path']).convert('RGB');w,h=im.size
            region=text_region(im)
            preview=region.copy();preview.thumbnail((1000,800));buffer=io.BytesIO();preview.save(buffer,format='JPEG',quality=95)
            locator_url='data:image/jpeg;base64,'+base64.b64encode(buffer.getvalue()).decode()
            locate_prompt="Tìm vị trí cụm chữ có thể đã bị đọc thành "+repr(job['read'])+" trong ảnh. Chỉ định vị theo nét chữ, không sửa chữ. Trả JSON {\"bbox\":[x0,y0,x1,y1]} với tọa độ 0–1000 so với toàn ảnh; bbox ôm sát cụm chữ, không lấy mũi tên hoặc cụm chữ khác. Nếu không thấy thì bbox=null."
            located=self.request('locate_'+hashlib.sha256((job['frame_id']+job['read']+locator_url).encode()).hexdigest()[:16],[{'type':'image_url','image_url':{'url':locator_url}},{'type':'text','text':locate_prompt}],300)
            box=located.get('bbox');focused=region
            if isinstance(box,list) and len(box)==4 and all(isinstance(x,(int,float)) for x in box) and 0<=box[0]<box[2]<=1000 and 0<=box[1]<box[3]<=1000:
                rw,rh=region.size
                focused=region.crop((max(0,int((box[0]-20)*rw/1000)),max(0,int((box[1]-20)*rh/1000)),min(rw,int((box[2]+20)*rw/1000)),min(rh,int((box[3]+20)*rh/1000))))
                if focused.width<region.width*.8 and focused.height<region.height*.8:
                    focused=focused.resize((focused.width*3,focused.height*3))
            views=[region.copy(),focused]
            url=[]
            for i,v in enumerate(views):
                v.thumbnail((640,500) if i==0 else (900,700));buffer=io.BytesIO();v.save(buffer,format='JPEG',quality=95)
                url.append('data:image/jpeg;base64,'+base64.b64encode(buffer.getvalue()).decode())
            target=job['candidate']
            note=f" (tức đuôi file {target} được viết không có dấu chấm, có thể là chữ viết tay)" if target.startswith('.') and '.' not in job['read'] else ''
            if note:target=target[1:]
            sc=self.choose('reread6_'+hashlib.sha256(json.dumps(job).encode()).hexdigest()[:16],'Ảnh 1 là vùng chứa chữ; ảnh 2 phóng to cụm chữ cần đọc. Chỉ xét nét chữ của cụm đó, không xét chữ khác trong ảnh.',
                           f"Một nhãn từng được OCR thành '{job['read']}'; '{job['candidate']}' là chữ đọc rõ ở khung khác cùng video. Xét nét chữ và các nhãn cùng sơ đồ, đây có phải cách viết của '{target}'{note} không? Khi đọc chữ viết tay, không coi nét kéo bút cuối chữ là chữ cái độc lập nếu nó nối liền chữ trước. Không ghép chỉ vì cùng xuất hiện hoặc giống âm; phải có bằng chứng thị giác của chính nhãn này.",options,url)
            return dict(job,p=round(sc['A'],3),accepted=sc['A']>=0.6)
        print('Re-reading',len(jobs),'rare on-screen strings against their images',flush=True)
        with ThreadPoolExecutor(1) as pool:checked=list(pool.map(check,jobs))
        decisions=[]
        for key in {(c['read'],c['candidate']) for c in checked}:
            votes=[c for c in checked if (c['read'],c['candidate'])==key]
            p=sum(c['p'] for c in votes)/len(votes)
            decisions.append({'read':key[0],'candidate':key[1],'frames':votes[0]['frames'],'p':round(p,3),'accepted':p>=0.6})
        save(cache,decisions);policy.write_text(policy_value)
        for c in decisions:
            if c['accepted']:self.apply_reading(c)
        print('Re-read accepted:',[(c['read'],c['candidate']) for c in decisions if c['accepted']],flush=True)

    def apply_reading(self,c):
        for fid in c['frames']:
            o=self.screen[fid]
            o['visible_text']=[c['candidate'] if x==c['read'] else x for x in o.get('visible_text',[])]
            for key in ('technical_terms','visible_errors'):
                o[key]=[c['candidate'] if x==c['read'] else x for x in o.get(key,[])]
            if o.get('description'):o['description']=o['description'].replace(c['read'],c['candidate'])
            o.setdefault('rereads',{})[c['read']]=c['candidate']

    def screen_vocabulary(self):
        """Unique on-screen strings with the first frames that show them."""
        vocab={}
        for f in self.frames:
            o=self.screen.get(f['id'],{})
            for t in o.get('visible_text',[])+o.get('technical_terms',[])+o.get('visible_errors',[]):
                if isinstance(t,str) and t.strip():
                    entry=vocab.setdefault(norm(t),{'text':t.strip(),'frames':[]})
                    if len(entry['frames'])<3:entry['frames'].append(f['id'])
        return list(vocab.values())

    def frame_text(self,frame_id):
        o=self.screen.get(frame_id,{})
        return norm(' '.join(o.get('visible_text',[])+o.get('technical_terms',[])+o.get('visible_errors',[])+[o.get('description','')]))

    def chunk_rows(self,rows,max_chars=9000):
        """Split transcript rows into consecutive pieces small enough for one request."""
        chunk,size=[],0
        for r in rows:
            line=len(r['text'])+40
            if chunk and size+line>max_chars:yield chunk;chunk,size=[],0
            chunk.append(r);size+=line
        if chunk:yield chunk

    def relevant_terms(self,rows):
        """Glossary entries that concern these rows, so per-section prompts do not carry the whole video's glossary."""
        ids={r['id'] for r in rows};text=norm(' '.join(r['text'] for r in rows))
        pick=lambda terms:[{k:t[k] for k in ['asr','screen','evidence_frame_ids','p_same_term'] if k in t} for t in terms if ids&set(t.get('segment_ids',[])) or norm(t['asr']) in text]
        return {'verified':pick(self.glossary['terms']),'possible_check_screen_text':pick(self.glossary.get('possible',[]))}

    def screen_terms(self):
        """Short technical strings read on screen, with the first frame showing each."""
        terms={}
        for f in self.frames:
            o=self.screen.get(f['id'],{})
            for t in o.get('technical_terms',[])+[x for x in o.get('visible_text',[]) if len(x)<=24]:
                if isinstance(t,str) and 1<len(t.strip())<=40 and re.search(r'[A-Za-z]',t):terms.setdefault(norm(t),{'text':t.strip(),'frame':f['id']})
        for f in self.frames:
            for ext in re.findall(r'(?<![\w])\.[a-z][a-z0-9]{1,5}(?![\w])',self.frame_text(f['id'])):terms.setdefault(ext,{'text':ext,'frame':f['id']})
        return list(terms.values())

    def technical_set(self):
        return {norm(t) for o in self.screen.values() for t in o.get('technical_terms',[]) if isinstance(t,str)}

    @staticmethod
    def identifier_like(text):
        return bool(re.search(r'\.[A-Za-z]{2,5}\b|\d|_',text) or re.fullmatch(r'[A-Z]{2,6}',text.strip()))

    def low_recall_terms(self):
        """SlideSpeech-style biasing list: on-screen terms that the transcript never contains (likely misheard)."""
        spoken=norm(' '.join(r['text'] for r in self.rows))
        return [t for t in self.screen_terms() if norm(t['text']).strip('.') not in spoken and len(t['text'])<=24]

    def phonetic_candidates(self):
        """Transcript phrases that sound like a low-recall screen term (e.g. a Vietnamese reading of an English file extension)."""
        cache=self.out/'phonetic_candidates.json'
        signature=hashlib.sha256(json.dumps({'rows':self.rows,'screen':self.screen},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        marker=self.out/'phonetic_candidates.sha256'
        if cache.exists() and marker.exists() and marker.read_text()==signature:return json.loads(cache.read_text())
        technical=self.technical_set()
        targets=[(t,fold(t['text'])) for t in self.low_recall_terms() if self.identifier_like(t['text']) or norm(t['text']) in technical]
        targets=[(t,k) for t,k in targets if len(k)>=2]
        result=phonetic_candidates(self.rows,targets)
        save(cache,result);marker.write_text(signature);print('Phonetic candidates:',len(result),flush=True)
        return result

    def build_glossary(self,name='glossary'):
        cache=self.out/f'{name}.json'
        if cache.exists():return json.loads(cache.read_text())
        instructions='''Bạn lập bảng đối chiếu thuật ngữ giữa lời nói (transcript ASR, có thể nghe sai từ nước ngoài, tên file, phần mở rộng, tên menu) và chữ đọc được trên màn hình trong cùng khoảng thời gian của video.
Với mỗi thuật ngữ kỹ thuật mà ASR có thể đã nghe sai, tìm chữ trên màn hình tương ứng dựa trên ngữ cảnh lời nói, thời điểm và cách phát âm. Chỉ ghép khi đủ căn cứ; giữ nguyên chữ màn hình đúng như danh sách. Không dùng kiến thức ngoài để tạo thuật ngữ không xuất hiện trên màn hình. Bỏ qua các từ không phải thuật ngữ.
Trả JSON {"terms":[{"asr":"dạng xuất hiện trong transcript","screen":"chữ đúng như trên màn hình","evidence_frame_ids":["k0001"],"segment_ids":["seg_0001"],"confidence":"high|medium","reason":"vì sao ghép ngắn gọn"}]}.'''
        def window(item):
            i,rows=item;a,b=rows[0]['start']-20,rows[-1]['end']+20
            frames=[f for f in self.frames if a<=f['time']<=b]
            vocab={}
            for f in frames:
                o=self.screen.get(f['id'],{})
                for t in o.get('visible_text',[])+o.get('technical_terms',[])+o.get('visible_errors',[]):
                    if isinstance(t,str) and t.strip():vocab.setdefault(norm(t),{'text':t.strip(),'frames':[]})['frames'].append(f['id'])
            vocab=[dict(v,frames=v['frames'][:3]) for v in list(vocab.values())[:300]]
            if not vocab:return []
            ids={r['id'] for r in rows};sounds=[c for c in phonetic if ids&set(c['segment_ids'])][:40]
            prompt=instructions+'\nỨNG VIÊN DO CODE TÌM THEO PHÁT ÂM (từ trong lời nói nghe giống chữ màn hình; chỉ là gợi ý, tự kiểm tra ngữ cảnh):\n'+json.dumps(sounds,ensure_ascii=False)+'\nCHỮ TRÊN MÀN HÌNH TRONG KHOẢNG THỜI GIAN NÀY (text, frames):\n'+json.dumps(vocab,ensure_ascii=False)+'\nTHUẬT NGỮ KỸ THUẬT XUẤT HIỆN Ở THỜI ĐIỂM KHÁC CỦA VIDEO (người nói có thể nhắc trước khi chúng hiện lên):\n'+json.dumps(global_terms,ensure_ascii=False)+'\nTHỜI ĐIỂM FRAMES:\n'+json.dumps({f['id']:stamp(f['time']) for f in frames})+'\nTRANSCRIPT:\n'+self.format_rows(rows)
            try:return self.request(f'{name}_w2_{i:03d}',prompt,3000).get('terms',[])
            except Exception as error:print('Glossary window skipped',i,type(error).__name__,flush=True);return []
        global_terms=self.screen_terms()[:250];phonetic=self.phonetic_candidates()
        pieces=list(enumerate(self.chunk_rows(self.rows,6000)))
        print('Qwen matching spoken terms with screen text in',len(pieces),'windows',flush=True)
        with ThreadPoolExecutor(4) as pool:proposed=[t for group in pool.map(window,pieces) for t in group]
        accepted,rejected,seen=[],[],{}
        for t in proposed:
            ok=isinstance(t.get('asr'),str) and isinstance(t.get('screen'),str) and t['asr'].strip() and t['screen'].strip()
            ok=ok and any(norm(t['screen']) in self.frame_text(x) for x in t.get('evidence_frame_ids',[]) if x in self.screen)
            ok=ok and bool(t.get('segment_ids')) and all(x in self.by_id for x in t.get('segment_ids',[]))
            ok=ok and any(norm(t['asr']) in norm(self.by_id[x]['text']) for x in t.get('segment_ids',[]) if x in self.by_id)
            if not (ok and norm(t['asr'])!=norm(t['screen'])):rejected.append(t);continue
            key=(norm(t['asr']),norm(t['screen']))
            if key in seen:
                kept=seen[key]
                for k in ['evidence_frame_ids','segment_ids']:kept[k]=sorted(set(kept[k])|set(t.get(k,[])))
                if t.get('confidence')=='high':kept['confidence']='high'
            else:seen[key]=dict(t,segment_ids=list(t.get('segment_ids',[])));accepted.append(seen[key])
        # Second, independent gate: is the screen text really the written form of what was said, not just something nearby?
        options={'A':'Có: chữ trên màn hình chính là thứ người nói đang gọi tên trong câu đó','B':'Không: chỉ xuất hiện cùng lúc, hoặc là một đối tượng/tên khác','C':'Không đủ căn cứ'}
        note='ASR tiếng Việt thường phiên âm từ, chữ cái và đuôi file tiếng Anh theo cách đọc (một chữ cái có thể bị nghe thành chữ cái khác có âm gần giống), nên cách viết trong lời nói có thể khác xa chữ trên màn hình. Hãy xét ngữ cảnh câu nói, cách phát âm và thời điểm. '
        def gate(item):
            i,t=item
            sound=max([c['sound_similarity'] for c in phonetic if norm(c['asr'])==norm(t['asr']) and norm(c['screen'])==norm(t['screen'])] or [0])
            evidence=('ĐỘ GIỐNG PHÁT ÂM (code tính): '+str(sound)+'\n' if sound else '')+'LỜI NÓI:\n'+self.format_rows([self.by_id[x] for x in t.get('segment_ids',[])][:6])+'\nCHỮ TRÊN MÀN HÌNH CÙNG LÚC:\n'+json.dumps({x:self.screen.get(x,{}).get('visible_text',[]) for x in t['evidence_frame_ids'][:3]},ensure_ascii=False)
            key=hashlib.sha256((t['asr']+'|'+t['screen']+'|'+evidence).encode()).hexdigest()[:16]
            return self.choose(f'term_gate_{key}',evidence,note+f"Khi người nói nói '{t['asr']}', họ có đang gọi tên '{t['screen']}' trên màn hình không?",options)
        candidates=[t for t in accepted if t.get('confidence') in ('high','medium')]
        rejected+=[dict(t,rejected_by='low_confidence') for t in accepted if t not in candidates]
        with ThreadPoolExecutor(8) as pool:scores=list(pool.map(gate,enumerate(candidates)))
        accepted,possible=[],[]
        for t,sc in zip(candidates,scores):
            t['p_same_term']=round(sc['A'],3)
            if sc['A']>=0.5:accepted.append(t)
            elif sc['A']>=0.2:possible.append(t)
            else:rejected.append(dict(t,rejected_by='term_gate'))
        glossary={'terms':accepted,'possible':possible,'rejected':rejected}
        save(cache,glossary)
        print('Glossary:',len(accepted),'verified,',len(possible),'possible,',len(rejected),'rejected',flush=True)
        return glossary

    def merge_glossaries(self,first,second):
        """Keep terms verified on either pass. First-pass segment IDs do not exist in the new transcript, so those terms match by text."""
        merged={}
        for source,glossary in (('pass1',first),('pass2',second)):
            for tier in ('terms','possible'):
                for t in glossary.get(tier,[]):
                    t=dict(t,segment_ids=t.get('segment_ids',[]) if source=='pass2' else [],tier=tier)
                    key=(norm(t['asr']).strip('. ,'),norm(t['screen']))
                    if key not in merged or t.get('p_same_term',0)>merged[key].get('p_same_term',0):merged[key]=t
        terms=[t for t in merged.values() if t['tier']=='terms'];possible=[t for t in merged.values() if t['tier']=='possible']
        result={'terms':terms,'possible':possible,'rejected':second.get('rejected',[])}
        save(self.out/'glossary_merged.json',result);print('Merged glossary:',len(terms),'verified,',len(possible),'possible',flush=True)
        return result

    def window_evidence(self,start,end,pad=10):
        frames=[f for f in self.frames if start-pad<=f['time']<=end+pad]
        return [dict(frame_id=f['id'],time=stamp(f['time']),**{k:self.screen.get(f['id'],{}).get(k) for k in ['visible_text','visible_errors','description']}) for f in frames]

    # ---------- authoring ----------
    def outline(self):
        cache=self.out/'outline.json'
        def nonoverlapping(sections):
            spans=sorted((self.positions[s['segment_start_id']],self.positions[s['segment_end_id']]) for s in sections)
            return all(left[1]<right[0] for left,right in zip(spans,spans[1:]))
        if cache.exists():
            cached=json.loads(cache.read_text())
            if nonoverlapping(cached['sections']) and (not self.screen_mode or len(cached['sections'])<=max(1,math.ceil(self.duration/75))):return cached
        pieces=list(self.chunk_rows(self.rows))
        print('Qwen: building outline in',len(pieces),'transcript windows',flush=True)
        instructions='''Bạn tự biên soạn tài liệu hướng dẫn có ảnh từ lời nói của một video. Người đọc cần thực hiện được thao tác mà không phải xem lại toàn video. Đây là một đoạn liên tiếp của transcript. Chưa viết nội dung chi tiết, hãy chia đoạn này thành các mục hợp lý theo thời gian.
Bao phủ đủ kiến thức, thao tác, cách kiểm tra kết quả, cách hoàn tác/làm lại, ví dụ và chẩn đoán lỗi nếu nguồn có. Không thêm mục từ kiến thức ngoài. Không ép số mục cố định. Chỉ bỏ câu đệm, lời lặp và phần chờ/tương tác không thêm thông tin mới. Phần lý thuyết cũng là một mục. Hai thao tác được trình bày riêng trong video thì không gộp thành một.
Transcript ASR có thể sai thuật ngữ; dùng bảng đối chiếu với chữ trên màn hình bên dưới. Chọn khoảng segment liên tiếp cho từng mục; không chồng khoảng nguồn giữa các mục, mỗi segment chỉ thuộc một mục; chỉ dùng IDs trong đoạn này. Không tạo timestamps.
Trả JSON thuần {"sections":[{"title":"...","purpose":"nội dung cần được giải thích/thực hiện đầy đủ trong mục","segment_start_id":"seg_0001","segment_end_id":"seg_0010"}]}.'''
        sections=[]
        for i,rows in enumerate(pieces):
            ids={r['id'] for r in rows};context=('\nMỤC CUỐI CỦA ĐOẠN TRƯỚC (chỉ để nối mạch, không lặp lại): '+sections[-1]['title']) if sections else ''
            mode_rules=('\nĐây là video ít hoặc không lời: nhóm các quan sát liên tiếp thành giai đoạn thao tác, không tạo mục riêng cho chờ, ảnh kế tiếp hay thao tác lặp. Chỉ mô tả điều thấy; không tự tạo công dụng, thông số hoặc lý do chưa có trong ảnh.' if self.screen_mode else '')
            prompt=instructions+mode_rules+context+'\nBẢNG ĐỐI CHIẾU THUẬT NGỮ:\n'+json.dumps(self.relevant_terms(rows),ensure_ascii=False)+'\nTRANSCRIPT:\n'+self.format_rows(rows)
            def validate(plan):
                if not plan.get('sections'):raise ValueError('No sections')
                for s in plan['sections']:
                    if s.get('segment_start_id') not in ids or s.get('segment_end_id') not in ids:raise ValueError('Section IDs must stay inside this transcript window')
                    self.expand_range(s)
                if not nonoverlapping(plan['sections']):raise ValueError('Section source ranges must not overlap; partition the sequence into chronological stages')
            sections.extend(self.request_valid(f'outline_{i:03d}',prompt,4000,validate)['sections'])
        covered={r['id'] for s in sections for r in self.expand_range(s)}
        missing=[r for r in self.rows if r['id'] not in covered];exclusions=[]
        for i,rows in enumerate(self.chunk_rows(missing,6000)):
            missing_ids={r['id'] for r in rows}
            nearby=[s['title'] for s in sections if abs(self.by_id[s['segment_start_id']]['start']-rows[0]['start'])<600]
            audit_prompt='''Đây là các đoạn transcript chưa được mục lục bao phủ. Một đoạn có giá trị khi nêu kiến thức, thao tác, điều kiện chuẩn bị, cách xem trạng thái, nguyên nhân, ví dụ hoặc cách khắc phục; khi đó thêm thành mục (khoảng segment liên tiếp trong danh sách bên dưới). Chỉ loại lời đệm, lặp không thêm thông tin, chờ và trao đổi không mang nội dung bài học. Không chấp nhận lý do loại chỉ vì có câu hỏi của người nghe hoặc người nói nhắc lại bài trước.
Trả JSON {"extra_sections":[{"title":"...","purpose":"...","segment_start_id":"...","segment_end_id":"..."}],"excluded_segments":[{"id":"...","reason":"..."}]}. Phân loại toàn bộ IDs bên dưới.
TÊN CÁC MỤC GẦN ĐÓ:\n'''+json.dumps(nearby,ensure_ascii=False)+'\nĐOẠN CHƯA BAO PHỦ:\n'+self.format_rows(rows)
            def validate_audit(a):
                for s in a.get('extra_sections',[]):
                    if any(r['id'] not in missing_ids for r in self.expand_range(s)):raise ValueError('Extra section must only contain uncovered IDs')
                for e in a.get('excluded_segments',[]):
                    if e.get('id') not in missing_ids or not e.get('reason'):raise ValueError('Invalid excluded source segment')
            audit=self.request_valid(f'outline_coverage_{i:03d}',audit_prompt,4000,validate_audit)
            sections.extend(audit.get('extra_sections',[]));exclusions.extend(audit.get('excluded_segments',[]))
        sections.sort(key=lambda s:self.positions[s['segment_start_id']])
        included={r['id'] for s in sections for r in self.expand_range(s)}
        excluded={e['id'] for e in exclusions};unclassified=[r['id'] for r in self.rows if r['id'] not in included|excluded]
        if unclassified:
            # Anything the model neither covered nor excluded is kept rather than silently dropped.
            print('Attaching unclassified segments to neighbouring sections:',len(unclassified),flush=True)
            for sid in unclassified:
                pos=self.positions[sid];target=min(sections,key=lambda s:min(abs(self.positions[s['segment_start_id']]-pos),abs(self.positions[s['segment_end_id']]-pos)))
                if pos<self.positions[target['segment_start_id']]:target['segment_start_id']=sid
                elif pos>self.positions[target['segment_end_id']]:target['segment_end_id']=sid
        if self.screen_mode:
            budget=max(1,math.ceil(self.duration/75))
            if len(sections)>budget:
                original_coverage={r['id'] for section in sections for r in self.expand_range(section)}
                prompt='Gộp mục lục quan sát hình ảnh thành các giai đoạn thao tác có ý nghĩa. Không chia mục riêng cho mỗi keyframe, chờ hoặc thao tác lặp; mỗi mục gồm nhiều thao tác phục vụ cùng mục tiêu. Giữ các mốc đầu/cuối và bao phủ mọi khoảng nguồn của mục lục hiện tại, không thêm nội dung. Tối đa '+str(budget)+' mục cho '+str(round(self.duration/60,1))+' phút. Trả JSON {"sections":[{"title":"...","purpose":"...","segment_start_id":"...","segment_end_id":"..."}]}.\nMỤC LỤC HIỆN TẠI (chỉ metadata, không chứa video):\n'+json.dumps(sections,ensure_ascii=False)
                def validate_compact(d):
                    if not 1<=len(d.get('sections',[]))<=budget:raise ValueError('Keep section count within duration budget')
                    coverage={r['id'] for section in d['sections'] for r in self.expand_range(section)}
                    if not original_coverage<=coverage:raise ValueError('Preserve every covered source segment')
                    if not nonoverlapping(d['sections']):raise ValueError('Merged sections must not overlap')
                    for section in d['sections']:
                        if not section.get('title') or not section.get('purpose'):raise ValueError('title and purpose required')
                sections=self.request_valid('outline_screen_compact',prompt,3500,validate_compact)['sections']
                sections.sort(key=lambda section:self.positions[section['segment_start_id']])
        def validate_head(d):
            if not isinstance(d.get('title'),str) or not d['title'] or not isinstance(d.get('summary'),str):raise ValueError('title/summary required')
        head=self.request_valid('outline_title','Đặt tiêu đề và tóm tắt 2–3 câu cho tài liệu hướng dẫn gồm các mục sau, chỉ dựa trên danh sách. Trả JSON {"title":"...","summary":"..."}.\n'+json.dumps([{k:s[k] for k in ['title','purpose'] if k in s} for s in sections],ensure_ascii=False),800,validate_head)
        plan={'title':head['title'],'summary':head['summary'],'sections':sections,'excluded_segments':exclusions};save(cache,plan)
        print('Outline:',len(sections),'sections;',len(exclusions),'excluded segments with model explanations',flush=True)
        return plan

    def candidates_for(self,rows,limit=10):
        a=rows[0]['start']-3;b=rows[-1]['end']+3
        inside=[f for f in self.frames if a<=f['time']<=b] or sorted(self.frames,key=lambda f:abs(f['time']-(a+b)/2))[:2]
        if len(inside)>limit:
            # Keep the strongest screen changes but spread across the section.
            ranked=sorted(inside,key=lambda f:-f['change'])[:limit];inside=sorted(ranked,key=lambda f:f['time'])
        return inside

    SCHEMA='''{"title":"...","explanation":["giải thích kiến thức quan trọng"],"preconditions":["điều kiện chuẩn bị có trong nguồn"],"why":["vì sao cần làm; không lặp explanation"],"actions":[{"text":"một thao tác cụ thể","source_segment_ids":["seg_..."]}],"examples":["ví dụ từ nguồn"],"expected_result":"...","diagnostics":[{"symptom":"dấu hiệu","cause":"nguyên nhân được nguồn giải thích","check":"kiểm tra đâu","fix":"cách xử lý có trong nguồn","source_segment_ids":["seg_..."]}],"uncertain_terms":["điểm chưa chắc"],"review_note":"điểm chưa đủ nguồn xác minh, hoặc chuỗi rỗng"}'''
    RULES='''Quy tắc nguồn: chỉ dùng transcript của mục, chữ đọc trên màn hình và bảng đối chiếu thuật ngữ. Với tên kỹ thuật (tên file, phần mở rộng, menu, hộp thoại, thông báo), ưu tiên chữ nhìn thấy trên màn hình hơn từ ASR; không giải thích ý nghĩa của một từ ASR chưa được đối chiếu và không thay nó bằng một từ thông dụng có âm gần giống. Không thêm lý do, lệnh, tên thông báo lỗi hay giải pháp từ kiến thức ngoài. Không tạo quan hệ nhân quả/phụ thuộc mà nguồn không nói. Khi người nói chỉ trình bày cách làm trong ví dụ của họ, viết là cách làm trong video, không biến thành quy tắc bắt buộc chung. Không kết luận công việc đã hoàn tất khi màn hình còn trạng thái chưa xong. Khi nguồn chỉ là quan sát ảnh không có lời, không biến nhãn/vật dụng nhìn thấy thành thao tác kiểm tra hoặc đối chiếu mà ảnh không cho thấy; không suy đoán thông số, công dụng, lý do hoặc chất lượng mối nối. Giữ tên, mã và số liệu đúng như nguồn; không trộn tên của các đối tượng khác nhau. Hai thao tác được trình bày riêng thì giữ riêng. Không có bằng chứng thì ghi uncertain_terms/review_note, không tự bù. Không chèn mô tả nội bộ ASR/model vào nội dung hướng dẫn.'''

    def validate_section(self,result,allowed):
        result.setdefault('expected_result','');result.setdefault('review_note','')
        if not isinstance(result.get('title'),str) or not result['title']:raise ValueError('Invalid title')
        for key in ['explanation','preconditions','why','examples','uncertain_terms']:
            result.setdefault(key,[])
            if not isinstance(result[key],list) or any(not isinstance(x,str) for x in result[key]):raise ValueError('Invalid '+key)
        for key in ['actions','diagnostics']:
            result.setdefault(key,[])
            for item in result[key]:
                if not item.get('source_segment_ids') or any(x not in allowed for x in item['source_segment_ids']):raise ValueError(key+' has source IDs outside this section')
        if not result['actions'] and not result['explanation']:raise ValueError('Section has no content')
        for item in result['actions']:
            if not isinstance(item.get('text'),str) or not item['text']:raise ValueError('Invalid action text')
        for item in result['diagnostics']:
            if any(not isinstance(item.get(k),str) for k in ['symptom','cause','check','fix']):raise ValueError('Invalid diagnostic fields')
        if not isinstance(result['expected_result'],str) or not isinstance(result['review_note'],str):raise ValueError('Invalid expected_result/review_note')

    def author_section(self,section,number):
        rows=self.expand_range(section);allowed={r['id'] for r in rows};frames=self.candidates_for(rows);frame_ids={f['id'] for f in frames}
        evidence=[dict(frame_id=f['id'],time=stamp(f['time']),**{k:self.screen.get(f['id'],{}).get(k) for k in ['visible_text','visible_errors','description']}) for f in frames]
        prompt='''Bạn tự viết đầy đủ một mục hướng dẫn từ lời giảng gốc và chữ đọc trên các ảnh màn hình của video. Không có biên tập viên sửa lại sau khi bạn trả lời.
Mục tiêu: người mới làm được theo mà không phải xem video. Giải thích vai trò của từng thành phần, chúng liên quan thế nào, vì sao cần thao tác, dấu hiệu thành công/thất bại và cách xử lý — chỉ khi nguồn có. Tách từng thao tác thành một phần tử actions. Nêu riêng ví dụ của người nói, phân biệt với giá trị người dùng tự nhập.
'''+self.RULES+'''
Chọn 1–3 ảnh có ích nhất (ưu tiên ảnh có hộp thoại, sơ đồ, danh sách file, thông báo hoặc trạng thái liên quan); caption chỉ mô tả điều thấy trong ảnh. match_status: matched nếu ảnh minh họa đúng nội dung, partial nếu chỉ là bối cảnh.
Trả JSON thuần theo schema, thêm trường "selected_frames":[{"id":"k0001","caption":"...","match_status":"matched|partial"}]:
'''+self.SCHEMA+'''
IDs source chỉ lấy từ lời giảng của mục này. Chọn ảnh bằng IDs có trong danh sách.
BẢNG ĐỐI CHIẾU THUẬT NGỮ:\n'''+json.dumps(self.relevant_terms(rows),ensure_ascii=False)+'\nMỤC LỤC ĐỊNH HƯỚNG:\n'+json.dumps(section,ensure_ascii=False)+'\nCHỮ TRÊN ẢNH ỨNG VIÊN:\n'+json.dumps(evidence,ensure_ascii=False)+'\nLỜI GIẢNG GỐC:\n'+self.format_rows(rows)
        def validate(data):
            self.validate_section(data,allowed)
            selected=data.get('selected_frames',[])
            if not selected or len(selected)>3 or len({f['id'] for f in selected})!=len(selected):raise ValueError('Select 1-3 distinct frames')
            for f in selected:
                if f.get('id') not in frame_ids or f.get('match_status') not in ['matched','partial'] or not f.get('caption'):raise ValueError('Invalid selected frame')
        result=self.request_valid(f'section_{number:03d}',prompt,6000,validate)
        by_frame={f['id']:f for f in frames}
        result['selected_frames']=[dict(by_frame[f['id']],caption=f['caption'],match_status=f['match_status']) for f in result['selected_frames']]
        result.update(id=f'step_{number:03d}',number=number,start=rows[0]['start'],end=rows[-1]['end'],source_segment_ids=[r['id'] for r in rows],
                      source_text=' '.join(r['text'] for r in rows),candidates=frames)
        return result

    def audit_section(self,step):
        keys=['title','explanation','actions','examples','expected_result','diagnostics']
        rows=[self.by_id[x] for x in step['source_segment_ids']];allowed=set(step['source_segment_ids'])
        prompt='''Kiểm tra độ đầy đủ của một mục hướng dẫn với transcript của chính mục đó. Chỉ so nội dung, không viết lại vì văn phong.
Tìm thao tác, cách kiểm tra kết quả, giải thích và ví dụ hữu ích bị bỏ sót. Dùng bảng đối chiếu thuật ngữ; không đảo lại về từ ASR sai. Bỏ qua câu đệm, lời lặp, chờ và tương tác không chứa thông tin mới.
Trả JSON {"missing":[{"point":"ý bị thiếu, nêu rõ nội dung","source_segment_ids":["seg_..."]}]}; [] nếu không thiếu.
BẢNG ĐỐI CHIẾU THUẬT NGỮ:\n'''+json.dumps(self.relevant_terms(rows),ensure_ascii=False)+'\nMỤC:\n'+json.dumps({k:step.get(k) for k in keys},ensure_ascii=False)+'\nTRANSCRIPT CỦA MỤC:\n'+self.format_rows(rows)
        def validate(a):
            if not isinstance(a.get('missing'),list):raise ValueError('missing must be a list')
            for m in a['missing']:
                if not isinstance(m.get('point'),str) or any(x not in allowed for x in m.get('source_segment_ids',[])):raise ValueError('Invalid missing point')
        return self.request_valid(f'completeness_{step["number"]:03d}',prompt,3000,validate)['missing']
    def audit(self,doc):
        with ThreadPoolExecutor(self.args.parallel) as pool:found=list(pool.map(self.audit_section,doc['steps']))
        for step,missing in zip(doc['steps'],found):step['missing_points']=[m['point'] for m in missing]
        doc['automatic_audit']={'missing_points':sum(len(m) for m in found)}
        return doc

    def deepen(self,step,number):
        """Rewrite the section with the completeness findings, then let an independent pass ground it."""
        rows=[self.by_id[x] for x in step['source_segment_ids']];allowed=set(step['source_segment_ids'])
        evidence=self.window_evidence(step['start'],step['end'])
        sources='\nBẢNG ĐỐI CHIẾU THUẬT NGỮ:\n'+json.dumps(self.relevant_terms(rows),ensure_ascii=False)+'\nCHỮ TRÊN MÀN HÌNH TRONG KHOẢNG THỜI GIAN CỦA MỤC:\n'+json.dumps(evidence,ensure_ascii=False)+'\nTRANSCRIPT CỦA MỤC:\n'+self.format_rows(rows)
        draft={k:step.get(k) for k in ['title','explanation','preconditions','why','actions','examples','expected_result','diagnostics','uncertain_terms','review_note']}
        prompt='''Bạn hoàn thiện một mục hướng dẫn từ video cho người mới. Bản nháp có thể thiếu lý do, điều kiện, cách kiểm tra và phân biệt lỗi, hoặc sai thuật ngữ do ASR. Tự đọc nguồn và biên soạn lại, không coi câu trong bản nháp là sự thật đã xác nhận. Bổ sung các ý bị thiếu được liệt kê nếu nguồn có.
'''+self.RULES+'\nTrả JSON thuần theo schema:\n'+self.SCHEMA+'\nBẢN NHÁP:\n'+json.dumps(draft,ensure_ascii=False)+'\nÝ CÓ THỂ BỊ THIẾU:\n'+json.dumps(step.get('missing_points',[]),ensure_ascii=False)+sources
        result=self.request_valid(f'deepen_{number:03d}',prompt,6000,lambda d:self.validate_section(d,allowed))
        grounding='''Bạn kiểm định nguồn độc lập cho một mục hướng dẫn. Kiểm tra từng câu: sửa hoặc bỏ quan hệ nhân quả/phụ thuộc, quy luật tuyệt đối, tên lỗi, ví dụ, tên file hoặc lệnh không được nguồn nói/cho thấy. Một câu có source ID hợp lệ chưa có nghĩa nội dung được source đó chứng minh. Giữ các giải thích quan trọng có nguồn; không biến việc kiểm định thành tóm tắt ngắn.
'''+self.RULES+'\nTrả lại toàn bộ JSON cùng schema:\n'+self.SCHEMA+'\nBẢN NHÁP:\n'+json.dumps(result,ensure_ascii=False)+sources
        return self.request_valid(f'grounding_{number:03d}',grounding,6000,lambda d:self.validate_section(d,allowed)),sources

    # ---------- claim verification ----------
    def compose(self,s):
        parts=list(s.get('explanation',[]))
        if s.get('preconditions'):parts.append('Điều kiện chuẩn bị:\n'+'\n'.join('• '+x for x in s['preconditions']))
        if s.get('why'):parts.append('Vì sao cần làm:\n'+'\n'.join('• '+x for x in s['why']))
        if s.get('actions'):parts.append('Thao tác:\n'+'\n'.join(f"{i}. {a['text']}" for i,a in enumerate(s['actions'],1)))
        if s.get('examples'):parts.append('Ví dụ trong video:\n'+'\n'.join('• '+x for x in s['examples']))
        if s.get('diagnostics'):
            parts.append('Phân biệt lỗi và cách xử lý:\n'+'\n\n'.join('Dấu hiệu: '+x['symptom']+'\nNguyên nhân: '+x['cause']+'\nKiểm tra: '+x['check']+'\nCách xử lý: '+x['fix'] for x in s['diagnostics']))
        if s.get('expected_result'):parts.append('Kết quả cần kiểm tra: '+s['expected_result'])
        return '\n\n'.join(parts)

    def term_violations(self,text):
        """Deterministic gate: the section must not use an ASR form the glossary showed is wrong on screen."""
        return term_violations(text,self.glossary['terms'],self.screen_corpus())

    def screen_corpus(self):
        if not hasattr(self,'_corpus'):
            self._corpus=norm(' '.join(x for f in self.frames for k in ('visible_text','technical_terms','visible_errors') for x in self.screen.get(f['id'],{}).get(k,[]) if isinstance(x,str)))
        return self._corpus

    def public_text(self,step):
        return '\n'.join([step['title'],self.compose(step)]+[f['caption'] for f in step.get('selected_frames',[])])

    def lexical_grounding(self,text,evidence,name):
        """The model checks semantic expansions separately from broad claim entailment."""
        prompt="""Rà riêng lỗi diễn giải từ ngữ trong bản hướng dẫn với nguồn bên dưới. Transcript là ASR có thể sai. Đừng chấm cả câu bằng mức "đúng ý chung".
Tìm cụm danh từ, tên đối tượng hoặc mô tả công dụng trong BẢN HƯỚNG DẪN mà nguồn không xác nhận đúng nghĩa ấy: đặc biệt từ nghe không rõ đã bị đổi thành từ thông dụng gần âm hoặc tự dịch/giải nghĩa. Một từ có âm gần giống không chứng minh nghĩa. Chữ màn hình và bảng đối chiếu xác nhận tên, nhưng không tự chứng minh công dụng. Với tên chưa rõ, mô tả trung tính hoặc bỏ tên thay vì sáng tạo một nghĩa dễ hiểu.
Chỉ báo lỗi có thật; câu mô tả thông thường được nguồn hỗ trợ thì giữ. Trả JSON {"unsupported":[{"phrase":"cụm nguyên văn cần bỏ/sửa trong bản hướng dẫn","source_phrase":"cụm nguyên văn trong transcript gây nhầm, hoặc chuỗi rỗng","reason":"nghĩa nào đã bị thêm mà nguồn không xác nhận"}]}.
BẢN HƯỚNG DẪN:
"""+text+'\nNGUỒN:\n'+evidence
        def validate(d):
            if not isinstance(d.get('unsupported'),list):raise ValueError('unsupported must be a list')
            for item in d['unsupported']:
                if not isinstance(item.get('phrase'),str) or not item['phrase'].strip() or norm(item['phrase']) not in norm(text) or not isinstance(item.get('reason'),str):raise ValueError('Quote an exact phrase from the draft and explain unsupported meaning')
        findings=self.request_valid(name,prompt,1600,validate)['unsupported']
        flags=[{'token':f['phrase'],'claim':f['phrase']+": "+f['reason'],'label':'insufficient','p_supported':0.0,'origin':'lexical_grounding'} for f in findings]
        if not getattr(self,'screen_mode',False):
            extraction='Liệt kê tất cả các cụm danh từ gọi tên loại đối tượng, file, bộ phận hoặc chức năng trong văn bản dưới đây. Giữ cả từ chỉ loại/công dụng/tính chất trong cụm, chép nguyên văn, không rút thành danh từ chung, không diễn giải. Bỏ câu đầy đủ, số thứ tự và cụm trùng. Trả JSON {"phrases":["cụm nguyên văn"]}.\n'+text
            def validate_phrases(d):
                if not isinstance(d.get('phrases'),list) or any(not isinstance(x,str) for x in d['phrases']):raise ValueError('phrases must be strings')
            phrases=list({norm(x):x for x in self.request_valid(name+'_nouns',extraction,1600,validate_phrases)['phrases'] if x.strip() and norm(x) in norm(text)}.values())
            options={'A':'Xác nhận đúng nghĩa/cách gọi trong hướng dẫn','B':'Chỉ có âm nghe gần giống; có thể là tên kỹ thuật ASR nghe sai','C':'Không có nguồn xác nhận nghĩa/cách gọi này'}
            question='Nguồn có xác nhận ĐÚNG NGHĨA của cách gọi sau trong hướng dẫn không? Cụm danh từ gồm cả từ chỉ loại/công dụng. Không tính một từ ASR gần âm nhưng chưa rõ nghĩa là bằng chứng cho nghĩa của từ thông dụng. Nguồn phải nói rõ ý nghĩa này hoặc nhìn thấy nguyên nhãn đó.\nCỤM DANH TỪ: '
            with ThreadPoolExecutor(8) as pool:
                scores=list(pool.map(lambda phrase:self.choose('lexeme_'+hashlib.sha256((evidence+phrase).encode()).hexdigest()[:16],evidence,question+repr(phrase),options),phrases))
            for phrase,score in zip(phrases,scores):
                if score['A']<.5 and not any(norm(f['token'])==norm(phrase) for f in flags):
                    flags.append({'token':phrase,'claim':phrase+': nguồn không xác nhận đúng nghĩa/cách gọi này; có thể là diễn giải từ ASR gần âm','label':'insufficient','p_supported':round(score['A'],3),'origin':'lexical_meaning'})
        return flags

    def verify(self,step,number,round_):
        text=self.public_text(step)
        evidence=json.dumps({'transcript':self.format_rows([self.by_id[x] for x in step['source_segment_ids']]),
                             'screen':self.window_evidence(step['start'],step['end']),'glossary':self.relevant_terms([self.by_id[x] for x in step['source_segment_ids']])},ensure_ascii=False)
        prompt='''Tách nội dung hướng dẫn dưới đây thành các khẳng định ngắn, mỗi khẳng định chỉ một ý. Mỗi khẳng định phải tự đứng được khi đọc riêng: thay đại từ và cách gọi tắt bằng chủ thể đầy đủ, giữ nguyên tên kỹ thuật, số liệu và điều kiện như văn bản (không bỏ "trong video", "ví dụ"). Không đánh giá đúng sai.
kind: action (thao tác), name (tên/đuôi file, menu, thông báo, mã), fact (mô tả), cause (nguyên nhân/quan hệ phụ thuộc), rule (quy tắc, điều kiện bắt buộc, dấu hiệu chung như "nếu X thì Y"), result (kết quả).
Trả JSON {"claims":[{"text":"...","kind":"action|name|fact|cause|rule|result"}]}.
TIÊU ĐỀ MỤC: '''+step['title']+'\nNỘI DUNG:\n'+text
        def validate(d):
            if not d.get('claims'):raise ValueError('No claims')
            for c in d['claims']:
                if not isinstance(c,dict) or not isinstance(c.get('text'),str) or not c['text'].strip():raise ValueError('Each claim needs text')
        items=self.request_valid(f'claims_{number:03d}_r{round_}',prompt,5000,validate)['claims']
        claims=[c['text'] for c in items];kinds=[c.get('kind','fact') for c in items]
        options={'A':'Được nguồn hỗ trợ trực tiếp (lời nói hoặc chữ/ảnh trên màn hình)','B':'Mâu thuẫn với nguồn, ví dụ sai tên/đuôi file/menu/số liệu so với màn hình hoặc lời nói',
                 'C':'Nguồn không đủ để xác nhận (suy diễn hoặc kiến thức ngoài)','D':'Nguồn chỉ nói về cách làm trong video nhưng khẳng định viết thành quy tắc chung/tuyệt đối'}
        question='Lưu ý ASR có thể nghe sai thuật ngữ. Với tên kỹ thuật (tên file, đuôi file, menu, mã linh kiện), chữ trên màn hình và bảng đối chiếu là bằng chứng; một tên chỉ có trong lời nói trong khi màn hình cho thấy tên khác thì KHÔNG được tính là được hỗ trợ. Khẳng định sau thuộc loại nào?\nKHẲNG ĐỊNH: '
        with ThreadPoolExecutor(8) as pool:
            scores=list(pool.map(lambda c:self.choose('verify_'+hashlib.sha256((evidence+c).encode()).hexdigest()[:16],evidence,question+c,options),claims))
        results=[{'claim':c,'kind':k,'label':LABELS[max(s,key=s.get)],'p_supported':round(s['A'],3),'scores':{LABELS[x]:round(v,3) for x,v in s.items()}} for c,k,s in zip(claims,kinds,scores)]
        # Rules and causes get a second question: does the source state it generally, or only show it in this video's situation?
        scope_options={'A':'Không: khẳng định nói đúng mức nguồn cho thấy (kể cả điều kiện, mục đích hay cách làm của bài hướng dẫn này)','B':'Có: khẳng định biến một quan sát hoặc ví dụ trong video thành quy luật tuyệt đối/chung (luôn luôn, mọi trường hợp, bắt buộc, chỉ khi, nguyên nhân duy nhất) mà nguồn không nói','C':'Nguồn không nói điều này'}
        scope_q='Khẳng định sau có tuyệt đối hóa vượt quá điều nguồn cho thấy không?\nKHẲNG ĐỊNH: '
        scoped=[r for r in results if r['kind'] in ('rule','cause') and r['label']=='supported']
        with ThreadPoolExecutor(8) as pool:
            scope_scores=list(pool.map(lambda r:self.choose('scope2_'+hashlib.sha256((evidence+r['claim']).encode()).hexdigest()[:16],evidence,scope_q+r['claim'],scope_options),scoped))
        limited=re.compile(r'trong (video|ví dụ|bài|tình huống)|người (nói|giảng)|theo (video|lời)',re.I)
        for r,sc in zip(scoped,scope_scores):
            r['scope']={'within_source':round(sc['A'],3),'absolutized':round(sc['B'],3),'unsupported':round(sc['C'],3)}
            if sc['C']>max(sc['A'],sc['B']):r['label']='insufficient'
            elif sc['B']>sc['A'] and not limited.search(r['claim']):r['label']='overgeneralized'
        flagged=[r for r in results if r['label']!='supported' or r['p_supported']<0.5]+self.term_violations(text)+self.lexical_grounding(text,evidence,f'lexical_{number:03d}_r{round_}')
        return results,flagged,evidence

    def revise(self,step,number,flagged,sources,round_):
        allowed=set(step['source_segment_ids'])
        draft={k:step.get(k) for k in ['title','explanation','preconditions','why','actions','examples','expected_result','diagnostics','uncertain_terms','review_note']}
        screen_refs=''
        if any(f.get('token','').startswith('.') for f in flagged):
            # Show where the real on-screen file names appear anywhere in the video, so the model can map the misheard name.
            refs=[]
            for f in self.frames:
                hits=[t for t in self.screen.get(f['id'],{}).get('visible_text',[]) if re.search(r'\.[A-Za-z][A-Za-z0-9]{1,5}\b',t)]
                if hits:refs.append({'frame_id':f['id'],'time':stamp(f['time']),'file_names':hits[:8],'description':self.screen.get(f['id'],{}).get('description','')})
            screen_refs='\nTÊN FILE THẤY TRÊN MÀN HÌNH Ở CÁC THỜI ĐIỂM KHÁC CỦA VIDEO:\n'+json.dumps(refs[:25],ensure_ascii=False)
        # A misheard name is removed rather than replaced by a guessed screen name: guessing could introduce a new error.
        directives=[f"Bỏ '{f['token']}' khỏi nội dung (không có trên màn hình); chỉ dùng tên khác khi lời nói và chữ trên màn hình cùng chỉ rõ đối tượng đó; ghi điểm cần xác minh vào review_note." for f in flagged if f.get('token')]
        if directives:screen_refs+='\nCHỈ DẪN BẮT BUỘC TỪ ĐỐI CHIẾU MÀN HÌNH:\n'+'\n'.join(directives)
        prompt='''Một bộ kiểm định độc lập đã đánh dấu các khẳng định dưới đây trong mục hướng dẫn: contradicted = mâu thuẫn nguồn, insufficient = chưa đủ nguồn, overgeneralized = viết thành quy tắc chung khi nguồn chỉ là cách làm trong video. Sửa mục: đổi khẳng định mâu thuẫn theo đúng nguồn (tên kỹ thuật theo chữ trên màn hình); bỏ hoặc làm mềm khẳng định chưa đủ nguồn và ghi vào review_note nếu quan trọng; viết lại khẳng định quá tổng quát thành cách làm trong video. Tên/đuôi file hoặc mã bị đánh dấu là không xuất hiện trên màn hình thì KHÔNG được giữ lại trong nội dung, kể cả khi thêm "theo lời trình bày": nếu ngữ cảnh lời nói khớp với một tên thấy trên màn hình thì dùng tên đó; nếu không chắc thì mô tả không kèm tên cụ thể và ghi điểm cần xác minh vào review_note. Không xóa nội dung được nguồn hỗ trợ.
'''+self.RULES+'\nTrả lại toàn bộ JSON cùng schema:\n'+self.SCHEMA+'\nKHẲNG ĐỊNH BỊ ĐÁNH DẤU:\n'+json.dumps([{k:f[k] for k in ['claim','label']} for f in flagged],ensure_ascii=False)+'\nMỤC HIỆN TẠI:\n'+json.dumps(draft,ensure_ascii=False)+sources+screen_refs
        return self.request_valid(f'revise_{number:03d}_r{round_}',prompt,6000,lambda d:self.validate_section(d,allowed))

    def scrub(self,step,number,tokens,attempt=1):
        """Sentence-level repair: rewrite only the sentences that still carry names that are not on screen."""
        def places():
            for key in ['explanation','preconditions','why','examples','uncertain_terms']:
                for i,x in enumerate(step.get(key,[])):yield (key,i,None),x
            for i,a in enumerate(step.get('actions',[])):yield ('actions',i,'text'),a['text']
            for i,d in enumerate(step.get('diagnostics',[])):
                for k in ['symptom','cause','check','fix']:yield ('diagnostics',i,k),d[k]
            yield ('expected_result',None,None),step.get('expected_result','')
            yield ('title',None,None),step['title']
            for i,f in enumerate(step.get('selected_frames',[])):yield ('selected_frames',i,'caption'),f['caption']
        low=[norm(t) for t in tokens]
        targets=[(where,text) for where,text in places() if where[0]!='uncertain_terms' and any(t in norm(text) for t in low)]
        if not targets:return
        prompt='''Viết lại từng câu dưới đây để bỏ các tên/cụm từ sau, vì cách gọi hoặc ý nghĩa của chúng chưa được nguồn xác nhận (có thể do diễn giải lỗi ASR): '''+json.dumps(tokens,ensure_ascii=False)+'''.
Không nhắc lại tên đó trong ngoặc hay dưới dạng "người nói gọi là". Nếu lời nói và chữ trên màn hình cùng chỉ rõ đối tượng thì dùng tên trên màn hình; nếu không thì mô tả đối tượng không kèm tên. Giữ nguyên các ý khác của câu. Không thêm thông tin mới.
Trả JSON {"rewrites":[{"id":0,"text":"câu đã viết lại"}]} với đủ mọi id.
CÁC CÂU:\n'''+json.dumps([{'id':i,'text':t} for i,(_,t) in enumerate(targets)],ensure_ascii=False)+'\nCHỮ TRÊN MÀN HÌNH QUANH MỤC:\n'+json.dumps(self.window_evidence(step['start'],step['end']),ensure_ascii=False)[:8000]+'\nTRANSCRIPT VÀ ĐỐI CHIẾU:\n'+self.format_rows([self.by_id[x] for x in step['source_segment_ids']])+'\n'+json.dumps(self.relevant_terms([self.by_id[x] for x in step['source_segment_ids']]),ensure_ascii=False)
        def validate(d):
            if {r.get('id') for r in d.get('rewrites',[])}!=set(range(len(targets))) or any(not isinstance(r.get('text'),str) for r in d['rewrites']):raise ValueError('Rewrite every id with text')
        result=self.request_valid(f'scrub_{number:03d}_{attempt}',prompt,4000,validate)
        for r in result['rewrites']:
            (key,i,field),_=targets[r['id']]
            if i is None:step[key]=r['text']
            elif field is None:step[key][i]=r['text']
            else:step[key][i][field]=r['text']

    def finalize_section(self,step,number):
        fields=['title','explanation','preconditions','why','actions','examples','expected_result','diagnostics','uncertain_terms','review_note']
        result,sources=self.deepen(step,number);step.update({k:result[k] for k in fields})
        history=[]
        for round_ in range(1,self.args.verify_rounds+2):
            results,flagged,_=self.verify(step,number,round_)
            history.append({'round':round_,'claims':len(results),'flagged':len(flagged)})
            if not flagged or round_>self.args.verify_rounds:break
            revised=self.revise(step,number,flagged,sources,round_);step.update({k:revised[k] for k in fields})
        for attempt in range(1,4):
            tokens=[f['token'] for f in flagged if f.get('token')]
            if not tokens:break
            self.scrub(step,number,tokens,attempt)
            results,flagged,_=self.verify(step,number,f'scrub{attempt}')
            history.append({'round':f'scrub{attempt}','flagged':len(flagged)})
        step['verification']={'claims':results,'unresolved':flagged,'history':history}
        return step

    def process_sections(self,plan,doc):
        # All shared evidence is immutable before workers start. Only the coordinator writes checkpoints.
        self.screen_corpus()
        def work(item):
            number,section=item
            print('Qwen processing section',number,'/',len(plan['sections']),section['title'],flush=True)
            with self.stage(f'section_{number:03d}'):
                step=self.author_section(section,number)
                missing=self.audit_section(step);step['missing_points']=[m['point'] for m in missing]
                return self.finalize_section(step,number)
        completed={};errors=[]
        with ThreadPoolExecutor(self.args.parallel) as pool:
            futures={pool.submit(work,item):item[0] for item in enumerate(plan['sections'],1)}
            for future in as_completed(futures):
                if future.cancelled():continue
                number=futures[future]
                try:completed[number]=future.result()
                except Exception as error:
                    errors.append((number,error))
                    for pending in futures:pending.cancel()
                doc['steps']=[completed[n] for n in sorted(completed)]
                doc['processing']={'completed_sections':sorted(completed),'total_sections':len(plan['sections']),
                                   'failed_sections':[n for n,_ in errors]}
                save(self.out/'document.partial.json',doc)
                print('Sections completed:',len(completed),'/',len(plan['sections']),flush=True)
        if errors:raise RuntimeError('Section '+str(errors[0][0])+' failed: '+str(errors[0][1])) from errors[0][1]
        doc['automatic_audit']={'missing_points':sum(len(s['missing_points']) for s in doc['steps'])}
        return doc

    def summarize(self,doc):
        """Write the title and summary from the verified sections, and hold them to the same screen gates."""
        brief=[{'title':s['title'],'explanation':s.get('explanation',[])[:3],'expected_result':s.get('expected_result','')} for s in doc['steps']]
        prompt='Đặt tiêu đề và tóm tắt 2–3 câu cho tài liệu hướng dẫn, chỉ dựa trên nội dung đã kiểm định bên dưới; không thêm tên lỗi, menu hay tên file không có trong nội dung. Trả JSON {"title":"...","summary":"..."}.\n'+json.dumps(brief,ensure_ascii=False)
        def validate(d):
            if not isinstance(d.get('title'),str) or not d['title'] or not isinstance(d.get('summary'),str):raise ValueError('title/summary required')
        head=self.request_valid('summary_final',prompt,800,validate)
        for attempt in range(1,3):
            problems=self.term_violations(head['title']+'\n'+head['summary'])
            if not problems:break
            head=self.request_valid(f'summary_final_fix_{attempt}',prompt+'\nBẢN TRƯỚC:\n'+json.dumps(head,ensure_ascii=False)+'\nBỎ CÁC TÊN SAU vì không có trên màn hình:\n'+'\n'.join(p['claim'] for p in problems),800,validate)
        doc['title'],doc['summary']=head['title'],head['summary']

    # ---------- output ----------
    def render(self,doc):
        for s in doc['steps']:
            s['instruction']=self.compose(s);s['terms_to_review']=s.get('uncertain_terms',[])
            unresolved=s['verification']['unresolved']
            if unresolved:
                note='Khẳng định chưa được nguồn xác nhận: '+'; '.join(f"{u['claim']} ({u['label']})" for u in unresolved)
                s['review_note']=(s.get('review_note','')+'\n'+note).strip()
            s['match_status']='matched' if all(f['match_status']=='matched' for f in s['selected_frames']) else 'partial'
            s['review_status']='needs_review' if unresolved or s.get('terms_to_review') or s['match_status']!='matched' else 'verified'
        renderer.OUT=self.out;renderer.SOURCE=self.video
        renderer.export(doc,basename='guide-auto')
        claims=[c for s in doc['steps'] for c in s['verification']['claims']]
        stats={'pipeline_version':VERSION,'content_author':self.args.model,'human_editorial_changes':0,'sections':len(doc['steps']),
               'keyframes':len(self.frames),'glossary_terms':len(self.glossary['terms']),
               'actions':sum(len(s.get('actions',[])) for s in doc['steps']),'instruction_words':sum(len(s['instruction'].split()) for s in doc['steps']),
               'diagnostic_cases':sum(len(s.get('diagnostics',[])) for s in doc['steps']),
               'claims':len(claims),'claim_labels':{v:sum(c['label']==v for c in claims) for v in LABELS.values()},
               'unresolved_claims':sum(len(s['verification']['unresolved']) for s in doc['steps']),
               'needs_review':[s['id'] for s in doc['steps'] if s['review_status']=='needs_review']}
        save(self.out/'automation_metrics.json',stats);print('AUTOMATION_RESULT',json.dumps(stats,ensure_ascii=False),flush=True)

    def invalidate_evidence_caches(self):
        """Derived artifacts must follow the current screen readings; keep independent ASR/frame caches."""
        signature=hashlib.sha256(json.dumps(self.screen,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        marker=self.out/'screen_evidence.sha256'
        if not marker.exists() or marker.read_text()!=signature:
            archive=self.out/'cache_previous';archive.mkdir(exist_ok=True)
            for path in list(self.out.glob('glossary*.json'))+[self.out/'phonetic_candidates.json',self.out/'outline.json']:
                if path.exists():path.replace(archive/path.name)
            marker.write_text(signature)
        if hasattr(self,'_corpus'):del self._corpus

    def prepare_screens(self):
        with self.stage('keyframes'):self.keyframes()
        with self.stage('read_screens'):self.read_screens()
        with self.stage('recheck_rare_text'):self.recheck_rare_text()

    def prepare_asr(self):
        with self.stage('asr_first_pass'):self.transcribe()

    def run(self):
        started=time.monotonic();self.performance['status']='running'
        try:
            self.run_pipeline();self.performance['status']='completed'
        except BaseException as error:
            self.performance.update(status='failed',error=type(error).__name__+': '+str(error));raise
        finally:
            self.performance['wall_seconds']=round(time.monotonic()-started,3)
            save(self.out/'performance.json',self.performance)

    def run_pipeline(self):
        with self.stage('prepare_sources'):
            with ThreadPoolExecutor(2) as pool:
                asr=pool.submit(self.prepare_asr);screens=pool.submit(self.prepare_screens)
                asr.result();screens.result()
        self.invalidate_evidence_caches()
        words=sum(len(r['text'].split()) for r in self.speech_rows)
        self.screen_mode=words/max(1,self.duration/60)<15
        if self.screen_mode:
            print('Little or no narration (',words,'words ); using screen content as the source',flush=True)
            # Bundle consecutive observations into 45-second sources; frames remain individually available for illustrations.
            rows=[];groups=[]
            for frame in self.frames:
                if not groups or frame['time']-groups[-1][0]['time']>=45:groups.append([])
                groups[-1].append(frame)
            for i,group in enumerate(groups):
                observations=[]
                for f in group:
                    o=self.screen.get(f['id'],{})
                    text=(o.get('description') or '')+(' Chữ: '+'; '.join(o.get('visible_text',[])[:15]) if o.get('visible_text') else '')
                    if text and not any(difflib.SequenceMatcher(None,norm(text),norm(old)).ratio()>=.9 for old in observations):observations.append(text)
                start=group[0]['time'];end=groups[i+1][0]['time'] if i+1<len(groups) else self.duration
                if start<end:rows.append({'id':f'scr_{i+1:04d}','start':start,'end':end,'text':'[Quan sát hình ảnh] '+' | '.join(observations),'frame_ids':[f['id'] for f in group]})
            save(self.out/'transcript.screen.json',rows);self.set_rows(rows)
            self.glossary={'terms':[],'possible':[],'rejected':[]}
        else:
            with self.stage('glossary_first_pass'):self.glossary=self.build_glossary()
        if self.args.asr_second_pass and not self.screen_mode:
            with self.stage('asr_second_pass_and_glossary'):
                if self.second_pass(self.glossary['terms']):self.glossary=self.merge_glossaries(self.glossary,self.build_glossary('glossary_pass2'))
        with self.stage('outline'):plan=self.outline()
        doc={'title':plan['title'],'summary':plan['summary'],'steps':[],'excluded_segments':plan.get('excluded_segments',[]),'glossary':self.glossary}
        with self.stage('sections'):doc=self.process_sections(plan,doc)
        with self.stage('summary'):self.summarize(doc)
        doc['review']={'author':self.args.model,'human_editorial_changes':0,'source_mode':'screen_only' if self.screen_mode else 'narration_and_screen',
                       'source_policy':'transcript_screen_text_and_screen_verified_glossary'}
        save(self.out/'document.auto.json',doc)
        with self.stage('render'):self.render(doc)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--video',required=True);p.add_argument('--output',required=True);p.add_argument('--base',default='http://127.0.0.1:8000/v1');p.add_argument('--model',default='qwen38')
    p.add_argument('--transcript',help='Optional raw transcript cache from a job on the same video (checked by hash)')
    p.add_argument('--asr-model',default='mobiuslabsgmbh/faster-whisper-large-v3-turbo');p.add_argument('--device',choices=['cuda','cpu'],default='cuda');p.add_argument('--gpu',type=int,default=0)
    p.add_argument('--language',default=None,help='ASR language code, e.g. vi or en; omit to auto-detect')
    p.add_argument('--asr-second-pass',action='store_true',help='Re-transcribe with hotwords read from the screen')
    p.add_argument('--scene-threshold',type=float,default=0.02,help='Fraction of changed pixels that marks a new screen')
    p.add_argument('--max-frame-gap',type=float,default=20,help='Seconds; take a frame at least this often')
    p.add_argument('--verify-rounds',type=int,default=2,help='Revision rounds after claim verification')
    p.add_argument('--parallel',type=int,default=3,help='Concurrent section workflows (default: 3)')
    p.add_argument('--api-parallel',type=int,default=4,help='Maximum in-flight Qwen requests across all workers (default: 4)')
    p.add_argument('--no-screen-reuse',action='store_true',help='Read every keyframe; disable conservative reuse of periodic duplicates')
    args=p.parse_args()
    if args.parallel<1 or args.api_parallel<1:p.error('Concurrency limits must be positive')
    Pipeline(args).run()
