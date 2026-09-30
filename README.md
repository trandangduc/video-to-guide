# Video → tài liệu hướng dẫn

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
