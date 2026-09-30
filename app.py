import base64
import html
import json
import os
import queue
import shutil
import subprocess
import threading
import time
import urllib.request
import urllib.error
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


def api(base, path, payload=None, key=''):
    headers = {'Content-Type': 'application/json'}
    if key:
        headers['Authorization'] = 'Bearer ' + key
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(base.rstrip('/') + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=300) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode('utf-8', errors='replace')[:1800]
        raise RuntimeError(f'API HTTP {error.code}: {detail}') from error


def command(args):
    result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace',
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError(result.stderr[-2500:])
    return result.stdout


def stamp(seconds):
    seconds = int(seconds)
    return f'{seconds//3600:02d}:{seconds//60%60:02d}:{seconds%60:02d}'


def generate(config, log):
    video = Path(config['video'])
    if not video.is_file():
        raise ValueError('Hãy chọn một file video tồn tại.')
    for executable in ('ffmpeg', 'ffprobe'):
        if not shutil.which(executable):
            raise RuntimeError(f'Chưa có {executable} trong PATH. Cài FFmpeg rồi mở lại tool.')
    start, length, interval = (float(config[k]) for k in ('start', 'length', 'interval'))
    if start < 0 or length <= 0 or interval < 1:
        raise ValueError('Bắt đầu phải >= 0, độ dài > 0 và khoảng lấy hình >= 1 giây.')
    duration = float(command(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                              '-of', 'default=noprint_wrappers=1:nokey=1', str(video)]))
    if start >= duration:
        raise ValueError('Thời điểm bắt đầu nằm ngoài video.')
    end = min(start + length, duration)
    log('Kiểm tra kết nối Qwen...')
    models = api(config['base'], '/models', key=config['key'])
    if config['model'] not in [m['id'] for m in models['data']]:
        raise ValueError('Không tìm thấy model đã nhập trên server.')
    out = Path(__file__).parent / 'output' / (time.strftime('%Y%m%d_%H%M%S') + '_' + str(time.time_ns())[-6:])
    out.mkdir(parents=True)
    segments = []
    if config['asr']:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise RuntimeError('Chưa cài Whisper. Chạy install_audio.cmd hoặc bỏ chọn chép lời.')
        log('Tách audio...')
        audio = out / 'audio.wav'
        command(['ffmpeg', '-y', '-v', 'error', '-ss', str(start), '-i', str(video),
                 '-t', str(end-start), '-vn', '-ac', '1', '-ar', '16000', str(audio)])
        log('Chép lời Whisper trên CPU (lần đầu sẽ tải model từ Internet)...')
        whisper = WhisperModel(config['whisper'], device='cpu', compute_type='int8')
        language = config['language'].strip() or None
        stream, _ = whisper.transcribe(str(audio), language=language, vad_filter=True)
        for seg in stream:
            segments.append({'start': start+seg.start, 'end': start+seg.end, 'text': seg.text.strip()})
            log(f'Chép lời đến {stamp(start+seg.end)}: {seg.text.strip()}')
        (out / 'transcript.json').write_text(json.dumps(segments, ensure_ascii=False, indent=2), encoding='utf-8')
        (out / 'transcript.txt').write_text('\n'.join(f"[{stamp(s['start'])}] {s['text']}" for s in segments), encoding='utf-8')
    steps = []
    t = start
    while t < end:
        i = len(steps)+1
        log(f'Đọc hình {i} tại {stamp(t)}...')
        frame = out / f'frame_{i:03d}.jpg'
        command(['ffmpeg', '-y', '-v', 'error', '-ss', str(t), '-i', str(video), '-frames:v', '1',
                 '-vf', 'scale=1280:-2', '-q:v', '3', str(frame)])
        nearby = ' '.join(s['text'] for s in segments if s['start'] < min(t+interval, end) and s['end'] > t)
        prompt = ('Viết bằng tiếng Việt một bước trong tài liệu hướng dẫn. Lời nói được cung cấp là nguồn chính; '
                  'hình là minh họa để đối chiếu. Giữ đúng chỉ dẫn và thông số trong lời nói, '
                  'không bỏ chỉ dẫn chỉ vì hình không thể hiện. Phân biệt điều người nói hướng dẫn với điều nhìn thấy. '
                  'Bản chép lời có thể sai. Nếu từ ngữ kỹ thuật không rõ hoặc câu bất thường (ví dụ tríp, cách, kèm), '
                  'không tự biến thành thao tác cắt, tuốt, hàn hoặc tên dụng cụ đã xác nhận; '
                  'ghi thuật ngữ chưa rõ cần nghe lại. Thông số và đơn vị phải ghi theo bản chép lời, cần xác nhận. '
                  'Chỉ mô tả thao tác nhìn thấy và lời nói được cung cấp. Không tự suy đoán số đo, tên thiết bị, '
                  'mục đích hoặc thao tác bị che khuất. Nếu không rõ hãy ghi cần xác nhận. '
                  'Đây là một khung hình đơn lẻ, không khẳng định chuyển động không nhìn thấy. '
                  'Trả về văn bản thuần: dòng đầu là tiêu đề, các dòng sau là mô tả. '
                  f'Mốc hình: {stamp(t)}. Lời nói trong khoảng tiếp theo: {nearby or "Không có bản chép lời."}')
        payload = {'model': config['model'], 'messages': [{'role': 'user', 'content': [
            {'type': 'text', 'text': prompt}, {'type': 'image_url', 'image_url': {
                'url': 'data:image/jpeg;base64,' + base64.b64encode(frame.read_bytes()).decode()}}]}],
            'max_tokens': 2000, 'temperature': 0.2,
            'chat_template_kwargs': {'enable_thinking': False}}
        response = api(config['base'], '/chat/completions', payload, config['key'])
        text = response['choices'][0]['message']['content']
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError('Model không trả về nội dung văn bản.')
        steps.append({'time': t, 'frame': frame.name, 'description': text.strip(), 'transcript': nearby})
        (out / 'steps.json').write_text(json.dumps(steps, ensure_ascii=False, indent=2), encoding='utf-8')
        t += interval
    esc = html.escape
    page = '''<!doctype html><html lang="vi"><meta charset="utf-8"><title>Tài liệu từ video</title>
    <style>body{font:16px/1.65 Arial;background:#edf2f7;color:#203047}main{max-width:960px;margin:24px auto;padding:32px;background:white}img{width:100%}section{margin:30px 0;break-inside:avoid}pre{white-space:pre-wrap;font:inherit}aside{padding:16px;background:#fff4da}small{color:#596b80}@media print{body{background:white}main{margin:0;padding:0}}</style><main>'''
    page += f'<h1>Tài liệu hướng dẫn từ video</h1><p>{esc(video.name)} · {stamp(start)} – {stamp(end)}</p>'
    page += '<aside>Bản nháp do AI tạo. Cần kiểm tra các thao tác và thông số trước khi sử dụng. '
    page += ('Có đối chiếu bản chép lời tự động; bản chép lời có thể sai.' if segments else 'Chỉ dựa trên hình, chưa có bản chép lời.') + '</aside>'
    for i, step in enumerate(steps, 1):
        page += f'<section><h2>Hình {i} · {stamp(step["time"])}</h2><img src="{step["frame"]}"><pre>{esc(step["description"])}</pre>'
        if step['transcript']:
            page += f'<p><b>Lời nói trong khoảng này:</b> {esc(step["transcript"])}</p>'
        page += '</section>'
    page += '</main></html>'
    guide = out / 'huong_dan.html'
    guide.write_text(page, encoding='utf-8')
    log(f'Hoàn tất: {guide}')
    return guide


class App:
    def __init__(self, root):
        self.root = root
        root.title('Video → Tài liệu hướng dẫn · Qwen')
        root.geometry('800x700')
        self.events = queue.Queue()
        self.values = {}
        fields = [('video', 'Video', ''), ('base', 'API base URL', 'http://192.168.2.230:8000/v1'),
                  ('model', 'Model hình ảnh', 'qwen38'), ('key', 'API key (nếu có)', ''),
                  ('start', 'Bắt đầu (giây)', '0'), ('length', 'Độ dài đoạn (giây)', '60'),
                  ('interval', 'Lấy hình mỗi (giây)', '10'), ('whisper', 'Whisper model', 'small'),
                  ('language', 'Ngôn ngữ audio (vi / en / trống = tự nhận)', 'vi')]
        frame = ttk.Frame(root, padding=16)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(1, weight=1)
        for row, (key, label, default) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky='w', pady=5)
            var = tk.StringVar(value=default)
            self.values[key] = var
            ttk.Entry(frame, textvariable=var, show='*' if key == 'key' else '').grid(row=row, column=1, sticky='ew', padx=8)
        ttk.Button(frame, text='Chọn video', command=self.browse).grid(row=0, column=2)
        self.asr = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame, text='Chép lời bằng Whisper (cần chạy install_audio.cmd lần đầu)', variable=self.asr).grid(row=9, column=0, columnspan=3, sticky='w', pady=8)
        ttk.Label(frame, text='Khung hình được gửi đến API bạn nhập. Whisper chạy trên máy này.\nKết quả lưu trong thư mục output; mở HTML và Ctrl+P để lưu PDF.').grid(row=10, column=0, columnspan=3, sticky='w')
        self.button = ttk.Button(frame, text='Tạo tài liệu', command=self.start)
        self.button.grid(row=11, column=0, columnspan=3, pady=12)
        self.logbox = tk.Text(frame, height=15, wrap='word')
        self.logbox.grid(row=12, column=0, columnspan=3, sticky='nsew')
        frame.rowconfigure(12, weight=1)
        root.after(150, self.poll)

    def browse(self):
        name = filedialog.askopenfilename(filetypes=[('Video', '*.mp4 *.mkv *.mov *.avi *.webm'), ('Tất cả', '*.*')])
        if name:
            self.values['video'].set(name)

    def start(self):
        config = {k: v.get().strip() for k, v in self.values.items()}
        config['asr'] = self.asr.get()
        self.button.configure(state='disabled')
        def worker():
            try:
                path = generate(config, lambda s: self.events.put(('log', s)))
                self.events.put(('done', str(path)))
            except Exception as error:
                self.events.put(('error', str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                self.logbox.insert('end', value+'\n')
                self.logbox.see('end')
                if kind in ('error', 'done'):
                    self.button.configure(state='normal')
                    if kind == 'done':
                        webbrowser.open(Path(value).as_uri())
                    else:
                        messagebox.showerror('Không thể hoàn tất', value)
        except queue.Empty:
            pass
        self.root.after(150, self.poll)


if __name__ == '__main__':
    App(tk.Tk())
    tk.mainloop()
