# Bàn giao: pipeline video → tài liệu hướng dẫn có ảnh (auto-v6-speed)

Cập nhật: 2026-10-08. Repo: `/home/ai_ductran/video-to-guide`, nhánh `main`. **Chưa commit**: toàn bộ thay đổi nằm trong working tree.

## Mới nhất 2026-10-08: giữ bố cục gốc, chỉ căn thẳng hàng

Người dùng bác bố cục v6: không muốn thêm cột HÌNH ẢNH/MÔ TẢ cạnh bảng dây. Mẫu thật có chữ trong floating textboxes, bảng cắt dây ở trên và hai vùng ĐẦU TRÁI/ĐẦU PHẢI bên dưới; chữ nằm trên ảnh. Những textbox này bị mất khi chỉ đọc/xuất ô bằng openpyxl. Yêu cầu hiện tại thay thế các bố cục lịch sử bên dưới.

`excel-guide-v7-native-floating-layout`: thêm `excel_template_layout.py` để đọc và sao chép textbox OOXML gốc, giữ font/paragraph, căn lại anchor và xfrm đồng bộ. Qwen38 nhận catalog ô/textbox cùng PDF để xác định bảng, tiêu đề, vùng trái/phải và phân nhóm thao tác; code kiểm tra IDs/ranges. Giữ bảng cắt dây và bảng vật tư theo merges/style mẫu, không tạo bảng mô tả/ảnh mới. Caption giữ nguyên văn nguồn, nằm trên ảnh; từng cặp trái/phải dùng chung hàng caption và hàng ảnh dù độ dài chữ khác nhau. Giữ nhóm A/B nguồn; model dùng PDF để gán bên. Sheet 4 dùng caption nổi và ảnh bên dưới theo mẫu gốc, không thêm bảng Mô tả/Kết quả riêng. Sheet 5 không đổi luồng.

Trích ô bảng dùng schema typed riêng cho từng bảng, giới hạn nguồn: step/group cho bảng dây, note cho vật tư. Trước đó schema ô tùy ý làm model đưa mã bộ sản phẩm vào PART và kích thước tuốt vào bảng nhãn. Bản mới yêu cầu trường có nghĩa cụ thể, kiểm tra giá trị là chuỗi nguyên văn nguồn, không dùng metadata làm wire part; không có dữ liệu nhãn thì bỏ bảng nhãn. Không suy đơn vị, không chèn dữ liệu mẫu cũ, không sửa tay nội dung đầu ra. Qwen38 vẫn chọn ảnh; SemIf không loại ảnh khỏi bước, không bắt dùng hết ảnh.

Đầu ra mới: `output/excel_template_aligned_20261008/b3fc336ddcaa4806b8d702f33754302d_huong_dan.xlsx`, nguồn bộ upload `b3fc336ddcaa4806b8d702f33754302d`. Cache ảnh/ghép được dùng lại; structural/table prompts mới có trace riêng. Đã kiểm tra trực tiếp XLSX và drawing XML: 18/18 đoạn nguồn có mặt; 10/10 bước có ảnh ngay dưới caption; 4 cặp bước trái/phải có cùng hàng caption/ảnh, bước cuối bên phải đứng riêng; tiêu đề trái/phải cùng hàng. Header bảng B7:K8 khớp giá trị/font/fill/border mẫu, E9=27.6, G9=11.M.129, H9=0.1, I9=0.38, PART chưa có nguồn để trống. Không có cột mô tả/ảnh tự thêm, không có cảnh báo tự sinh trong nội dung. Header rows 1–4/column widths/sheetFormatPr và logo bytes/anchor sheet 3/4 giữ nguyên; sheet 1/2 và sheet ẩn byte-identical. Báo cáo `native-layout-audit.json` và `.md`; log `excel-run.log`.

10 kiểm thử `test_excel*.py` đạt, gồm 2 test mới về bảo toàn textbox/style và căn hàng khi mô tả dài/ngắn khác nhau. Đã xem bản dựng ảnh kiểm tra từ OOXML (không phải ảnh chụp Excel); chưa xác nhận hiển thị bằng Excel của người dùng, cũng chưa chứng minh số đo/tool trên ảnh vốn không rõ. Web hiện có tại `http://192.168.2.230:9322/#excel`, trang/results/link XLSX đều HTTP 200 và danh sách nhận version v7. Không restart web/model/TTS/embedding, chưa commit. Lượt pipeline đã kết thúc, giữ web mở và dừng sau lượt này.

## Lịch sử v6: bố cục bảng riêng và Qwen38 ghép ảnh từng bước

Người dùng yêu cầu sheet 3 bám bố cục mẫu, giữ bảng ITEM/PART/MÀU/Cắt (In/mm)/Tool tuốt/kích thước tuốt trái/phải (In/mm), đồng thời mỗi mô tả thao tác phải có một ảnh. Không cần dùng hết ảnh. Dùng Qwen38 đọc ảnh và chọn ảnh gần nhất cho từng bước; không để SemIf loại ảnh khỏi dòng. Các số đo/tool/mã không có bằng chứng vẫn để trống trong các cột tương ứng. Sheet 4 theo header/logo gốc với Mô tả/Kết quả; sheet 5 giữ trang PDF/crop. Không ghi cảnh báo hay “cần đối chiếu/chưa có ảnh” vào ô nội dung.

`excel-guide-v6-qwen-step-photos` thêm vùng HÌNH ẢNH và MÔ TẢ THAO TÁC cạnh bảng dây; mỗi bước nằm trên một hàng có viền, nhóm “Đầu dây A/B” đi cùng mô tả, ảnh giữ trong cột riêng. Header gốc B:K và header/logo ở hàng 1–4 không đổi. Qwen38 đọc ảnh thành các lô nhỏ rồi chọn ảnh cho từng bước từ contact sheet và catalog thị giác; ảnh có thể dùng lại khi phù hợp, không bắt buộc dùng hết ảnh. Qwen38 cũng chọn ảnh kết quả sheet 4. Giá trị dây chỉ do model trích khi nguồn/PDF nêu rõ, không đổi đơn vị. SemIf còn trong các tiện ích lịch sử nhưng không quyết định cặp ảnh của job này.

Job kiểm tra: `20261006_060852_72c92afd`. Workbook `output/excel_web_20261006_060852_72c92afd/b3fc336ddcaa4806b8d702f33754302d_huong_dan.xlsx`. Đã đọc lại workbook: 10/10 dòng thao tác có đúng một ảnh; header trái/phải gốc khớp mẫu; các ảnh căn ở cột L:M và mô tả ở N:R cùng hàng; 27.6 nằm ở cột cắt, 0.38 ở kích thước tuốt phải, 0.1 ở kích thước tuốt trái. Không có cảnh báo tự sinh trong ô. Sheet 1–2 byte-identical, 40 phần ZIP gốc được giữ nguyên, logo/header sheet 3/4 khớp cả anchor và SHA-256. Qwen38 là model trong trace ghép ảnh. Còn các trường hợp ảnh không thể chứng minh số đo/tool; các cảnh báo này chỉ nằm metadata JSON, không nằm trên sheet. 12 kiểm thử Excel/ghép ảnh và tiện ích đạt, cú pháp Python đạt. Web `http://192.168.2.230:9322/#excel`, API job/results và tải XLSX đều trả HTTP 200; cổng đang được server có sẵn sử dụng nên không khởi thêm bản web thứ hai. Chưa commit.

## Yêu cầu mới: upload, dùng hết ảnh, giữ header/logo (2026-10-06)

Yêu cầu sau cùng của người dùng thay chính sách bỏ ảnh theo ngưỡng: mọi ảnh đều liên quan đến mô tả và phải dùng hết, không có phần ảnh không liên quan. `excel-guide-v4-upload-all-header`: model gắn mỗi ảnh còn thiếu vào bước mô tả phù hợp nhất, kiểm tra đủ IDs; nhiều ảnh/bước được chia hàng tiếp, tối đa hai ảnh/hàng. SemIf vẫn chấm để lưu bằng chứng, **không loại ảnh khỏi workbook vì điểm thấp**. Điểm/trace chỉ nằm ở JSON và mục chi tiết web; không chèn đoạn “cần đối chiếu” hoặc “chưa có ảnh” vào Excel. Ô thiếu ảnh để trống. Chỉ giữ ghi chú gốc từ TXT, không chèn warnings tự sinh vào nội dung. Không sửa tay đầu ra.

Header sheet 3–5 giữ nguyên các hàng 1–4, merges, column widths, sheetFormatPr và các đối tượng logo/header có anchor trong bốn hàng đầu bằng OOXML. Header/mã/logo gốc không đổi kể cả khi metadata đầu vào khác. Sheet 1–2 và sheet ẩn vẫn giữ nguyên. Nội dung dưới header mới xếp lại, màu xám/trắng; UI cũng giảm màu.

Web upload mẫu XLSX, TXT UTF-8, PDF và nhiều ảnh hoặc cả thư mục ảnh; không tự chọn dataset có sẵn khi mở trang. API `/api/excel/uploads` tạo phiên; POST `/api/excel/uploads/<id>` nhận từng file raw với X-Role/X-Filename; POST `/api/excel/uploads/<id>/complete` xác nhận đủ bộ. Kiểm tra nội dung file thật, tên/path, upload thiếu, trùng loại, 512 MB/file và 2 GB/bộ; ảnh trùng tên vẫn lưu riêng. Dữ liệu ở `output/excel_uploads/<id>`. Nút Ghép ảnh có thể tự upload bộ đã chọn. Bộ máy chủ cũ chỉ là tùy chọn trong details.

31 unit test đạt, gồm upload một bộ mới, tên Unicode/trùng tên, file hỏng/path/thiếu file, giữ ảnh bị điểm thấp, nhúng toàn bộ ảnh thật vào XLSX và bảo toàn header/logo. Web đã nạp lại riêng, session 34898, tại `http://192.168.2.230:9322/#excel`; không sửa/restart model/TTS/embedding. Upload HTTP đủ 33 file và job mới `20261006_050659_664ec104` đã completed, nguồn upload `b3fc336ddcaa4806b8d702f33754302d`. Kết quả `output/excel_web_20261006_050659_664ec104/b3fc336ddcaa4806b8d702f33754302d_huong_dan.xlsx`: đủ 30/30 IDs và hashes ảnh trong ZIP, 10/10 bước có ảnh; sheet 3/4/5 lần lượt 30/3/8 ảnh kể cả logo (có ảnh dùng ở hơn một bước). Sheet 4 IMG_024 + IMG_030. Header rows 1–4/cols/sheetFormatPr canonical XML và logo bytes/anchor/ext so khớp mẫu; sheet 1–2 byte-identical và sheet ẩn nguyên bản. 18 đoạn nguồn có trong workbook: mã nguồn riêng ở nội dung A7, header vẫn giữ mã mẫu. Không có cảnh báo tự sinh trong ô nội dung. Sau kiểm tra metadata, chỉ ghép lại workbook qua hàm xuất từ plan model đã có; không gọi thêm model, không chỉnh tay đầu ra. Báo cáo `upload-all-photos-audit.md` trong output job. API/upload/trạng thái/download đã kiểm tra; JS/Python hợp lệ, 31 test đạt. Dừng chạy job sau lượt này, web giữ mở. Chưa commit.

## Bổ sung theo yêu cầu dùng SemIf (2026-10-06)

Đã chuyển quyết định ghép ảnh Excel sang SemIf thực sự: vendor core MIT nguyên bản từ dự án Phu-main, upstream commit `23cf1f39fc9534fe81437200959b6dfc7106e45a`, với transport ảnh/vLLM riêng `semif_score.py`. Ngưỡng ghép 0.65; xác nhận đầy đủ chi tiết 0.85; observed option mass tối thiểu 0.01. JSON fit/stage không được vượt cổng logprob. Ảnh bước bị bác được đề xuất tối đa 4 ứng viên khác rồi chấm ảnh thật; vẫn không đạt thì để thiếu ảnh và ghi cần đối chiếu. Điểm chưa hiệu chuẩn, không phải xác suất đúng. Trace/ngưỡng trong matching-plan và preview web, chi tiết AUTOMATION.md. Không đổi model/server, không commit. 27 unit test đạt.

Lượt mẫu mới: `output/excel_794940_b_semif_v1`, log `/tmp/excel-semif.log`. Job cuối completed. Đã so 18 đoạn nguồn nguyên văn trong plan và workbook, kiểm tra XML/drawings và toàn bộ giá trị sheet 1–2 giữ nguyên, sheet ẩn còn nguyên. 6/10 bước có ảnh qua ngưỡng; 4 bước chưa ghép được (TXT_002/005/006/011). Sheet 4 chọn IMG_024 tổng thể và IMG_029 cận cảnh, mô tả quan sát không khẳng định mã J908 đã đọc trên ảnh. Sheet 5 toàn trang + 6 crop. Còn 11 mục cần đối chiếu tool/số đo/mã; metadata PDF OCR đọc khác nguồn, chưa xác minh. Không coi là ghép đúng hoàn toàn. Báo cáo `output/excel_794940_b_semif_v1/semif-audit.md`, traces và preservation-check. Web/API/link XLSX và plan trả 200; nút Xem ghép ảnh / điểm SemIf có trên web. 27 test và cú pháp JS/Python đạt. Dừng chạy job sau lượt này; web tiếp tục chạy để người dùng test.

## Luồng mới: ảnh + mô tả + PDF → Excel mẫu (2026-10-06)

Người dùng yêu cầu thêm tab mới với dữ liệu `tests/794940_B`; xác nhận sheet 4 phải có mô tả, kết quả và ảnh sản phẩm tương ứng (thường nhóm ảnh cuối). Đã thêm `excel_guide.py`, hai test Excel và một test web Excel; cập nhật `web_app.py`/`web_ui.html`. Web tại `http://192.168.2.230:9322/#excel`, session 87705, nạp lại riêng web, không restart model/TTS/embedding. Job video cũ vẫn đọc được trạng thái sau restart.

- 30 ảnh, mô tả UTF-8 18 đoạn, PDF một trang ảnh scan, mẫu 5 sheet chính + sheet ẩn. Luồng generic, không viết cứng mã/tool/số đo của bộ dữ liệu trong thuật toán.
- Qwen đọc ảnh từng lô tối đa 2, chọn ghép nguồn và kiểm định bằng ảnh thật; tối đa 2 request đang chạy. JSON Schema có maxItems/maxLength. Lượt đầu thất bại vì model đọc thước rồi liệt kê số tới hàng trăm; đã xử lý bằng grammar giới hạn thực sự, không chỉ nhắc prompt; không đổi server. Kết quả ghép/caption/notes do model viết, mô tả và số đo lấy nguyên văn từ file nguồn.
- Đã tạo `output/excel_794940_b_v1/794940_B_huong_dan.xlsx`: sheet 3 có 10 bước, sheet 4 có mô tả/kết quả/ảnh thành phẩm, sheet 5 có toàn trang PDF và 6 crop. Header/logo và bố cục hàng đồng đều, ảnh giữ tỉ lệ, ngắt trang giữa bước, print definitions sheet mới riêng; PDF dùng A3 ngang.
- Sheet 1–2 XML/relationships/drawings/media giữ nguyên; các phần ZIP không thay được so byte, style gốc được so canonical XML. `preservation-check.json`: 40 phần gốc giữ nguyên, sheet1/2 byte-identical, style cũ không đổi. Sheet ẩn thứ sáu giữ nguyên. So toàn bộ 18 đoạn mô tả và các số/mã trong workbook đã đạt. Mẫu ghi 794941, đầu vào 794940: giữ mã cũ ở sheet1/2, sheet3–5 dùng mã nguồn và ghi khác biệt.
- Có 11 mục cần đối chiếu (tool/chiều/số đo/định danh không nhìn rõ trong ảnh). Tạo XLSX thành công không chứng minh mọi ghép ảnh đã được xác nhận sản xuất. Không tự đổi 0.25m sang đơn vị khác. Chưa có UI chỉnh lại cặp ảnh hay upload ZIP; dùng đường dẫn thư mục và xem preview cặp ghép sau job.
- Web kiểm tra dataset, chạy job, log, preview và tải XLSX. Chặn job chạy chồng video/Excel cả CLI; metadata job mới được lưu để phục hồi khi web restart. Dataset path giới hạn trong repo. CLI `./.venv/bin/python excel_guide.py --folder tests/794940_B --output output/<job>`; file input nhiều cùng loại thì truyền template/description/pdf/images tương đối. Chi tiết ở AUTOMATION.md.
- Đã chạy 20 test chung đạt, test web Excel bổ sung đạt (tổng 21); cú pháp JS/Python và các API được kiểm tra. Requirements bổ sung openpyxl/lxml/PyMuPDF. Chưa commit, file mẫu và dữ liệu nguồn không chỉnh tay. Các lỗi pipeline video cũ vẫn còn, không coi luồng Excel này là đã sửa pipeline video.

## Giao diện web được người dùng yêu cầu sau lượt tăng tốc

Đã thêm `web_app.py` + `web_ui.html`, đang chạy tại `http://192.168.2.230:9322` (session 91322), theo yêu cầu LAN rõ ràng sau đó của người dùng. Chạy lại bằng `.venv/bin/python web_app.py --host 192.168.2.230 --port 9322`. Web localhost cũ đã được dừng riêng. Giao diện chọn/tải video, chỉnh concurrency/ngôn ngữ/ASR2, chạy pipeline mới qua run_auto.sh, xem log và tải kết quả. Chỉ khởi chạy khi người dùng bấm nút; mỗi job có output mới `output/web_<id>`, uploads ở `output/web_uploads`. Web chặn job đồng thời và kiểm tra pipeline CLI bằng pgrep đường dẫn đầy đủ. HTML cũ trong danh sách chỉ là lịch sử, không coi là guide từ benchmark failed.

Auto-review từ chối bind 0.0.0.0 (đọc video và launch pipeline ra toàn mạng chưa được cho phép). Ban đầu dùng localhost; sau đó người dùng yêu cầu rõ `192.168.2.230:9322`, đã bind đúng địa chỉ/cổng này và kiểm tra trang/API đều 200. Không mở forwarding. Kiểm tra trang/API/guide 200, job video không hợp lệ 400, path traversal 403. Không chạy thêm GPU job khi test web, không đổi dịch vụ dùng chung, chưa commit. Khi kết thúc lượt chat web tiếp tục chạy để người dùng test; pipeline benchmark trước vẫn đã dừng.

## Lượt tối ưu tốc độ 2026-10-06 — đã kết thúc, benchmark lỗi

Sau khi dừng lượt sửa nội dung trước, người dùng đã yêu cầu tiếp tục riêng các cách tăng tốc 1–5 và chạy một lượt sạch video chính 22:41. Yêu cầu mới cho phép lượt này; yêu cầu dừng bên dưới là lịch sử của lượt trước. Chưa commit, không đổi hoặc restart dịch vụ dùng chung.

- VERSION `auto-v6-speed`; `--parallel` mặc định 3 mục, `--api-parallel` mặc định 4 request Qwen đang chạy cho toàn pipeline (bao gồm các pool chấm điểm lồng nhau). Mỗi mục đi qua viết → completeness → deepen → grounding → đủ vòng verify/revise/scrub. Không gộp kiểm định và không giảm vòng sửa. Checkpoint chỉ chứa mục hoàn tất kiểm định, sắp theo thứ tự nguồn; một mục lỗi thì hủy những future chưa chạy, chờ mục đã chạy và giữ checkpoint rồi báo lỗi.
- Whisper lượt đầu chạy cùng nhánh keyframe/đọc màn hình/đọc lại chữ. Không giả định GPU hoàn toàn tách khỏi vLLM; giới hạn request chỉ áp dụng cho client này.
- Chỉ khung định kỳ gần như không đổi mới dùng lại observation; so RGB toàn độ phân giải và từng ô 32 pixel với khung đại diện đã được đọc (không nối chuỗi sai lệch). Vẫn giữ tất cả ảnh và IDs; observation được deep copy và ghi `reused_from`. `screen_reuse.json` ghi số khung thật sự đọc; `--no-screen-reuse` để tắt.
- Không có ứng viên phát âm thì không chạy ASR lượt hai dù có glossary; lý do ghi `asr_second_pass.json`.
- Các prompt biên soạn đưa RULES + SCHEMA giống hệt lên đầu. Bộ phân loại đưa đáp án chung trước, rồi bằng chứng của mục, rồi câu hỏi/khẳng định riêng, giữ prefix bằng chứng giữa các lần chấm cùng mục. Không bật/tắt prefix cache của server. Không cam kết cache server có hiệu lực; `cached_prompt_tokens` chỉ ghi phần usage API cung cấp; `cached_prompt_tokens_available` phân biệt không có số liệu với cache thật sự bằng 0. Metrics server đọc riêng có prefix-cache hits, nhưng đó là toàn server dùng chung, không phải mức tiết kiệm của job.
- Trace cùng tên được khóa trong tiến trình để không gọi trùng khi các luồng gặp cùng cache; JSON ghi bằng temporary file riêng rồi replace atomically. CLI probe dùng cùng transport initializer.
- 18 unit test đạt, gồm 6 hàm thuần cũ và 12 kiểm tra tốc độ/luồng: giới hạn API, ASR và ảnh cùng chạy, giữ đủ vòng sửa, checkpoint/thứ tự, cache cùng request, thay đổi chữ nhỏ, reuse độc lập và ghi JSON đồng thời. Không gọi model/GPU trong test.
- Benchmark sạch cuối đã kết thúc (exit 1) ở `output/layout_netlist_auto_speed_v2`, không truyền transcript và thư mục mới trước khi chạy. Log tạm `/tmp/video-guide-speed-v2.log`. Model weights và prefix cache của server có thể đã nóng; không xóa cache server dùng chung. `performance.json` ghi wall time, từng giai đoạn và tổng thời gian request/đợi slot khi job kết thúc, cả khi lỗi. Tổng thời gian API cộng nhiều request song song nên không bằng wall time. Chưa có baseline tuần tự sạch hoàn chỉnh để tính tỉ lệ tăng tốc.

Lệnh đo:

```bash
./run_auto.sh --video 'B_i 7 -  Ph_n 1  Gi_i thi_u file Layout_ s_a l_i khi import netlist v_o Layout.mp4' --output output/layout_netlist_auto_speed_v2 --language vi --asr-second-pass --parallel 3 --api-parallel 4
```

Lượt thử speed_v1 đã được dừng đúng client bằng pgrep đường dẫn đầy đủ sau khi phát hiện thứ tự câu hỏi riêng trước bằng chứng mất prefix theo mục. Trạng thái/log của lượt bỏ: `output/layout_netlist_auto_speed_v1/run-status.json`, `run-last.log`; không coi là benchmark hoàn tất. Thêm test xác nhận prefix bằng chứng, và fallback đọc độc lập nếu khung đại diện không đọc được. Lượt v2 bắt đầu lại toàn bộ với thư mục mới, không sao chép cache v1.

Các lỗi nội dung ở lượt trước vẫn là vấn đề mở, không được coi là đã sửa bởi thay đổi tốc độ. Kết quả cuối: **1188.931 giây = 19 phút 49 giây**, status failed; đây là wall time lượt thất bại, gồm chờ mục đang chạy sau lỗi đầu tiên, không phải thời gian tạo guide. Có 12 mục lục; chỉ khởi chạy 1–5, mục 2 và 5 hoàn tất kiểm định, mục 3/4 lỗi schema rà nghĩa (không trích đúng cụm nguyên văn sau hai lần sửa), mục 1 bị cắt ở `lexical_001_rscrub2` cả ba budget 1600/3200/6400. Mục 6–12 bị hủy trước khi chạy. Không có guide MD/HTML/PDF mới, không có document.auto/automation_metrics mới trong thư mục sạch.

- Chuẩn bị nguồn 264.499s (ASR lượt đầu 27.145s chồng nhánh ảnh: keyframe 32.853s, đọc màn hình 209.955s, recheck 21.688s); glossary lượt đầu 45.536s; ASR2+glossary 91.835s; outline 34.899s; phần mục 752.160s. Tổng request API 806; 329 trace hits nội bộ trong cùng job; 8 retry do phản hồi bị cắt, 4 sửa schema. 149 frame, đọc 144, dùng lại 5 = 3.36%, thấp hơn ước tính 20–40%. API không cung cấp cached-token usage; không suy ra cache server tắt.
- Đã đọc/grep toàn bộ hai mục hoàn tất ở `content-main-benchmark.txt`, 18 unresolved. Cổng token báo 0 nhưng **vẫn có lỗi thật**: dòng 31 `pg111.brd`, ảnh được chọn k0059 và ảnh k0056 ghi `prj111.brd`; OCR k0062 đọc sai pg111 nên cổng toàn-video tin tên sai. Mục 5 đã giới hạn câu đầu về màu theo video nhưng why/expected vẫn khá chung (dòng 35/52). Mục 2 không kết luận board hoàn tất. Không suy ra các lỗi quan hệ/Export/pin đã sửa vì các mục đó chưa xong. Report count G1/G2 dùng ranh giới token, không đếm chữ g1 nằm trong pg111.
- **Đạt ở mức triển khai và unit test** các cách tăng tốc 1–5; giữ đủ vòng kiểm định. **Chưa đạt** phép đo chạy thành công đến cuối, chưa chứng minh 12–18 phút hoặc mức tăng tốc so với tuần tự, chưa chứng minh chất lượng tương đương, chưa đạt audit nội dung, chưa kiểm thử lại video không lời ở lượt tăng tốc này. Không triển khai cách 6–7.
- Báo cáo: `output/layout_netlist_auto_speed_v2/benchmark-report.md`, `performance.json`, `run-status.json`, `run-last.log`, `document.partial.json`, `content-main-benchmark.txt`, `content-term-violations.json`, `content-token-counts.json`. Lượt v1 bị dừng riêng có log/status; không dùng như guide cuối.
- Đã xác nhận không còn tiến trình pipeline bằng pgrep đường dẫn đầy đủ. **Dừng sau lượt này, không mở thêm job, chưa commit.** Dịch vụ dùng chung không bị restart/sửa cấu hình.

## Trạng thái phiên sửa nội dung trước 2026-10-06 (lịch sử)

**Chủ dự án đã yêu cầu: xong lượt hiện tại thì dừng và báo cáo; không mở thêm lượt sửa/chạy lại sau đó.** Chưa commit. Phiên này không restart hay đổi cấu hình vLLM/TTS/embedding; dừng job bằng `pgrep` với đường dẫn đầy đủ. **Lượt cuối đã kết thúc: cả hai job exit 1, không còn tiến trình pipeline. Không chạy lại sau yêu cầu dừng.** Báo cáo chi tiết ở `output/layout_netlist_auto_v5/content-audit-last-run.md`.

- **Video chính chưa chạy xong / chưa đạt audit:** 11 mục đã viết, 8 mục hoàn tất kiểm định, 67 flags chưa giải quyết trong prefix. Job chết tại `lexical_009_r2`: cả 3 lần trả 1600/3200/6400 token đều `finish_reason=length`, request raises ValueError trước khi render. Xem `output/layout_netlist_auto_v5/run-last.log`, `run-status.json`, `document.partial.json`, `content-main-verified-prefix.txt`. Các mục 9–11 trong partial chưa được kiểm định xong; không lấy chúng làm kết luận sửa audit.
- **Không có HTML/PDF/Markdown mới.** `guide-auto.md` vẫn byte-for-byte giống `cache_previous/guide-before-last-run.md` (bản 2026-10-05), còn “file tóm tắt”/“ps mv”; `document.auto.json` và `automation_metrics.json` cũng là bản cũ. Không dùng những file này để đánh giá code cuối. Prefix 8 mục mới có .bat 5 lần, .bsm 0, ps mv/psmv 0, tóm tắt 0, Cannot Load Footprint 0, G1/G2 0; những số 0 chỉ có phạm vi prefix, không phải chứng nhận guide cuối.
- Đã đọc/grep xác nhận lỗi còn thật ở prefix: .bat trong quan hệ file mục 1; pg111.brd ở mục 5 trong khi ảnh k0056 có prj111.brd; quy tắc màu thành công/thất bại chưa giới hạn video ở mục 5; mục 7 còn “cả 3 file ... phải có mặt trong cùng một thư mục layout”. Mục 8 đã tách Save As/Export và chọn đúng ảnh k0120 nhưng còn khẳng định Export xuất .psm, trong khi ảnh chọn Padstacks, không chọn Package symbols; loại file xuất chưa được ảnh này hỗ trợ. Pin và 0/9 chưa có bản kiểm định cuối. Các kết luận cụ thể có dòng bằng chứng trong `content-audit-last-run.md`.
- Đã đạt phép thử ảnh cho `ps mv`/`psmv`→`.psm`, và bác ba cặp nhiễu; bằng chứng ở `output/rare_text_probe_v5/` và các quyết định đầy đủ ở `output/layout_netlist_auto_v5/screen_rechecks.json`.
- Đã thêm/sửa code: crop vùng sáng + bbox; lọc cấu trúc ghép chữ; hash payload của `choose`; vô hiệu hóa cache theo screen; hash cache phonetic theo rows/screen; loại segment ID trùng; rà nghĩa từ ngữ và danh từ; kiểm tra tiêu đề/caption, ranh giới token, nguyên cụm tiếng Anh; chấm lại sau scrub; không tự gắn `needs_review` chỉ vì review_note; gộp nguồn ảnh 45 giây; ngân sách mục theo thời lượng; kiểm tra khoảng nguồn không chồng nhau; đối chiếu cả hai ASR theo cửa sổ.
- Sáu unit test của `fold`, `term_violations`, `phonetic_candidates` đã đạt; code và CLI probe biên dịch được.
- **Đã thấy hồi quy thật trong lượt cuối video chính:** mục 1 sau đủ 2 lượt revise + 3 lượt scrub vẫn có `.bat` trong nội dung chính, mặc dù cổng xác định báo không có trên màn hình. Có 8 unresolved ở mục này. Grounding ban đầu đã viết đúng `.pad`, nhưng lexeme scorer bác "file có phần mở rộng .pad" (p=0.069), "file .pad" (p=0.072), dẫn tới revise quay về ASR `.bat`. `lexical_grounding` còn trả cả những mục reason "Không có lỗi" trong danh sách unsupported. Cổng cuối hiện **chỉ ghi unresolved, vẫn cho phép render nội dung sai tên**, nên phải siết điều kiện xuất ở lượt tiếp theo; không coi `needs_review` là cách sửa nội dung chính. Traces: `grounding_001`, `revise_001_r1/r2`, `lexeme_0ccdf1f82622eb26`, `lexeme_cc68b2656744ec5b`, `lexical_001_rscrub3`.
- **Video thứ hai chưa đạt chạy xong.** Đoạn 01:00–05:00 tự chuyển chế độ hình ảnh (16 từ sau lọc), 65 keyframe, 5 nhóm nguồn. Nháp trước có 3 mục, nhưng lượt cuối thất bại ở `outline_001`: model lặp khoảng nguồn chồng nhau sau 2 lần tự sửa; pipeline raise `ValueError`, chưa có guide HTML/PDF/Markdown. Xem `output/silent_auto_v5/run-last.log`, `run-status.json`, `traces/outline_001_repair_*.json`. **Không mô tả nháp 3 mục là kết quả hoàn chỉnh.** Bước tiếp theo cần cách lập mục lục có partition nguồn đáng tin cậy hoặc model gộp ở cấp nhóm trước; hiện cổng nonoverlap chạy trước bước compact, nên model sai ngay tại cửa sổ sẽ chưa tới bước gộp.

## Mục tiêu

Từ một video bất kỳ (bài giảng phần mềm có lời, hoặc quay màn hình không lời), tự động sinh tài liệu hướng dẫn HTML/PDF/Markdown có ảnh, đúng thuật ngữ, không bịa. Yêu cầu của chủ dự án:

- Dùng được cho mọi loại video. **Không viết cứng** thuật ngữ, tên phần mềm hay câu hướng dẫn riêng cho một video.
- Nội dung do model viết (Qwen38 qua vLLM); code chỉ kiểm tra, không biên tập tay. `human_editorial_changes` phải bằng 0.
- **Không request nào được nhét cả video**: chia nhỏ theo khung hình, cửa sổ transcript và từng mục.

Tiêu chí "đạt" là sửa hết các lỗi trong `output/layout_netlist_auto_v3/content-audit.md`, áp dụng được cho video khác, và không còn tên hoặc thuật ngữ bịa trong nội dung chính.

## Môi trường

- Chạy: `./run_auto.sh --video <mp4> --output <dir> [--transcript <transcript.raw.json>] [--language vi] [--asr-second-pass]`. `run_auto.sh` gọi `.venv/bin/python auto_guide.py` và thêm thư viện CUDA.
- Model: `qwen38` (Qwen3.8-27B-FP8) ở `http://127.0.0.1:8000/v1`, hỗ trợ `logprobs`/`top_logprobs` và `response_format: json_object`.
  - Model nhận được `video_url`, nhưng server chỉ cấp 2048 token encoder cho mỗi đầu vào: 6 giây video ở 640px đã vượt giới hạn, nên không dùng.
- ASR: faster-whisper large-v3-turbo trên GPU 0 (còn khoảng 5GB VRAM trống).
- **Không được** khởi động lại hay sửa cấu hình vLLM/TTS/embedding đang chạy chung trên máy.
- Video thử chính: `B_i 7 -  Ph_n 1  Gi_i thi_u file Layout_ s_a l_i khi import netlist v_o Layout.mp4` (22:41, tiếng Việt, Cadence Allegro).
  - Transcript lượt 1 đã lưu: `output/layout_netlist_auto_v3/transcript.raw.json`.
- Video thử thứ hai: `20260924_133059.mp4` (9:37, hàn linh kiện, gần như không có lời).
- **Dừng tiến trình**: dùng `pgrep -f '^/home/ai_ductran/video-to-guide/.venv/bin/python /home/ai_ductran/video-to-guide/auto_guide'`. Không dùng `pkill -f auto_guide.py`, vì lệnh đó khớp với chính shell đang chạy và tự kill nó.

## Kiến trúc cơ sở auto-v5 (thay đổi luồng auto-v6-speed ghi ở đầu)

1. **ASR**: Whisper chép lời. Câu giống hệt nhau lặp từ 3 lần trở lên bị loại (ảo giác "Hãy subscribe…"). Nếu còn dưới 15 từ/phút thì chuyển sang **chế độ màn hình**: gộp keyframe thành đoạn nguồn `scr_XXXX` khoảng 45 giây; giữ frame IDs của từng đoạn và bỏ mô tả gần trùng.
2. **Keyframe theo thay đổi màn hình** (`keyframes`): lấy mẫu 0.5 giây/lần; chọn khung khi tỷ lệ điểm ảnh thay đổi ≥ `--scene-threshold` (0.02) và màn hình đã đứng yên; thêm ít nhất 1 khung mỗi `--max-frame-gap` (20 giây).
3. **Đọc chữ màn hình** (`read_screens`): 2 ảnh mỗi request; lô lỗi thì đọc từng ảnh; ảnh hỏng thì bỏ qua. Prompt yêu cầu chép cả chữ viết tay. Kết quả: `screen_text.json`.
4. **Đọc lại chuỗi hiếm có kiểm chứng ảnh** (`recheck_rare_text`) — đã chạy thử: dò vùng sáng → model định vị bbox → phóng to chữ, tối đa 2 ảnh/lượt; chấm cách đọc chuẩn hóa p≥0.6, xử lý tuần tự. Cổng cấu trúc loại ứng viên đổi phần số, rút ngắn tên hoặc ghép từ giao diện thường.
5. **Ứng viên theo phát âm** (`fold`, `phonetic_candidates`, ý tưởng từ PMF-CEC): gộp các phụ âm dễ nhầm (b/p, d/t, g/k/c/j…), so cụm 1–3 từ trong transcript với chữ màn hình **không có trong transcript** ("low-recall", ý tưởng từ SlideSpeech). Kết quả: `phonetic_candidates.json`.
6. **Bảng thuật ngữ** (`build_glossary`): Qwen ghép từ ASR với chữ màn hình theo từng cửa sổ transcript. Code kiểm tra chữ màn hình có trong khung được trích dẫn. Sau đó một **cổng xác suất kiểu SemIf** (`choose`, đọc logprob các chữ cái A/B/C) phân 3 mức: `terms` (p≥0.5), `possible` (0.2–0.5, chỉ là gợi ý), còn lại bị loại.
7. **ASR lượt 2** (`--asr-second-pass`): hotwords ≤200 ký tự lấy từ thuật ngữ đã xác minh và ứng viên phát âm. Bỏ lượt 2 nếu mất hơn 15% số từ. Bảng thuật ngữ lượt 1 và lượt 2 được **gộp** (`glossary_merged.json`). Prompt khi dùng lượt hai vẫn kèm ASR lượt đầu trong cùng cửa sổ để đối chiếu nghĩa và chiều quan hệ; source IDs dùng lượt đang hoạt động.
8. **Mục lục** theo cửa sổ transcript, sau đó kiểm tra các đoạn chưa được bao phủ. Đoạn chưa phân loại được gắn vào mục gần nhất. Khoảng nguồn các mục không được chồng nhau; vi phạm trả cho model tự sửa. Chế độ không lời có ngân sách `ceil(duration/75)` mục, tối thiểu 1; model gộp metadata mục lục nếu quá nhiều, code kiểm tra giữ đủ nguồn.
9. **Viết từng mục** (`author_section`): ảnh ứng viên là keyframe trong khoảng thời gian của mục; prompt kèm `RULES` nguồn và `SCHEMA`.
10. **Rà độ đầy đủ theo mục**, **bổ sung giải thích**, rồi **kiểm định nguồn** (`deepen`).
11. **Kiểm định từng khẳng định** (`verify`):
    - Tách khẳng định tự đứng được, có `kind` (ý tưởng DnDScore).
    - Chấm A/B/C/D: hỗ trợ / mâu thuẫn / thiếu nguồn / tổng quát hóa.
    - Khẳng định loại `rule`/`cause` được hỏi thêm câu "có tuyệt đối hóa vượt quá nguồn không".
12. **Cổng xác định trong code** (`term_violations`): đuôi file, mã chữ+số, từ viết tắt in hoa 2–5 chữ, và chuỗi giao diện/thông báo tiếng Anh trong ngoặc phải xuất hiện nguyên cụm trên màn hình. Kiểm tra ranh giới đuôi file/mã, loại description khỏi corpus tên, kiểm tra cả tiêu đề và caption. Cổng này tự tắt khi video không có chữ trên màn hình.
13. **Viết lại** (`revise`, tối đa `--verify-rounds`=2): tên không có trên màn hình thì bắt buộc bỏ, không thay bằng tên đoán. Sau đó **sửa hẹp từng câu** (`scrub`) cho các tên còn sót, tối đa 3 lượt, rồi kiểm định lại toàn bộ khẳng định và nghĩa từ ngữ sau mỗi lượt. Thêm `lexical_grounding`: model rà diễn giải ASR, trích nguyên văn cụm danh từ, chấm nghĩa từng cụm bằng logprob; p<0.5 thì yêu cầu model viết lại. Không có danh sách từ riêng cho video.
14. **Tóm tắt cuối** viết từ nội dung đã kiểm định và đi qua cùng cổng (`summarize`). Render bằng `build_guide_local.export`.

**Cache**: `request()` chỉ dùng lại trace khi hash prompt trùng (`input_sha256`). `choose` cũng kiểm tra hash toàn bộ payload (câu hỏi, đáp án và ảnh), không chỉ tên trace. `screen_evidence.sha256` làm hết hiệu lực cache glossary/phonetic/outline khi cách đọc màn hình đổi, lưu bản trước ở `cache_previous/`. Cache phonetic có hash rows và screen để không lẫn hai lượt ASR. Cache glossary vẫn dựa trên lần vô hiệu hóa màn hình: thay code/prompt glossary nhưng không đổi screen chưa tự làm hết hiệu lực cache glossary; đây là điểm cần cải thiện tiếp. Chạy lại cùng lệnh và cùng thư mục output thì pipeline tiếp tục từ chỗ dừng. `config.json` khóa thư mục với cấu hình: đổi tham số CLI thì phải dùng thư mục mới.

Tài liệu người dùng: `AUTOMATION.md`, `README.md`. Bảng so sánh v4 với audit: `output/layout_netlist_auto_v4/audit-compare.md`.

## Kết quả trước phiên tiếp tục (lịch sử): `output/layout_netlist_auto_v5/`

`automation_metrics.json`: 10 mục, 149 keyframe, 21 thuật ngữ xác minh, 208 khẳng định (203 được hỗ trợ, 5 thiếu nguồn, 0 mâu thuẫn), 9 khẳng định chưa giải quyết.

| Lỗi trong audit v3 | v5 |
|---|---|
| .bat/.bsm thay vì .pad/.psm | **Đạt**: nội dung chính không còn .bat/.bsm; .pad 5 lần, .psm 2 lần |
| "Cannot Load Footprint" bịa | **Đạt** |
| Bỏ lỡ hộp thoại Export Libraries | **Đạt** |
| G1/G2 ↔ J1/J2, prj111 | **Đạt** |
| 0/9 → "board hoàn tất" | **Đạt** |
| Quy tắc màu tuyệt đối | **Đạt**: ghi rõ "theo mô tả trong video" |
| Quan hệ file mục 1 | **Chưa đạt**: còn chữ `'ps mv'` (11 lần) và "file tóm tắt" (2 lần), xem dưới |

Video thứ hai (đoạn 01:00–05:00, chạy ở thư mục nháp, không nằm trong repo): pipeline tự chuyển sang chế độ màn hình và tạo được tài liệu, nhưng **chia quá nhỏ** (14 mục cho 4 phút) và rườm rà.

## Ưu tiên cho lượt tiếp theo sau khi người dùng cho tiếp tục

1. Chặn xuất khi `term_violations(public_text)` hoặc cổng summary còn lỗi tên: hiện code chỉ đánh dấu unresolved nên `.bat` vẫn lọt ra nội dung sau scrub. Không tự xóa/sửa guide trong code; yêu cầu model sửa được mới xuất.
2. Sửa rà nghĩa để không bác tên đã được kiểm chứng màn hình: đã thấy `.pad` bị bác rồi model quay về `.bat`. Phân biệt kiểm tra cách viết/tên với kiểm tra công dụng, chuẩn hóa thuật ngữ giữa hai lượt ASR, và dùng disposition có cấu trúc để không nhận reason "Không có lỗi" như một lỗi.
3. Mục lục màn hình cần cơ chế chia nguồn đáng tin cậy trước cổng nonoverlap; hiện model giữ các mục theo chủ đề lặp lại nhưng không chia được khoảng liên tiếp, và chết trước compact. Không tăng số lần sửa một cách mù quáng.
4. Ràng buộc đầu ra của rà nghĩa (số item, kích thước reason), kiểm soát false positive thay vì chỉ tăng max_tokens; lượt cuối chết tại lexical_009_r2 sau 3 phản hồi bị cắt.
5. Hash cache glossary theo rows/screen/prompt/policy. Cổng mới yêu cầu asr có nguyên văn trong segment trích dẫn chỉ chạy khi build glossary mới, không kiểm tra lại cache cũ nếu screen không đổi.
6. Xác minh lại toàn bộ audit bằng nội dung sau thay đổi; không dùng số supported hoặc needs_review thay cho đọc/grep.

## Vấn đề ghi nhận trước phiên tiếp tục (lịch sử)

1. **Đọc sai chữ viết tay.** Sơ đồ vẽ trong Paint ghi `*.brd`, `*.dra`, `*.psm`, `*.pad`. Qwen đọc thành `'ps mv'`/`'psmv'`/`'bed'` vì vùng vẽ nhỏ trong khung 1600×900. Đã kiểm tra bằng mắt ở `output/layout_netlist_auto_v5/frames/k0014.jpg`: vùng Paint nằm khoảng x 13–58%, y 25–80% của khung.
   - Khi kiểm tra lại bằng toàn khung, Qwen trả lời 'ps mv' ≠ psm với p≈0.05–0.15, tức là bác bỏ.
   - Hướng đang thử: gửi thêm 4 vùng ảnh phóng to (xem "Việc dở dang").
2. **"file tóm tắt".** Qwen diễn giải từ ASR "bắt tắt" (thực ra là padstack/pad) thành một từ thông dụng. Bộ chấm khẳng định không bắt được lỗi này. `RULES` đã cấm, nhưng chưa có hiệu lực. Cần một cách kiểm tra không phụ thuộc video cho kiểu lỗi "thay từ nghe không rõ bằng từ thông dụng có âm gần giống".
3. **Chế độ màn hình chia mục quá nhỏ.** Cần gộp các keyframe gần nhau hoặc giống nhau trước khi lập mục lục, hoặc giới hạn số mục theo thời lượng.
4. **Mục nào cũng `needs_review`**, vì Qwen luôn ghi `review_note`. Nên tách "ghi chú thông tin" khỏi "cần kiểm tra thật".
5. **Bộ chấm khẳng định là chính Qwen**, nên ở chỗ màn hình không có chữ (màu sắc, quan hệ nhân quả) nó vẫn tin lời nói.
6. **Chưa có test tự động.** Nên thêm unit test cho `fold`, `term_violations`, `phonetic_candidates`, `keyframes` với dữ liệu nhỏ.

## Chạy lại phép thử chữ hiếm

Có CLI riêng, không chạy ASR hoặc viết guide, và bắt buộc output riêng để không ghi quyết định thử có lọc vào cache job chính:

```bash
.venv/bin/python recheck_screen_text.py \
  --source output/layout_netlist_auto_v5 \
  --output /tmp/rare-text-next-probe \
  --read 'ps mv' --read psmv --read 'BRD File' --read pg111.brd --read Place
```

Phép thử trước khi siết lọc cấu trúc đã lưu ở `output/rare_text_probe_v5/`: ps mv→.psm p=0.756; psmv→.psm p=0.697; ba ghép nhiễu bị bác với p=0.257/0.349/0.320. Code hiện tại còn bác những ghép nhiễu không tương thích cấu trúc trước khi gửi ảnh. Lượt đầy đủ giảm từ 157 xuống 34 jobs; quyết định ở `output/layout_netlist_auto_v5/screen_rechecks.json`.

Lệnh video chính (giữ đúng cấu hình của thư mục v5):

```bash
./run_auto.sh \
  --video 'B_i 7 -  Ph_n 1  Gi_i thi_u file Layout_ s_a l_i khi import netlist v_o Layout.mp4' \
  --output output/layout_netlist_auto_v5 \
  --transcript output/layout_netlist_auto_v3/transcript.raw.json \
  --language vi --asr-second-pass
```

Video thứ hai: đã cắt 01:00–05:00 bằng stream copy thành `output/silent_0100_0500.mp4`. Job ở `output/silent_auto_v5/`, lệnh `./run_auto.sh --video output/silent_0100_0500.mp4 --output output/silent_auto_v5 --language vi`.

Unit tests: `.venv/bin/python -m unittest discover -s tests -v` (6 test đạt). Các hàm thuần ở module-level: `fold`, `term_violations`, `phonetic_candidates`. Đã sửa segment ID trùng trong ứng viên phát âm. Chưa có unit test keyframes.

## Đã thử và bỏ (đừng lặp lại)

- **Toàn khung + 4 phần ảnh phóng to**: lần thử 5 ảnh/request chỉ trả một phản hồi rồi các client chờ; đã dừng đúng client, không restart server. Crop nền sáng vẫn bác nhãn cần sửa (ps mv p=0.242, psmv p=0.104). Crop bbox riêng nhưng yêu cầu khớp OCR tuyệt đối cũng không đạt. Cách đang dùng kiểm tra cách viết chuẩn hóa theo nét chữ/ngữ cảnh, phân biệt nét kéo bút cuối chữ với chữ cái độc lập; vẫn cần cổng cấu trúc để tránh ghép nhiễu.
- **Chỉ rà nghĩa toàn mục**: bỏ sót "file tóm tắt" trong bản cũ. Bổ sung trích danh từ + chấm từng cụm; phép thử bắt được cụm này p=0.250.
- **Hotwords dài (600 ký tự chữ màn hình)**: Whisper sụp, từ 01:15 chỉ còn ra từ lẻ.
- **Để model tự chọn đuôi file thay thế** cho tên bị gắn cờ: model chọn `.brd` cho `.bat` (do `pjl_1.brd` có ở mọi khung). Đảo thứ tự đáp án vẫn ra `.brd`, nên đây không phải thiên vị vị trí. Đã thay bằng quy tắc "bỏ, không đoán".
- **Gắn "cách đọc khả dĩ" chỉ bằng độ giống chuỗi**, không kiểm chứng ảnh: rất nhiễu và sai.
- **Đọc video trực tiếp bằng `video_url`**: vượt giới hạn encoder 2048 token của server.

## Nguồn tham khảo đã dùng

- SlideSpeech (danh sách bias low-recall từ OCR): https://arxiv.org/pdf/2309.05396
- OCR-Enhanced Multimodal ASR: https://arxiv.org/html/2601.18393v1
- ED-CEC / PMF-CEC (sửa lỗi ASR theo ngữ cảnh và phát âm): https://arxiv.org/pdf/2310.05129, https://arxiv.org/pdf/2506.11064
- FActScore / OpenFActScore / DnDScore (kiểm định khẳng định): https://github.com/shmsw25/FActScore, https://github.com/lflage/OpenFActScore, https://arxiv.org/pdf/2412.13175
- PySceneDetect (có thể thay bộ chọn keyframe tự viết): https://www.scenedetect.com/api/
- SemIf của chủ dự án (chấm theo logprob): `/home/ai_ductran/Phu-main/src/inference/semif.py`
