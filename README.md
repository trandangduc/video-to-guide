# Video → tài liệu hướng dẫn

## Pipeline tự động trên Linux với Qwen38

Đọc [AUTOMATION.md](AUTOMATION.md) để chạy `run_auto.sh` / `auto_guide.py`: video → transcript thô → Qwen tự lập mục lục → đọc ảnh → viết hướng dẫn chi tiết → tự rà soát → bổ sung giải thích và kiểm định nguồn → HTML/PDF/Markdown. Không nạp nội dung hoặc ảnh đã chỉnh/chọn tay của bản mẫu cũ.

Pipeline hỗ trợ xử lý các mục song song, cache và kiểm tra nội dung; các lỗi chất lượng video còn lại được ghi trong [HANDOFF.md](HANDOFF.md). Xem tài liệu bàn giao để biết kết quả đã kiểm tra và giới hạn hiện tại.

Web có tab video và tab **Ảnh + mô tả → Excel**: upload mẫu XLSX, mô tả TXT, PDF và ảnh; Qwen38 đọc/ghép ảnh, giữ sheet 1–2 và header/logo. Sheet 3–4 dùng textbox và bố cục trái/phải của mẫu, căn mô tả/ảnh thẳng hàng. Cách chạy và các yêu cầu đầu vào ở [AUTOMATION.md](AUTOMATION.md). Dữ liệu mẫu riêng và đầu ra không đưa vào Git.

```sh
.venv/bin/python web_app.py --host 127.0.0.1 --port 9322
.venv/bin/python -m unittest discover -s tests -v
```

GUI Tkinter bên dưới vẫn là prototype cũ. `requirements-local.txt` ghi các thư viện dùng cho pipeline Linux.

## Triển khai trên máy GPU

Đọc [PLAN.md](PLAN.md) để tiếp tục xây dựng pipeline audio → bước hướng dẫn → chọn hình tương ứng. Đích triển khai: 2 RTX 5090, Whisper large-v3 và WhisperX, Qwen vision qua API.

Mã hiện tại là prototype: Whisper small trên CPU và ảnh định kỳ. Chọn hình theo nội dung, CUDA và WhisperX trong kế hoạch chưa được triển khai. Không có video nguồn trong repo; chuyển video sang máy đích riêng.

## Chạy prototype hiện tại

1. Nhấp đúp `run.cmd` (cần Python có Tkinter và FFmpeg/ffprobe trong PATH).
2. Chọn video. API mặc định: `http://192.168.2.230:8000/v1`, model: `qwen38`.
3. Thử 60 giây, khoảng hình 10 giây. Bấm **Tạo tài liệu**.
4. Kết quả tự mở trong trình duyệt. Ctrl+P → Lưu dưới dạng PDF. Giữ nguyên thư mục ảnh bên cạnh HTML.

Chép lời bằng Whisper được bật mặc định: chạy `install_audio.cmd` một lần nếu chưa cài thư viện. Lần đầu sử dụng cần Internet để tải model Whisper. `small` nhẹ hơn; `medium` chậm hơn trên CPU và thường cho kết quả tốt hơn. Nhập `vi` cho tiếng Việt, `en` cho tiếng Anh, để trống để tự nhận dạng. Lời nói là nguồn chính cho hướng dẫn; Qwen nhận cả hình và lời nói trong cùng khoảng thời gian. Có thể bỏ chọn chép lời để thử riêng phần đọc hình.

Audio được xử lý trên máy này. Chỉ các khung hình đã lấy và đoạn chép lời tương ứng được gửi đến API cấu hình. Tool không cần Codex hoặc ChatGPT để chạy. API key chỉ được giữ trong bộ nhớ phiên chạy.

Đây là bản nháp theo các khung hình định kỳ, có thể bỏ lỡ thao tác giữa hai hình. Giảm khoảng lấy hình để có nhiều chi tiết hơn (tăng số lần gọi model). Nội dung AI và chép lời cần được kiểm tra lại. Tool không tự xác nhận thông số kỹ thuật. Nếu bị lỗi giữa chừng, ảnh và các bước hoàn thành vẫn nằm trong thư mục output; chạy lại tạo một thư mục mới. Không có chức năng tiếp tục phiên cũ.

Đóng cửa sổ sẽ kết thúc tác vụ đang chạy. Whisper hiện chạy CPU; chưa hỗ trợ chọn GPU trong giao diện. Kết quả gồm HTML, ảnh, steps.json và (khi bật chép lời) audio.wav, transcript.txt, transcript.json.

## Chạy web nền trên Linux

Web app có thể chạy dưới dạng user service để vẫn hoạt động sau khi đóng terminal hoặc VS Code:

```sh
systemctl --user link "$(pwd)/video-to-guide-web.service"
systemctl --user daemon-reload
systemctl --user enable --now video-to-guide-web.service
systemctl --user status video-to-guide-web.service
```

Web app lắng nghe cổng 9322. Xem log bằng `journalctl --user -u video-to-guide-web.service -f`; dùng `systemctl --user restart video-to-guide-web.service` hoặc `systemctl --user stop video-to-guide-web.service` để quản lý. Service bind vào `0.0.0.0` để có thể truy cập qua địa chỉ máy chủ; chỉ mở cổng này trên mạng đáng tin cậy vì ứng dụng chưa có đăng nhập.
