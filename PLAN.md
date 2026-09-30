# Kế hoạch: Video → tài liệu hướng dẫn theo lời nói

Ngày: 30/09/2026. Đây là kế hoạch triển khai trên máy GPU; chưa phải tính năng đã hoàn thành.

## 1. Mục tiêu và yêu cầu đã chốt

Người dùng chọn video hướng dẫn, hệ thống nhận dạng lời nói tiếng Việt, chia lời nói thành các bước và tự chọn hình thể hiện thao tác tương ứng. Xuất tài liệu dễ sửa, có thể truy ngược về video nguồn.

- Nội dung hướng dẫn lấy từ audio. Hình dùng để minh họa và đối chiếu.
- Không lấy ảnh vào tài liệu chỉ vì đến một khoảng thời gian cố định.
- Mỗi bước có thể có 1–3 hình, ví dụ trạng thái trước, thao tác và kết quả.
- Ưu tiên chất lượng nhận dạng, không tối ưu theo giới hạn CPU.
- Phần cứng đích do người dùng cung cấp: 2 NVIDIA RTX 5090, tổng 64 GB VRAM. Bộ nhớ của hai GPU không tự gộp; xác minh VRAM và phần đang được Qwen sử dụng trước khi phân bổ.
- Chỉ chọn repo thư viện/model ASR có hơn 5.000 sao. Kiểm tra lại trước triển khai; không dùng repo đông sao làm vỏ bọc cho một model ASR khác chưa đạt điều kiện.
- Tool chạy độc lập, không cần Codex/ChatGPT để xử lý video.
- Tiếng Việt có thể pha từ kỹ thuật tiếng Anh, tên linh kiện, số đo và đơn vị.

## 2. Stack đề xuất

Số sao lấy qua GitHub API trong phiên nghiên cứu 30/09/2026, có thể thay đổi:

| Repo | Sao | Vai trò |
| --- | ---: | --- |
| https://github.com/openai/whisper | 109784 | Model ASR `large-v3` |
| https://github.com/SYSTRAN/faster-whisper | 25633 | Inference GPU bằng CTranslate2 |
| https://github.com/m-bain/whisperX | 24311 | Căn transcript với audio để có mốc thời gian chi tiết |

WhisperX dùng faster-whisper; đây không phải ba model ASR độc lập. Chạy baseline Whisper large-v3 và so chất lượng trước khi chọn cấu hình cuối.

WhisperX có cấu hình alignment tiếng Việt trong `whisperx/alignment.py`, hiện trỏ đến `nguyenvulebinh/wav2vec2-base-vi-vlsp2020`. Đó là model căn thời gian phụ trợ, không phải model chép lời chính. Điều kiện >5k được áp dụng cho repo stack ASR ở trên; nếu người dùng yêu cầu cả model phụ trợ cũng phải có repo >5k, dùng timestamps của Whisper trước và báo giới hạn, không lách điều kiện.

Qwen vision hiện chạy với API tương thích OpenAI:

- API base mặc định qua biến môi trường: `http://192.168.2.230:8000/v1`.
- Model: `qwen38`.
- Đã kiểm tra model list và gọi đọc một ảnh thành công từ máy Windows nguồn.
- Cần kiểm tra lại khả năng nhận nhiều ảnh trong một request và JSON có cấu trúc trên máy đích.
- Model này dùng cho chia bước, đánh giá hình và soạn tài liệu; chưa xác minh khả năng nhận audio.
- Không chọn Qwen3-ASR cho kế hoạch này: khi kiểm tra có 3630 sao, chưa đạt điều kiện.

Tài liệu tham chiếu:

- https://github.com/openai/whisper
- https://github.com/SYSTRAN/faster-whisper
- https://github.com/m-bain/whisperX
- https://github.com/m-bain/whisperX/blob/main/whisperx/alignment.py

## 3. Hiện trạng prototype trong repo

`app.py` là prototype Tkinter, chọn video → tách audio bằng FFmpeg → Whisper small trên CPU → lấy hình định kỳ → gọi Qwen → xuất HTML.

Đã thử nhận dạng 60 giây đầu, nhận được transcript nhưng nhiều lỗi thuật ngữ. Đã thử gửi transcript đó cùng 6 ảnh đến Qwen và xuất HTML. Lần thử ghép hình dùng transcript đã lưu để không phải nhận dạng lại. Đã kiểm tra khởi tạo GUI. Chưa thử CUDA, large-v3, WhisperX hoặc chọn hình theo nội dung.

Không đưa video nguồn, audio, frame hoặc output lên GitHub. Video gốc trên máy nguồn: `20260924_133059.mp4`, khoảng 9 phút 38 giây, 1920×1080, có audio. Người dùng cần chuyển video sang máy đích riêng.

## 4. Kiến trúc cần triển khai

```text
Video
  → probe + audio 16 kHz mono (giữ ánh xạ thời gian gốc)
  → ASR large-v3 + VAD
  → transcript thô có timestamps
  → alignment tiếng Việt khi có thể
  → Qwen chia thành bước, tham chiếu segment IDs
  → lấy các hình ứng viên quanh từng bước
  → loại mờ/trùng + Qwen so khớp nội dung thao tác
  → chọn 1–3 hình/bước, ghi rõ mức khớp và nguồn
  → trình duyệt kiểm tra/sửa
  → HTML và Markdown; DOCX ở giai đoạn sau
```

Tách pipeline khỏi UI. UI chỉ tạo job, hiển thị tiến độ, sửa nội dung và xem kết quả. Ưu tiên Python backend + giao diện web chạy trong LAN để thao tác trên máy GPU; giữ CLI cho kiểm thử và tự động hóa. Không biến prototype Tkinter thành nơi chứa mọi logic.

Các module đề xuất: `media`, `asr`, `alignment`, `step_builder`, `frame_candidates`, `vision_selector`, `document`, `jobs`, `config`. Mỗi giai đoạn có đầu vào/đầu ra JSON và cache riêng.

## 5. Các giai đoạn triển khai

### P0 — Kiểm tra môi trường GPU

1. Chạy `nvidia-smi`, xác định OS, driver, VRAM trống, các process của Qwen.
2. Tạo môi trường Python riêng, không cài chồng lên môi trường Qwen.
3. Pin phiên bản Python/PyTorch/CTranslate2/WhisperX sau khi xác minh chúng hỗ trợ RTX 5090. Kiểm tra tương thích Blackwell bằng smoke test thực tế; không suy ra chỉ từ việc CUDA được nhận diện.
4. Chọn một GPU có đủ bộ nhớ trống cho ASR; dành phần còn lại cho Qwen. Không mặc định Qwen chỉ dùng một GPU.
5. Kiểm tra FFmpeg, API model list, một ảnh và một request nhiều ảnh có đánh số.

Hoàn thành khi chạy được inference audio trên GPU và request vision có kết quả. Ghi phiên bản và cấu hình vào tài liệu setup.

### P1 — Nâng chất lượng ASR và kiểm chứng

1. Trích đúng 60 giây đầu làm mẫu, sau đó thêm một đoạn có nhiều thuật ngữ kỹ thuật từ giữa video.
2. Baseline: Whisper large-v3, CUDA FP16, `language=vi`, VAD, beam size khởi điểm 5. Thử tác động của context trước đó; không coi beam lớn là bảo đảm chính xác hơn.
3. So sánh với small hiện tại bằng bản chép lời được người dùng xác nhận. Nếu chưa có reference đã xác nhận, chỉ báo khác biệt, không báo WER như kết quả đáng tin cậy.
4. Đánh giá riêng số đo, đơn vị, màu dây, tên linh kiện và từ Anh–Việt. Có thể thêm glossary do người dùng cung cấp vào prompt ASR nếu backend hỗ trợ, nhưng không dùng glossary để đoán lại câu.
5. Giữ nguyên `transcript.raw.json`; bản chỉnh sửa hoặc chuẩn hóa nằm trong file riêng, kèm ghi nhận thay đổi.
6. Không đổi số đo/đơn vị hoặc diễn giải từ không rõ bằng Qwen thành một chỉ dẫn chắc chắn. Đánh dấu đoạn cần nghe lại và cho phát audio tại chỗ.

Hoàn thành khi có transcript mẫu, báo cáo so sánh thực tế, số đo/đơn vị được đánh dấu để kiểm tra. Chất lượng chưa đạt thì xử lý ASR trước khi viết tài liệu đẹp.

### P2 — Timestamps và chia bước từ audio

1. Căn transcript với audio qua WhisperX alignment tiếng Việt. Giữ lại timestamps gốc để fallback khi alignment thất bại hoặc thiếu từ.
2. Với từ tiếng Anh/đơn vị không căn được, ghi `alignment_status`; không tạo thời gian giả với vẻ chính xác.
3. Gửi transcript với segment IDs tới Qwen, yêu cầu chia theo thao tác, gộp câu lặp, giữ toàn bộ thông số.
4. Qwen trả JSON gồm title, instruction, source_segment_ids, uncertain_terms. Thời gian bước được code tính từ IDs; không để model tự bịa timestamps.
5. Validate IDs có tồn tại, thứ tự thời gian, giới hạn video, thông số giữ nguyên và câu bị bỏ sót. Retry có giới hạn nếu JSON sai.

Hoàn thành khi mỗi bước truy về được lời nói gốc; khoảng thời gian không lệch do offset đoạn video hoặc cắt khoảng im lặng.

### P3 — Tự chọn hình theo bước

1. Với mỗi bước, tạo cửa sổ thời gian từ audio. Khởi điểm mở rộng trước/sau 3 giây; giới hạn trong video. Đây là tham số cần thử, không phải chân lý.
2. Lấy 8–12 ảnh ứng viên rải trong cửa sổ. Lấy ảnh định kỳ ở đây chỉ là tìm ứng viên, không phải chọn ảnh đưa vào tài liệu.
3. Dùng độ nét và độ giống ảnh để giảm ảnh mờ/trùng. Giữ đa dạng theo thời gian; không loại tất cả ảnh khác biệt chỉ vì camera rung.
4. Gửi hình đánh số, timestamp và nội dung bước tới Qwen. Yêu cầu chọn IDs, nêu thao tác nhìn thấy và lý do khớp. Trả `no_match` nếu chưa có ảnh thể hiện thao tác.
5. Nếu thiếu hình, mở rộng có giới hạn quanh bước và thử lại. Không chuyển sang hình của bước khác mà không ghi nhận nguồn.
6. Chọn tối đa 3 ảnh để minh họa trước/thao tác/kết quả; kiểm tra IDs, loại trùng và giữ ảnh gốc tương ứng.
7. Nếu không có ảnh phù hợp, xuất bước với lời hướng dẫn và trạng thái cần chọn hình thủ công. Không tạo ảnh giả thay thao tác thật.

Hoàn thành khi từng ảnh có lý do khớp với bước và người dùng thấy rõ thao tác. Không hứa chọn đúng chỉ dựa vào timestamp: người nói và thao tác có thể lệch nhau.

### P4 — Giao diện kiểm tra và xuất tài liệu

- Chọn video và đoạn thử, cấu hình ASR/Qwen, glossary và nơi lưu.
- Tiến độ riêng từng stage, hiển thị lỗi hữu ích, hủy job.
- Xem bước, nghe đoạn audio và tua video tại đúng mốc.
- Sửa transcript/instruction và chọn ảnh thay thế từ danh sách ứng viên; sửa transcript phải vô hiệu cache phụ thuộc.
- Lưu phiên, tiếp tục job sau lỗi, không xử lý lại các stage hợp lệ.
- Export HTML in được, Markdown và JSON nguồn. DOCX là phần tiếp theo nếu cần bản sửa bằng Word.
- Backend LAN phải giới hạn thư mục truy cập và có xác thực nếu mở ra ngoài máy; không lưu API key vào log hoặc Git.

## 6. Hợp đồng dữ liệu tối thiểu

```json
{
  "step_id": "step_003",
  "title": "Tiêu đề lấy từ chỉ dẫn",
  "instruction": "Nội dung hướng dẫn",
  "source_segment_ids": ["seg_007", "seg_008"],
  "start": 18.3,
  "end": 28.3,
  "uncertain_terms": [],
  "selected_frames": [
    {"candidate_id": "c003_05", "time": 24.0,
     "path": "frames/c003_05.jpg", "match_reason": "Thao tác nhìn thấy"}
  ],
  "review_status": "needs_review"
}
```

Các số và câu trong ví dụ là minh họa schema, không phải thông số đã xác nhận từ video. Timestamps luôn dùng giây trong video gốc. Cache key gồm hash nguồn, đoạn xử lý, phiên bản model, config và prompt. File checkpoint không được đánh dấu hoàn thành trước khi validate và ghi atomically.

## 7. Kiểm thử và nghiệm thu

- Video không audio, im lặng, sai đường dẫn, đoạn ngoài video, API lỗi/timeout/JSON sai.
- Chọn đoạn bắt đầu >0: audio, hình, timestamps và link tua đều đúng offset.
- Model nhận dạng xong nhưng alignment thiếu từ: vẫn có transcript và thông báo fallback.
- Lời nói trước thao tác, thao tác kéo dài, tay che, máy quay đứng yên, các câu lặp, không tìm thấy hình.
- Cache/resume, thay glossary hoặc transcript phải chạy lại đúng stage phụ thuộc.
- Không để lời sai từ ASR biến thành thông số đã được xác nhận. Không báo accuracy/WER khi chưa có reference.
- Smoke test trên RTX 5090 và test end-to-end 60 giây, sau đó toàn bộ video 9 phút 38 giây.
- Ghi thời gian từng stage, VRAM cực đại, số request Qwen và kết quả đánh giá thủ công; không chỉ đo tốc độ ASR.

## 8. Hướng dẫn cho agent triển khai ở máy đích

Đọc PLAN.md và prototype để hiểu hiện trạng. Bắt đầu từ P0/P1. Chưa tải/cài tất cả model một lượt. Dùng môi trường riêng, bảo toàn dịch vụ Qwen đang chạy. Xác minh điều kiện sao repo và tương thích GPU. Lưu transcript mẫu, so chất lượng và báo rõ giới hạn trước khi chuyển sang chọn hình tự động. Sau đó triển khai P2/P3/P4, chạy thử thật và cập nhật README với lệnh chạy đã kiểm chứng. Không mô tả tính năng trong kế hoạch là đã hoàn thành.
