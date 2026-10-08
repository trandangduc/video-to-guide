# Pipeline tự động bằng Qwen38

Luồng chạy chính trên máy Linux là `run_auto.sh` / `auto_guide.py`. Đây là pipeline CLI riêng; GUI Tkinter trong `app.py` vẫn là prototype cũ và chưa nối với pipeline này.

## Phân chia trách nhiệm (auto-v6-speed)

Không có bảng thuật ngữ, tên phần mềm hay câu hướng dẫn viết riêng cho một video. Mọi tri thức chuyên ngành đến từ lời nói và chữ trên màn hình của chính video đó.

1. **ASR**: Whisper chép lời có segment IDs/timestamps. Ngôn ngữ tự nhận dạng nếu không truyền `--language`. Câu giống hệt nhau lặp từ 3 lần trở lên (ảo giác của Whisper khi gặp đoạn im lặng/nhạc, vd. "Hãy subscribe…") bị loại.
   **Video không có lời giảng**: nếu sau khi lọc còn dưới 15 từ/phút (hoặc video không có audio), pipeline chuyển sang chế độ màn hình: gộp keyframe liên tiếp thành các đoạn nguồn `scr_XXXX` khoảng 45 giây (mô tả và chữ trên màn hình, loại quan sát gần trùng), vẫn giữ từng keyframe để chọn ảnh, lưu ở `transcript.screen.json`; `document.auto.json` ghi `source_mode: screen_only`.
2. **Khung hình theo thay đổi màn hình**: code lấy mẫu 2 khung/giây, chọn khung khi tỷ lệ điểm ảnh thay đổi ≥ `--scene-threshold` và màn hình đã đứng yên (hộp thoại, sơ đồ, danh sách file), cộng một khung tối thiểu mỗi `--max-frame-gap` giây. Thay cho 6 mốc cố định của v3, vốn bỏ lỡ hộp thoại Export.
3. **Đọc chữ màn hình theo từng khung**: Qwen đọc từng keyframe độc lập với transcript (`screen_text.json`).
   **Đọc lại chữ hiếm** (`screen_rechecks.json`): dò vùng nền sáng, để model định vị cụm chữ bằng bbox rồi phóng to cụm đó; tối đa 2 ảnh/request, xử lý tuần tự. Model xác nhận cùng nhãn với p≥0.6, có phân biệt nét kéo bút với chữ cái riêng. Code bác ứng viên làm mất phần tên, đổi phần số hoặc ghép từ giao diện thông thường; không chuẩn hóa chỉ bằng độ giống phát âm. Bản OCR gốc vẫn giữ trong `screen_text.json`; các cách đọc được chấp nhận áp dụng trong bộ bằng chứng của lần chạy. Có thể thử riêng bằng `recheck_screen_text.py --source <job> --output <thư-mục-thử-riêng> [--read <chuỗi>]`; không dùng output của job chính làm thư mục thử có lọc.
4. **Bảng đối chiếu thuật ngữ**: Qwen ghép từ ASR với chữ màn hình theo từng cửa sổ thời gian (kèm danh sách thuật ngữ kỹ thuật của toàn video). Code chỉ nhận cặp có chữ màn hình thực sự nằm trong khung được trích dẫn. Sau đó một cổng xác suất kiểu SemIf hỏi "người nói có đang gọi tên chữ màn hình này không": p≥0.5 → `terms` (đã xác minh), 0.2–0.5 → `possible` (chỉ là gợi ý cho model), còn lại bị loại (`glossary.json`).
5. **ASR lượt 2 (tùy chọn `--asr-second-pass`)**: chép lời lại với hotwords ngắn (≤200 ký tự) lấy từ thuật ngữ đã xác minh. Khi dùng lượt hai, prompt vẫn kèm ASR lượt đầu của cùng cửa sổ để đối chiếu nghĩa/quan hệ; source IDs lấy theo lượt đang dùng. Nếu lượt 2 mất >15% số từ so với lượt 1 thì giữ lượt 1 (`asr_second_pass.json`). Danh sách hotwords dài làm Whisper chỉ còn nhận ra các từ lẻ.
6. Chế độ ít/không lời yêu cầu model gộp mục lục thành các giai đoạn thao tác; số mục tối đa bằng `ceil(thời lượng / 75 giây)`, tối thiểu một mục. Việc gộp chỉ gửi metadata mục lục, kiểm tra giữ đủ khoảng nguồn; không gửi cả video. Mỗi segment chỉ được gắn vào một khoảng mục lục, không chồng nguồn; model tự sửa khi vi phạm. Qwen lập mục lục theo từng đoạn transcript, phân loại đoạn bị loại, viết từng mục với ảnh ứng viên trong khoảng thời gian của mục, rà độ đầy đủ từng mục, bổ sung giải thích, kiểm định nguồn.
7. **Kiểm định từng khẳng định (kiểu SemIf)**: Qwen tách mục thành các khẳng định ngắn; mỗi khẳng định được chấm bằng xác suất token A/B/C/D (được hỗ trợ / mâu thuẫn / chưa đủ nguồn / tổng quát hóa quá mức) với bằng chứng là transcript của mục, chữ màn hình quanh mục và bảng đối chiếu.
   **Rà nghĩa từ ngữ riêng**: model rà cách gọi/công dụng không có căn cứ, rồi trích cụm danh từ nguyên văn và chấm từng cụm với nguồn. Bộ chấm nghĩa vẫn là Qwen và có thể đánh dấu nhầm hoặc bỏ sót; không thay thế kiểm tra đầu ra. Một âm ASR gần giống không chứng minh nghĩa của từ thông dụng; điểm hỗ trợ <0.5 được trả về model sửa. Danh sách cụm từ hoàn toàn do model trích, không có danh sách riêng cho video.
8. **Cổng xác định trong code** (không phụ thuộc video; tự tắt khi video không có chữ trên màn hình):
   - đuôi file và mã có cả chữ lẫn số (vd. `.bsm`, `G2`) phải xuất hiện với đúng ranh giới token trên màn hình ở ít nhất một thời điểm;
   - chuỗi giao diện/thông báo tiếng Anh đặt trong ngoặc phải có nguyên cụm trên màn hình, không chỉ từng từ rời rạc;
   - không dùng dạng ASR mà bảng đối chiếu (độ tin cao, p≥0.8) đã chứng minh sai.
   Khẳng định bị đánh dấu được trả cho Qwen viết lại (tối đa `--verify-rounds` vòng). Tên không có trên màn hình phải bị bỏ, không thay bằng tên đoán; phần còn lại hiện trong ghi chú cần kiểm tra của tài liệu. Cổng áp dụng cả tiêu đề và caption. Sửa hẹp tối đa 3 lượt vẫn do model viết; sau mỗi lượt chấm lại khẳng định và nghĩa từ ngữ, không giữ metrics của bản trước khi sửa. `review_note` riêng lẻ không còn tự gắn trạng thái `needs_review`; trạng thái này dựa trên lỗi chưa giải quyết, thuật ngữ chưa chắc hoặc ảnh chỉ khớp một phần.

**Giới hạn ngữ cảnh**: không request nào nhận cả video. Đọc màn hình 2 ảnh/lượt (lô lỗi → đọc từng ảnh; ảnh không đọc được thì bỏ qua), bảng thuật ngữ và mục lục theo cửa sổ transcript, rà soát/viết/kiểm định theo từng mục, chỉ kèm thuật ngữ liên quan đến mục.

Schema/IDs hợp lệ không chứng minh nội dung đúng. Bộ chấm khẳng định cũng là cùng model nên có thể sai; xác suất được lưu trong `traces/verify_*.json` để đánh giá.

## Chạy

Môi trường `.venv` đã được chuẩn bị trên máy này. `run_auto.sh` thêm đường dẫn CUDA riêng cho tiến trình xử lý; không sửa môi trường các dịch vụ Qwen/TTS/embedding đang chạy.

```bash
cd /home/ai_ductran/video-to-guide
./run_auto.sh \
  --video '/đường/dẫn/video.mp4' \
  --output '/đường/dẫn/output' \
  --base http://127.0.0.1:8000/v1 \
  --model qwen38
```

Mặc định ASR dùng Whisper large-v3-turbo, GPU 0. Có thể chọn `--device cpu` khi GPU không đủ bộ nhớ. Trước khi chạy ASR GPU, đọc lại VRAM trống; thư viện/model tương thích đã được kiểm tra bằng tác vụ Whisper trên máy này. Không tự dừng các dịch vụ khác để lấy thêm VRAM.

Để thử lại cùng một video mà không chép lời lần nữa:

```bash
./run_auto.sh \
  --video '/đường/dẫn/video.mp4' \
  --output '/đường/dẫn/output-mới' \
  --transcript '/đường/dẫn/job-trước/transcript.raw.json'
```

Cache transcript phải có `media.json` cùng thư mục với cùng hash video. Tool kiểm tra hash video, hash transcript và cấu hình job. Khi đổi VERSION hoặc cấu hình CLI, dùng thư mục output mới. Prompt JSON/choose có hash để tiếp tục cùng thư mục khi cấu hình không đổi; cache glossary chưa băm đầy đủ policy/prompt/rows, cần kiểm tra hoặc vô hiệu hóa riêng khi thay logic glossary mà screen không đổi. Không sử dụng `steps.reviewed.json` của bản đã chỉnh tay.

Chạy lại cùng lệnh với cùng thư mục output sẽ tận dụng cache request của các bước đã chạy: request nào có trace với cùng hash prompt trong `traces/` thì không gọi lại model; prompt thay đổi (do sửa code hoặc đầu vào) thì gọi lại. Cả request JSON lẫn bộ phân loại logprob đều kiểm tra hash toàn bộ đầu vào trước khi dùng trace. Khi bằng chứng màn hình thay đổi, `screen_evidence.sha256` làm hết hiệu lực cache glossary, ứng viên phát âm và mục lục; bản cũ được chuyển sang `cache_previous/`, cache ASR/keyframe không đổi. Chính sách đọc lại có marker `screen_recheck_policy.txt`. Tùy chọn `--refine-from` của v3 đã bỏ.

Nếu API cần khóa, đặt biến `VIDEO_GUIDE_API_KEY`; khóa không được ghi vào trace.

## Kết quả và khả năng kiểm tra

- `guide-auto.html`: một file HTML nhúng ảnh, mục lục và lời nói gốc để đối chiếu.
- `guide-auto.pdf`: bản PDF có font tiếng Việt.
- `guide-auto.md`, `steps.json`, `document.auto.json`: nội dung và tham chiếu nguồn.
- `transcript.raw.json` (và `transcript.pass2.json` khi bật ASR lượt 2), `outline.json`, `keyframes.json`, `frames/`, `screen_text.json`, `glossary.json`: transcript, mục lục, khung hình, chữ màn hình và bảng đối chiếu.
- `steps.json`/`document.auto.json`: mỗi mục có `verification` gồm từng khẳng định, nhãn, xác suất và các khẳng định chưa giải quyết.
- `traces/`: prompt và phản hồi thực tế của Qwen, cả các lần tự sửa schema và audit. Image payload được thay bằng hash để tránh nhân bản base64; ảnh thật được lưu trong `frames/` và đánh số theo section/candidate.
- `automation_metrics.json`: số mục/thao tác/keyframe/thuật ngữ, thống kê nhãn khẳng định và số khẳng định chưa giải quyết. `human_editorial_changes` bằng 0 trong pipeline này.

Các script `review_guide_local.py` và dữ liệu `output/layout_netlist_guide/steps.reviewed.json` thuộc bản mẫu đã chỉnh tay trước đó. Pipeline tự động không gọi script đó, không nạp dữ liệu đó và không lấy ảnh đã chọn tay của bản mẫu.

PDF và HTML dùng Times New Roman nhúng sẵn. Renderer đọc font từ `~/.local/share/fonts/video-guide-times/` (`Times.TTF`, `Timesbd.TTF`); khi chuyển tool sang máy khác cần cài bộ font này.

## Unit test

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Các hàm thuần `fold`, `term_violations`, `phonetic_candidates` được kiểm tra với dữ liệu nhỏ: dấu tiếng Việt, các phụ âm dễ nhầm, ranh giới mã/đuôi file, nguyên cụm thông báo, ghép nhiều từ và loại segment ID trùng. Test không gọi model hoặc GPU.

## Trạng thái lượt sửa nội dung trước 2026-10-06 (lịch sử)

Code cuối **chưa đạt tiêu chí kiểm định nội dung và chưa chạy xong hai benchmark**. Video chính dừng ở rà nghĩa mục 9 vì phản hồi bị cắt sau cả 3 lần thử; 8/11 mục hoàn tất kiểm định nhưng prefix vẫn có .bat, tên file pg111.brd, quy tắc 3 file chung thư mục và quy tắc màu quá chung. Rà nghĩa bắt được lỗi “file tóm tắt” trong phép thử nhưng cũng bác nhầm .pad, gây hồi quy. Video không lời dừng tại mục lục vì model không sửa được các khoảng nguồn chồng nhau; nháp 3 mục không phải guide hoàn chỉnh.

Các file guide/metrics v5 đã có vẫn là bản trước lượt này; không dùng làm kết quả của code cuối. Trạng thái thật và log nằm trong `run-status.json`/`run-last.log` của từng output; báo cáo đọc/grep và ảnh ở `output/layout_netlist_auto_v5/content-audit-last-run.md`. Cổng token hiện báo unresolved nhưng chưa chặn xuất khi model không bỏ được tên sai sau scrub. Các điểm này cần được sửa trước khi coi pipeline đáng tin cậy. Người dùng yêu cầu dừng sau lượt thử, đã dừng, không commit.

## Tăng tốc (auto-v6-speed)

Whisper lượt đầu chạy đồng thời với nhánh keyframe/đọc màn hình. Sau mục lục, mỗi mục chạy toàn bộ quy trình độc lập với các mục khác; vẫn giữ bước bổ sung và kiểm định riêng, cùng số vòng sửa. Thứ tự mục trong tài liệu theo nguồn, không theo thứ tự hoàn tất. Checkpoint `document.partial.json` chỉ lưu các mục hoàn tất kiểm định; khi một mục lỗi, job giữ kết quả các mục đã hoàn tất, hủy việc chưa chạy và báo lỗi sau khi các mục đang chạy kết thúc. Trace đã có vẫn giúp tiếp tục mà không phải gọi lại request giống nhau.

```bash
./run_auto.sh --video '/đường/dẫn/video.mp4' --output '/đường/dẫn/output-mới' --parallel 3 --api-parallel 4 --asr-second-pass
```

`--parallel` mặc định 3 là số mục cùng xử lý. `--api-parallel` mặc định 4 giới hạn tổng request Qwen đang chạy của tiến trình, bao gồm các luồng chấm điểm bên trong mỗi mục. Dùng `--parallel 1` khi muốn các mục chạy tuần tự. Các cờ này không sửa cấu hình server và không giới hạn request của ứng dụng khác. Whisper vẫn cần VRAM riêng; không có bảo đảm rằng các dịch vụ trên máy dùng GPU hoàn toàn độc lập.

Khung được lấy do hết khoảng thời gian, có ảnh gần như không đổi so với khung đại diện đã đọc, có thể dùng lại observation. So sánh toàn độ phân giải RGB và từng ô nhỏ giúp tránh bỏ qua thay đổi chữ nhỏ. Nếu khung đại diện không đọc được thì khung trùng được đọc độc lập. Không bỏ ảnh gốc/IDs; ghi `reused_from` và thống kê `screen_reuse.json`. Dùng `--no-screen-reuse` để đọc mọi khung. ASR lượt hai tự bỏ qua khi không có ứng viên phát âm; lưu lý do trong `asr_second_pass.json`.

RULES/SCHEMA được đưa lên đầu prompt biên soạn, tạo prefix chung nếu server vốn bật prefix caching. Bộ phân loại đặt đáp án chung trước bằng chứng của mục và đặt câu hỏi riêng sau cùng để giữ prefix theo mục. Pipeline không đổi thiết lập cache server. Trace cùng tên được khóa và các file JSON được ghi atomically bằng temporary file riêng để an toàn khi nhiều luồng ghi.

`performance.json` được ghi khi job kết thúc, kể cả lỗi: wall time, thời gian giai đoạn, thời gian tổng API/đợi slot, số request và token API cung cấp. `cached_prompt_tokens_available` cho biết API có cung cấp số cached token hay không; không suy ra cache tắt từ giá trị 0 khi API thiếu số liệu. Các giai đoạn và request chạy song song có thể chồng nhau; không cộng các số đó thành wall time. Cache hit là số lần dùng trace JSON/choose; không bao gồm cache cấp artifact. Benchmark không dùng cache pipeline cần output mới, không truyền `--transcript`, không sao chép cache cũ. Model weights và cache server dùng chung có thể đã nóng.

18 unit test đạt cho bản này. Lượt sạch video 22:41 tại `output/layout_netlist_auto_speed_v2` đã kết thúc exit 1, **1188.931 giây (19 phút 49 giây)**. Có 12 mục lục; hai mục (2, 5) hoàn tất kiểm định, ba mục (1, 3, 4) lỗi rà nghĩa do phản hồi bị cắt hoặc cụm trích không có nguyên văn trong hướng dẫn; bảy mục chưa chạy bị hủy. Không có guide hoàn chỉnh mới. Wall time gồm thời gian để các mục đang chạy kết thúc sau lỗi đầu tiên.

Chuẩn bị nguồn 264.499s; glossary 45.536s; ASR2+glossary 91.835s; outline 34.899s; phần xử lý mục 752.160s. Đọc 144/149 frame, dùng lại 5 (3.36%). Số này thấp hơn ước tính 20–40% và không đủ chứng minh mốc 12–18 phút; chưa có baseline tuần tự sạch tương đương. API không trả số cached token, dù metrics server dùng chung có prefix hits.

Đã đọc/grep hai mục đã xong, còn 18 unresolved. Nội dung chính vẫn có `pg111.brd` trong khi ảnh đã chọn ghi `prj111.brd`; OCR cũng đọc sai pg111 nên cổng token báo 0. Quy tắc màu chưa giới hạn đầy đủ ở mọi trường. Các mục quan hệ file/Export/pin chưa hoàn tất; không lấy số 0 .bat/tóm tắt trong hai mục không liên quan để coi audit đã đạt. Các thay đổi tốc độ không giải quyết các lỗi chất lượng cũ.

Chi tiết đo và bằng chứng nội dung: `output/layout_netlist_auto_speed_v2/benchmark-report.md`; số liệu máy đọc được ở `performance.json`, `run-status.json`, checkpoint ở `document.partial.json`, log ở `run-last.log`. Lượt v1 đã dừng để sửa thứ tự prefix, được giữ riêng và không coi là benchmark hoàn chỉnh. Đã dừng sau lượt cuối, không còn tiến trình pipeline, chưa commit.

## Giao diện web để test

Chạy `.venv/bin/python web_app.py --host 127.0.0.1 --port 7860`, mở `http://127.0.0.1:7860` trên máy chạy repo. Giao diện ở `web_ui.html`, server dùng thư viện chuẩn Python, không cần cài thêm framework.

Chọn video có sẵn hoặc tải video lên (tối đa 10 GB), chọn ngôn ngữ, `parallel`, `api-parallel` và ASR lượt hai, rồi bấm **Tạo tài liệu**. Web chỉ bắt đầu pipeline khi bấm nút; dùng `run_auto.sh` và output riêng `output/web_<job-id>`. Log trực tiếp ở giao diện và `web-run.log`; mở/tải HTML/PDF/Markdown khi tạo thành công. Thư viện kết quả hiển thị các guide cũ với thời gian file, không coi chúng là đầu ra benchmark cuối. Nội dung hiện vẫn có thể sai, cần đối chiếu video.

Web cho một job hoạt động mỗi lần và kiểm tra pipeline CLI bằng pgrep đường dẫn đầy đủ để tránh khởi chạy chồng. Upload nằm ở `output/web_uploads`; chỉ phục vụ file trong output. Đã kiểm tra HTTP trang chính/API danh sách/guide trả 200, job video sai trả 400, đường dẫn ngoài output trả 403. Không khởi chạy thêm pipeline trong phép thử web.

Mặc định chỉ bind localhost. Auto-review đã từ chối lần thử bind `0.0.0.0` vì phạm vi mạng rộng hơn quyền hiện có; server đang chạy theo phương án `127.0.0.1`, không mở LAN. Dịch vụ Qwen/TTS/embedding không thay đổi. Chưa commit.

Người dùng sau đó đã yêu cầu mở LAN tại **http://192.168.2.230:9322**. Web hiện chạy bằng `.venv/bin/python web_app.py --host 192.168.2.230 --port 9322`, đã kiểm tra trang và API danh sách trả 200; web localhost cũ đã dừng. Mặc định CLI vẫn là localhost.

## Tab Ảnh + mô tả → Excel

Mở `http://192.168.2.230:9322/#excel`. Chọn bộ dữ liệu có sẵn hoặc nhập đường dẫn thư mục trong repo, bấm **Kiểm tra dữ liệu**, rồi **Ghép ảnh và tạo Excel**. Thư mục cần có một mẫu `.xlsx`, một file mô tả `.txt` UTF-8, một `.pdf` và ảnh `.jpg/.png/...` (có thể trong thư mục con). Nếu có nhiều file cùng loại, dùng các ô chọn file riêng (đường dẫn tương đối trong bộ dữ liệu). Giao diện hiện dùng đường dẫn thư mục trên máy; chưa có upload cả bộ dữ liệu Excel qua ZIP.

Luồng `excel_guide.py` đọc tối đa hai ảnh mỗi request và giới hạn hai request đồng thời. Qwen mô tả ảnh, xác định vùng hình/bảng trong từng trang PDF, ghép mô tả với ảnh, chọn ảnh kết quả rồi đối chiếu từng cặp bằng ảnh thật. JSON Schema giới hạn mảng và độ dài văn bản để tránh model liệt kê số thước vô hạn; không sửa cấu hình vLLM. Thứ tự mô tả, mã và số đo gốc được giữ nguyên. Phần không đủ bằng chứng được ghi chú cần đối chiếu; ảnh không liên quan theo kiểm định bị bỏ khỏi cặp. Không tự thay đơn vị hoặc mã vật tư.

- Sheet 1–2 và các sheet khác ngoài 3–5 giữ nguyên. Xuất bằng thay các worksheet 3–5 trong ZIP XLSX, thêm style/media mới; các phần còn lại được so byte và các style cũ được giữ nguyên.
- Sheet 3: mô tả bên trái, ảnh bên phải, hàng ảnh cùng chiều cao, ảnh giữ tỉ lệ; nhóm theo tiêu đề nguồn, ngắt trang giữa bước, ghi chú ở cuối.
- Sheet 4: mô tả kết quả, kết quả quan sát và ảnh thành phẩm tương ứng, ưu tiên nhóm ảnh cuối khi phù hợp. Không xác nhận đạt kiểm tra điện chỉ bằng ảnh.
- Sheet 5: ảnh toàn trang PDF cùng các vùng hình/bảng được cắt từ trang gốc; ảnh nhúng gốc cũng được trích vào assets. Bản toàn trang giữ đủ thông tin ngay cả nếu crop chưa chính xác. Dàn trang A3 ngang cho bản vẽ.

Header/logo lấy từ mẫu, các sheet mới dùng Arial và khoảng cách đồng đều. Phạm vi in/tên hàng tiêu đề của sheet 3–5 được cập nhật riêng; không thay print definitions của sheet 1–2. Không ghi đè file mẫu.

CLI:

```bash
.venv/bin/python excel_guide.py --folder tests/794940_B --output output/excel_794940_b_v1
```

File mẫu thử thật: `output/excel_794940_b_v1/794940_B_huong_dan.xlsx`. Có 10 bước, 1 mục kết quả, đọc 30 ảnh, PDF 1 trang; sheet ẩn thứ sáu được giữ nguyên. `preservation-check.json` xác nhận 40 phần gốc không đổi byte, worksheet 1–2 không đổi, style cũ giữ nguyên. Đã so toàn bộ 18 đoạn mô tả với nguồn và kiểm tra số đo/mã vật tư trong XLSX. Mẫu giữ mã 794941 ở sheet 1–2; sheet mới dùng 794940, có ghi chú khác mã. 11 mục bước/kết quả vẫn cần đối chiếu vì ảnh không xác nhận được đầy đủ tool/số đo/định danh; không coi tạo file thành công là kiểm định sản xuất đạt.

Output gồm `matching-plan.json` (mô tả gốc, ảnh được ghép, kết quả kiểm định), `image-observations.json`, `pdf-images.json`, `assets/`, `traces/`, `excel-result.json` và XLSX. Có cache theo prompt/schema và hash nguồn; thay nguồn thì dùng output mới. Web tạo output riêng `output/excel_web_<id>`, lưu job metadata để xem tiến độ sau khi web restart. Một tác vụ video hoặc Excel hoạt động mỗi lần; job CLI cũng được kiểm tra bằng pgrep đường dẫn đầy đủ. Restart web không dừng các job con.

Đã kiểm tra HTTP tab/API inspect/results, cú pháp JavaScript, test bảo toàn mẫu/công thức/ảnh/sheet ẩn và test launch/recover job Excel. Tổng 21 unit test đạt theo các lượt kiểm tra. Các thư viện thêm: openpyxl, lxml, PyMuPDF (đã ghi phiên bản trong requirements-local.txt). Chưa commit.


### SemIf cho ghép ảnh Excel (2026-10-06)

Theo yêu cầu dùng SemIf, `semif_score.py` dùng nguyên bản `direct_messages`, validation và conditional softmax từ `vendor/semif_phase1/core.py` (MIT; revision/hash trong `UPSTREAM.json`). Transport chỉ gọi Qwen đang chạy: một token, temperature 0, top_logprobs 20, thinking off; thêm ảnh thật vào user content. Không nạp model khác, không chỉnh server. Token đáp án phải khớp chính xác A/B/C/D; không strip rồi gộp token khác. Không thấy token lựa chọn thì điểm bằng 0 và bác, không dùng phân phối đều làm bằng chứng.

- Ghép bước: điểm A >= 0.65, A phải thắng; riêng xác nhận toàn bộ tool/số đo/mã/hướng dùng ngưỡng 0.85. Không đủ xác nhận chi tiết thì đánh dấu cần đối chiếu dù ảnh có thể minh họa phù hợp.
- Ảnh kết quả: tổng điểm A (tổng thể) + B (cận cảnh) >= 0.65, đáp án thắng phải thuộc A/B. So ảnh ứng viên với PDF, xét đối tượng kết quả chính; không yêu cầu chứng minh mọi công đoạn hay kiểm tra điện. Model chỉ chọn trong tập qua cổng và viết mô tả quan sát.
- Các cổng yêu cầu observed_option_mass >= 0.01. Đây là khối lượng xác suất API thực sự trả cho các chữ lựa chọn; điểm conditional softmax **chưa hiệu chuẩn**, không phải xác suất đúng thực tế.
- Cặp bước bị bác được model đề xuất tối đa 4 ứng viên khác từ catalog; code chấm từng ảnh thật bằng SemIf, giữ tối đa 2 ảnh qua ngưỡng. Không có ảnh qua thì giữ mô tả nguồn, ghi chưa có ảnh phù hợp, không hạ ngưỡng để ép ghép.
- JSON model viết `fit`/`stage` không được vượt quyết định của SemIf. Trace lưu request đã hash URL ảnh, top_logprobs, scores, observed_option_mass và revision upstream. `matching-plan.json` giữ checks, ngưỡng và điểm; preview web hiển thị điểm/giữ/bác. Tối đa 2 request đồng thời, tối đa 2 ảnh một request.

Chạy mẫu: `.venv/bin/python excel_guide.py --folder tests/794940_B --output output/excel_794940_b_semif_v1`. Bản `excel_794940_b_v1` là lượt trước SemIf. 27 unit test đạt, gồm kiểm tra conditional softmax, thiếu option mass, ngưỡng và việc JSON free-form không thể vượt cổng SemIf.

Kết quả mẫu SemIf cuối: 6/10 bước có ảnh, 4 bước chưa qua ngưỡng (TXT_002/005/006/011), giữ mô tả và báo thiếu ảnh. Sheet 4 IMG_024 + IMG_029; 18 đoạn nguồn nguyên văn trong XLSX, 40 phần ZIP gốc không thay giữ nguyên, sheet 1–2 và sheet ẩn được đối chiếu. Còn 11 mục cần kiểm tra chi tiết và OCR metadata PDF cần đọc lại. Báo cáo `output/excel_794940_b_semif_v1/semif-audit.md`. Link tải mẫu: `http://192.168.2.230:9322/files/excel_794940_b_semif_v1/794940_B_huong_dan.xlsx`. Nút Xem ghép ảnh / điểm SemIf trong danh sách kết quả xem cả cặp được giữ/bị bác.


### Upload và ghép ảnh theo bố cục bảng riêng — lịch sử v6

Mở tab Excel tại `http://192.168.2.230:9322/#excel`. Chọn mẫu `.xlsx`, mô tả `.txt` UTF-8, PDF và các ảnh cần dùng (chọn nhiều file hoặc cả thư mục ảnh). Bấm **Upload bộ file**, sau đó **Ghép ảnh và tạo Excel**; nút tạo cũng có thể tự upload bộ đã chọn. Không cần nhập đường dẫn máy chủ; trang không tự chọn dữ liệu demo.

Yêu cầu mới nhất: sheet 3 bám bảng của mẫu với ITEM, PART, MÀU, Cắt (In/mm), Tool tuốt và kích thước tuốt trái/phải (in/mm). Mỗi bước thao tác có đúng một ảnh được Qwen38 chọn từ ảnh thực tế; không cần dùng hết ảnh và ảnh được phép dùng lại khi hợp lý. Qwen38 đọc ảnh và chọn cặp; SemIf không loại ảnh khỏi các dòng. Trường số đo/tool/mã không có nguồn rõ để trống. Nhóm Đầu dây A/B được giữ cùng mô tả. Ảnh và mô tả ở hai vùng có viền, thẳng hàng cùng dòng. Sheet 4 giữ Mô tả/Kết quả dưới header/logo gốc; sheet 5 giữ trang PDF và vùng cắt.

Header/logo gốc của sheet 3/4 giữ nguyên. Sheet 1–2 và sheet ẩn không đổi. Không ghi cảnh báo tự sinh hoặc dòng “cần đối chiếu/chưa có ảnh” trong ô nội dung. Các cảnh báo về số đo/tool/mã không chứng minh được chỉ ở metadata. Không đổi đơn vị hay tự suy ra đầu A/B là trái/phải. Upload hỗ trợ mỗi file tối đa 512 MB, tổng bộ 2 GB; ảnh trùng tên lưu riêng. Chỉ nút tạo Excel mới chạy model.

Lượt thật cuối qua bộ upload `b3fc336ddcaa4806b8d702f33754302d`, job `20261006_060852_72c92afd`, version `excel-guide-v6-qwen-step-photos`: 10/10 dòng thao tác có một ảnh, mô tả nằm cùng hàng, model trace ghi `qwen38`. Header B:K của mẫu khớp; logo/header sheet 3/4 giữ nguyên anchor và SHA-256; sheet 1–2 byte-identical, 40 phần ZIP gốc còn nguyên. Kiểm tra trực tiếp: 27.6 ở cột cắt, 0.38 ở tuốt phải, 0.1 ở tuốt trái. Workbook: `output/excel_web_20261006_060852_72c92afd/b3fc336ddcaa4806b8d702f33754302d_huong_dan.xlsx`; báo cáo layout `output/excel_web_20261006_060852_72c92afd/native-layout-audit.md`. Web tại `http://192.168.2.230:9322/#excel`, job/API và download link đều HTTP 200. Các ảnh không xác nhận đủ số đo/tool vẫn có trong hàng theo yêu cầu, nhưng chưa chứng minh được chi tiết đó. 12 kiểm thử Excel/ghép ảnh và tiện ích, cùng kiểm tra cú pháp Python, đạt. Chưa commit.


### Bố cục nguyên mẫu với textbox nổi — hiện hành 2026-10-08

Bản v7 thay bố cục v6: đọc cả floating textboxes trong mẫu, giữ bảng cắt dây phía trên, tiêu đề ĐẦU TRÁI/ĐẦU PHẢI và chữ phía trên ảnh trong hai vùng gốc. Chỉ căn lại hàng/cột và khoảng cách cho thẳng; không thêm cột HÌNH ẢNH/MÔ TẢ cạnh bảng dây. Sheet 4 dùng caption/ảnh theo bố cục nổi của mẫu, không thêm bảng riêng. Header/logo và sheet 1–2 vẫn giữ nguyên. Upload và các nút web dùng như trước; Qwen38 đọc/chọn ảnh, không cần dùng hết ảnh.

`excel_template_layout.py` đọc nguyên mẫu OOXML, Qwen xác định bảng và vùng/caption/nhóm; schema typed riêng từng bảng chỉ lấy giá trị nguyên văn nguồn có ý nghĩa đúng cột. Không có nguồn thì để trống; bảng nhãn không có dữ liệu được bỏ. Textbox sao chép font/paragraph, cập nhật anchor và xfrm; mô tả dài được tăng chiều cao, mỗi cặp hai bên chung hàng chữ và ảnh. Bảng vật tư giữ merges/style gốc và tăng chiều cao cho ghi chú nguồn. Ảnh giữ tỉ lệ.

File mới: `output/excel_template_aligned_20261008/b3fc336ddcaa4806b8d702f33754302d_huong_dan.xlsx`. Đã kiểm tra nội dung/XML thực tế: 18 đoạn nguồn, 10 bước có ảnh, 4 cặp trái/phải căn cùng hàng, tiêu đề cùng hàng, bảng cắt đúng cột; header/logo và sheet 1–2/ẩn giữ nguyên. Chi tiết `native-layout-audit.json` và `.md` cùng thư mục. 10 test Excel đạt, gồm kiểm tra textbox/style và căn hàng với chữ dài/ngắn. Bản dựng ảnh OOXML đã được xem; cần người dùng mở Excel để xác nhận hiển thị trong ứng dụng thực tế.

Tải tại `http://192.168.2.230:9322/files/excel_template_aligned_20261008/b3fc336ddcaa4806b8d702f33754302d_huong_dan.xlsx`. Trang web/results/download trả HTTP 200, kết quả v7 đã có trong danh sách. Không thay dịch vụ dùng chung, chưa commit; dừng tác vụ sau lượt này, web giữ mở. Các vấn đề chất lượng video trước đó chưa được luồng Excel này giải quyết.
