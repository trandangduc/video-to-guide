import json, os, time, subprocess
from pathlib import Path
import av, imageio_ffmpeg, wave
import numpy as np
from faster_whisper import WhisperModel

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'B_i 7 -  Ph_n 1  Gi_i thi_u file Layout_ s_a l_i khi import netlist v_o Layout.mp4'
OUT = ROOT / 'output' / 'layout_netlist_guide'
OUT.mkdir(parents=True, exist_ok=True)
with av.open(str(SOURCE)) as c:
    meta = {'source': str(SOURCE), 'duration': c.duration / av.time_base,
            'streams': [{'type': s.type, 'codec': s.codec_context.name} for s in c.streams]}
(OUT / 'media.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
if (OUT / 'transcript.raw.json').exists():
    print('Using completed cached transcript', flush=True)
    raise SystemExit(0)
if not (OUT / 'audio.wav').exists():
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-y', '-i', str(SOURCE), '-vn', '-ac', '1', '-ar', '16000', str(OUT / 'audio.wav')], check=True)
print('Loading cached Whisper large-v3-turbo CUDA int8_float16 on GPU 0', flush=True)
started = time.monotonic()
try:
    model = WhisperModel('mobiuslabsgmbh/faster-whisper-large-v3-turbo', device='cuda', device_index=0, compute_type='int8_float16', cpu_threads=4, num_workers=1)
except RuntimeError as e:
    print('GPU initialization failed; using CPU int8:', str(e), flush=True)
    model = WhisperModel('mobiuslabsgmbh/faster-whisper-large-v3-turbo', device='cpu', compute_type='int8', cpu_threads=8)
with wave.open(str(OUT / 'audio.wav'), 'rb') as audio_file:
    audio_samples = np.frombuffer(audio_file.readframes(audio_file.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
segments, info = model.transcribe(audio_samples, language='vi', beam_size=5, vad_filter=True, word_timestamps=True,
    initial_prompt='Video hướng dẫn thiết kế mạch in bằng tiếng Việt: OrCAD Capture, Layout, netlist, footprint, PCB, import. Giữ nguyên lời nói và tên lệnh nghe được.')
result=[]
for i,s in enumerate(segments):
    row={'id': f'seg_{i+1:04d}', 'start': round(s.start,3), 'end': round(s.end,3), 'text': s.text.strip(),
         'avg_logprob': s.avg_logprob, 'no_speech_prob': s.no_speech_prob,
         'words': [{'start':round(w.start,3),'end':round(w.end,3),'word':w.word,'probability':w.probability} for w in (s.words or [])]}
    result.append(row)
    print(f'[{s.start:.1f}-{s.end:.1f}] {s.text.strip()}',flush=True)
    (OUT/'transcript.partial.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'transcript.raw.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'transcript.txt').write_text('\n'.join(f"[{r['start']:.1f}-{r['end']:.1f}] {r['text']}" for r in result),encoding='utf-8')
(OUT/'asr_metrics.json').write_text(json.dumps({'model':'large-v3-turbo','device':model.model.device,'compute_type':model.model.compute_type,'elapsed_seconds':round(time.monotonic()-started,2),'segments':len(result),'language':info.language},indent=2),encoding='utf-8')
print('DONE',len(result),'segments',round(time.monotonic()-started,1),'seconds',flush=True)
