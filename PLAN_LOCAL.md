# Kế hoạch triển khai trên máy hiện tại: video có lời hướng dẫn → tài liệu có ảnh

Ngày lập: 05/10/2026 (Asia/Saigon).
Trạng thái: kế hoạch đề xuất; chưa cài dependency hoặc triển khai pipeline mới.

## 1. Quyết định đề xuất

Người dùng xác nhận video có tiếng hướng dẫn. Dùng lời nói làm nguồn chính để viết nội dung, dùng hình thật trong video để minh họa và đối chiếu. Những thao tác quan trọng chỉ nhìn thấy trong hình cần được đối chiếu riêng, không suy diễn từ lời nói.

Bắt đầu với Whisper large-v3 qua faster-whisper và API qwen38 đang chạy. Chưa cần triển khai thêm Qwen3-VL. Xem video trực tiếp là lựa chọn bổ sung khi phân tích ảnh theo bước không giải quyết được thao tác liên tục hoặc thứ tự hành động.

Kế hoạch này bổ sung PLAN.md bằng kết quả kiểm tra máy hiện tại. Không ghi đè các yêu cầu và kế hoạch cũ. Repo hiện là prototype Tkinter: Whisper chạy CPU, lấy ảnh định kỳ, xuất HTML; chưa có chọn ảnh theo nội dung và chưa có pipeline GPU hoàn chỉnh.

## 2. Tài nguyên đã kiểm tra

Các con số là ảnh chụp trạng thái tại lúc kiểm tra, cần đọc lại trước mỗi job.

| Thành phần | Quan sát | Ảnh hưởng đến thiết kế |
| --- | --- | --- |
| Hệ điều hành / CPU | Linux; môi trường thấy 8 CPU logic; CPU name Ryzen 9 9950X | Có thể tách audio, lấy ảnh và xử lý CPU; không coi tên CPU là số lõi được cấp |
| RAM | Khoảng 60 GiB tổng, 36 GiB available | Có thể chạy ASR CPU nếu GPU không đủ chỗ |
| Đĩa | Khoảng 363 GiB trống trên phân vùng home | Đủ làm mẫu; giới hạn ảnh ứng viên và dọn cache theo job |
| GPU 0 | RTX 5090, 32607 MiB tổng; 4789 MiB trống | Có thể thử ASR tiết kiệm VRAM sau khi kiểm tra lại, chưa bảo đảm đủ |
| GPU 1 | RTX 5090, 32607 MiB tổng; 295 MiB trống | Chưa phù hợp để thêm ASR/model mới |
| Vision đang phục vụ | vLLM Qwen/Qwen3.8-27B-FP8, tensor parallel 2 GPU | Tận dụng dịch vụ đang chạy |
| API local | http://127.0.0.1:8000/v1; model qwen38, alias qwen36 cùng root model | Gọi trực tiếp từ pipeline trên máy này |
| Dịch vụ khác | MinerU, embedding, TTS và Ollama | VRAM tổng 64 GB không đồng nghĩa 64 GB còn trống; bộ nhớ hai GPU không tự gộp |
| Ollama | Đã có qwen3-vl:latest, metadata 8.8B Q4_K_M | Chưa cần tải model này; không tự nạp thêm vào VRAM đang gần đầy |
| Công cụ xử lý | ffmpeg/ffprobe chưa có trong PATH ở shell đã kiểm tra; faster-whisper/WhisperX chưa thấy trong Python hệ thống và venv vrag | Chuẩn bị venv riêng và công cụ video khi bắt đầu triển khai |

Kiểm tra API: qwen38 nhận được 2 ảnh mẫu trong cùng request và trả đúng chữ/màu riêng của từng ảnh, khoảng 3,78 giây. Đây chỉ là smoke test khả năng nhận nhiều ảnh; chưa chứng minh chất lượng phân tích video thực tế. Kết quả JSON nằm trong markdown fence nên vẫn cần parser và validation.

File video hiện có: 20260924_133059.mp4. Khi kiểm tra file tăng từ khoảng 92 MB lên 107 MB; OpenCV báo `moov atom not found`. Có thể đang chép chưa xong hoặc file có vấn đề. Chưa xác minh được độ dài, luồng audio hoặc nội dung video trên máy này. Thông tin 9 phút 38 giây trong PLAN.md là từ máy nguồn, không phải kết quả probe hiện tại.

## 3. Pipeline đề xuất

```text
Video có lời hướng dẫn
  → kiểm tra file đọc được, luồng audio/video, thời lượng
  → tách audio 16 kHz mono
  → Whisper: lời nói + segment IDs + timestamps
  → Qwen: chia thành bước và giữ tham chiếu lời nói gốc
  → lấy ảnh ứng viên quanh từng bước
  → lọc ảnh mờ/trùng và giữ đa dạng theo thời gian
  → Qwen: chọn ảnh khớp thao tác, đối chiếu nội dung
  → người dùng sửa bước và thay ảnh nếu cần
  → HTML có ảnh nhúng + PDF; JSON nguồn và ảnh gốc
```

Ảnh định kỳ chỉ để tìm ứng viên. Không tạo một bước hướng dẫn chỉ vì đã đến mốc 10 giây. Tài liệu cuối đi theo thao tác thực tế: tiêu đề, câu hướng dẫn, 1–3 ảnh khi cần, chú thích và mốc video nguồn.

## 4. Phân bổ tài nguyên

- Dùng qwen38 đang phục vụ, giới hạn ban đầu một request vision mỗi lần; tăng sau khi đo.
- CPU đảm nhiệm FFmpeg, lọc ảnh và xuất tài liệu. Chỉ giữ ảnh cần thiết theo job.
- ASR ưu tiên large-v3 vì tiếng Việt và thuật ngữ; thử GPU 0 với INT8/FP16 hỗn hợp, không batching, sau khi xác minh CUDA/CTranslate2 tương thích RTX 5090.
- VRAM khoảng 4,7 GiB trống chưa bảo đảm đủ: đo đỉnh dùng thật trên mẫu 60 giây và giữ khoảng dự phòng. Nếu không đủ, chạy large-v3 INT8 trên CPU cho thử nghiệm, chấp nhận chậm hơn; model nhỏ chỉ dùng kiểm tra đường đi nếu cần, không mặc định là chất lượng cuối.
- Muốn chạy GPU ổn định có thể cần sắp lại tài nguyên các dịch vụ. Đó là thay đổi triển khai riêng; không tự dừng embedding/TTS/MinerU hoặc khởi động lại Qwen trong công việc lập kế hoạch này.
- Giải phóng model ASR của job sau khi chép lời xong rồi mới xử lý ảnh. Dịch vụ Qwen hiện tại vẫn giữ bộ nhớ của nó.
- Đo thời gian từng stage, đỉnh RAM/VRAM, số ảnh và số request. Chưa có benchmark nên không hứa thời gian xử lý toàn video.

## 5. Các giai đoạn và điều kiện hoàn thành

### Giai đoạn 1 — Môi trường và mẫu 60–90 giây

1. Chờ file video hoàn tất, probe xác nhận đọc được và có audio. File lỗi thì dừng tại đây, báo rõ nguyên nhân.
2. Tạo venv riêng trong video-to-guide; cài FFmpeg/ffprobe và thư viện cần thiết, tránh cài vào venv đang phục vụ Qwen.
3. Kiểm tra phiên bản CUDA/CTranslate2 và inference thực tế trên RTX 5090 trước khi chọn cấu hình GPU.
4. Chọn đoạn mẫu có cả lời nói và thao tác; kiểm tra thêm đoạn bắt đầu giữa video để xác minh offset.
5. Chép lời large-v3 với tiếng Việt, VAD và timestamps. Giữ transcript thô riêng, bản sửa riêng. Kiểm tra tên linh kiện, số đo, đơn vị, thuật ngữ Anh–Việt bằng cách nghe lại.

Đầu ra: media.json, transcript.raw.json, transcript.reviewed.json nếu đã sửa, báo cáo tài nguyên và các chỗ cần kiểm tra. Chưa làm tài liệu toàn video trước khi chất lượng mẫu đạt yêu cầu.

### Giai đoạn 2 — Chia bước từ lời nói

1. Gửi transcript có segment IDs cho Qwen để nhận diện thao tác, gộp lời lặp và viết câu hướng dẫn ngắn.
2. Mỗi bước giữ source_segment_ids; code tính start/end từ segment gốc, không để model tự tạo timestamps.
3. Giữ số đo/đơn vị và đánh dấu từ chưa rõ. Kiểm tra không bỏ mất thao tác hoặc tự bổ sung điều kiện không có nguồn.
4. Timestamps của Whisper đủ để bắt đầu. Thêm WhisperX alignment nếu thực tế cho thấy lệch mốc làm chọn ảnh khó; không coi alignment là bước cải thiện nội dung nhận dạng.

Đầu ra: steps.json; mỗi bước có tiêu đề, hướng dẫn, nguồn lời nói và khoảng thời gian.

### Giai đoạn 3 — Chọn ảnh đúng thao tác

1. Mỗi bước lấy khoảng 8–12 ảnh ứng viên trong cửa sổ thời gian, khởi điểm mở rộng trước/sau khoảng 3 giây; điều chỉnh theo độ lệch lời nói–thao tác.
2. Lọc độ mờ và ảnh gần trùng; giữ các trạng thái trước/thao tác/kết quả. Camera chuyển cảnh không phải điều kiện bắt buộc: thao tác có thể diễn ra khi camera đứng yên.
3. Gửi nhóm nhỏ ảnh đánh số kèm timestamp và nội dung bước cho qwen38, ví dụ 4–6 ảnh/request; kiểm tra giới hạn API trước khi tăng.
4. Model chọn IDs và mô tả bằng chứng nhìn thấy, hoặc trả no_match. Code xác minh IDs và đường dẫn tồn tại.
5. Nếu bỏ lỡ thao tác nhanh, lấy ảnh dày hơn quanh đoạn đó. Nếu ảnh rời vẫn không rõ, thử clip ngắn bằng khả năng video của model/API hiện tại.
6. Chọn 1–3 ảnh thật/bước; chú thích dựa trên chi tiết thấy được. Khoanh vùng/mũi tên là tùy chọn sau khi vị trí được xác minh, luôn giữ ảnh gốc.

Đầu ra: bước có ảnh minh họa, thời điểm ảnh, lý do chọn và trạng thái cần kiểm tra. Chưa tìm được ảnh thì cho chọn thủ công; không ghép ảnh không liên quan.

### Giai đoạn 4 — Duyệt và xuất tài liệu

1. Giao diện web local: chọn video, xem tiến độ, đọc/sửa từng bước, nghe lời nói hoặc tua lại video tại mốc tương ứng.
2. Cho thay ảnh từ ứng viên và lưu thay đổi. Mỗi stage có cache/checkpoint để tiếp tục sau lỗi; đổi transcript phải vô hiệu hóa kết quả phụ thuộc.
3. Xuất HTML nhúng ảnh để mở được một file độc lập và PDF để chia sẻ. Lưu JSON và ảnh gốc phục vụ chỉnh sửa/truy nguồn. Thêm DOCX nếu cần chỉnh trong Word.
4. Chạy toàn bộ video sau khi bản mẫu được duyệt. Tài liệu cần rõ thao tác, ảnh phù hợp và không mất thông số.

## 6. Qwen3-VL có cần thiết không?

Chưa cần thêm model. Máy đã có Qwen3-VL trong Ollama, và qwen38 hiện tại đã vượt qua bài kiểm tra nhận nhiều ảnh. Model card Qwen3.8-27B-FP8 còn có ví dụ input video, nhưng chưa kiểm tra đường đi video trực tiếp trên API đang chạy.

Qwen3-VL hỗ trợ video thông qua xử lý/lấy mẫu khung hình và thông tin thời gian. Model hỗ trợ video và server hỗ trợ nhận file video là hai khả năng cần kiểm tra riêng. Không nên mặc định có thể gửi một MP4 dài vào bất kỳ API nào hoặc rằng vision tự chép chính xác tiếng nói.

Chỉ đánh giá phương án video/model khác khi có bằng chứng: không có lời nói cho thao tác quan trọng, chuyển động nhanh bị ảnh rời bỏ lỡ, thứ tự trạng thái không rõ hoặc model hiện tại chọn ảnh sai trong tập mẫu. Ưu tiên clip ngắn/chuỗi ảnh có timestamp và model hiện tại trước khi triển khai thêm một dịch vụ.

## 7. Nghiệm thu

- Người dùng nghe lại mẫu và xác nhận lời hướng dẫn, đặc biệt thông số và thuật ngữ.
- Mỗi bước truy được về transcript; mỗi ảnh truy được về timestamp video gốc.
- Người dùng đối chiếu ảnh với thao tác, có thể sửa câu và thay ảnh.
- Thử lệch lời nói–thao tác, tay che, đoạn im lặng, không tìm được ảnh, API timeout/JSON sai.
- Thử đoạn bắt đầu >0 để audio, ảnh và mốc video không lệch offset.
- Thử tiếp tục job sau lỗi và cache khi sửa transcript.
- HTML/PDF mở độc lập, ảnh rõ; chất lượng và tốc độ được báo bằng kết quả đo thật.

Bước triển khai đầu tiên: hoàn tất video → môi trường riêng → chép lời mẫu bằng large-v3 → chia bước và chọn ảnh bằng qwen38 → duyệt PDF mẫu.

## 8. Tài liệu tham khảo chính thức

- Qwen3.8 model card, gồm ví dụ ảnh và video: https://huggingface.co/Qwen/Qwen3.8-27B-FP8
- Qwen3-VL, xử lý video và lấy mẫu fps/num_frames: https://github.com/QwenLM/Qwen3-VL
- vLLM multimodal inputs, nhiều ảnh và video: https://docs.vllm.ai/en/stable/features/multimodal_inputs/
- faster-whisper, CPU/GPU và INT8: https://github.com/SYSTRAN/faster-whisper
