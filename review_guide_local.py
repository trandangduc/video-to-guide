"""Apply source-verified editorial corrections to this sample guide."""
import copy,json,re
from pathlib import Path
from PIL import Image
from build_guide_local import OUT,dump,export

doc=json.loads((OUT/'steps.selected.json').read_text())
rows=json.loads((OUT/'transcript.raw.json').read_text());lookup={r['id']:r for r in rows}
old={s['number']:s for s in doc['steps']}

def normalize(text):
    text=re.sub(r'\.bsm\b','.psm',text,flags=re.I)
    text=re.sub(r'\.bat\b','.pad',text,flags=re.I)
    text=re.sub(r'\.pat\b','.pad',text,flags=re.I)
    return text

for s in doc['steps']:
    for key in ['title','instruction','match_reason']:
        if isinstance(s.get(key),str):s[key]=normalize(s[key])
    for f in s['selected_frames']:f['caption']=normalize(f['caption'])
    s['terms_to_review']=[]

def assign_source(s,start,end):
    selected=[r for r in rows if r['end']>start and r['start']<end]
    s['source_segment_ids']=[r['id'] for r in selected]
    s['start']=min(r['start'] for r in selected);s['end']=max(r['end'] for r in selected)
    s['source_text']=' '.join(r['text'] for r in selected)

def focus(f,box,label):
    image=Image.open(OUT/f['path']);image.thumbnail((1500,1000))
    path=OUT/'frames'/(Path(f['path']).stem+'_'+label+'.jpg')
    image.crop(box).save(path,quality=94)
    f['context_path']=f['path'];f['path']=str(path.relative_to(OUT));f['detail_crop_bounds']=list(box)

old[1]['instruction']='File thiết kế board có đuôi .brd. File .dra dùng để chỉnh sửa footprint; khi lưu, phần mềm tạo file .psm để Layout nạp linh kiện. Footprint còn sử dụng các file padstack có đuôi .pad. Vì vậy, cần chuẩn bị các file liên quan trước khi đặt linh kiện vào board.'
assign_source(old[1],37,142)
old[1]['selected_frames'][0]['caption']='Sơ đồ trong bài giảng thể hiện quan hệ giữa các file .brd, .dra, .psm và .pad.'
focus(old[1]['selected_frames'][0],(240,245,910,655),'diagram')
old[1]['match_status']='matched'

old[2]['instruction']='Kiểm tra các linh kiện trong sơ đồ nguyên lý: đầu nối, diode, IC U1, điện trở và tụ điện. Chuẩn bị footprint tương ứng với các linh kiện sẽ đặt vào board. Trong bài giảng, giảng viên cung cấp sẵn một số footprint của tụ và điện trở; các linh kiện còn lại cần được chuẩn bị theo bài tập trước đó.'
old[2]['selected_frames'][0]['caption']='Sơ đồ nguyên lý trong OrCAD Capture: J1/J2, D1/D2, C1/C2/C3, R1 và IC U1.'
focus(old[2]['selected_frames'][0],(450,290,1210,540),'schematic')
old[3]['instruction']='Mở thư mục footprint được cung cấp trong tài liệu bài học. Sao chép các file .dra, .psm và .pad liên quan đến linh kiện, rồi dán vào thư mục chứa file board .brd. Trong cách làm được trình bày ở video, các file nằm cùng thư mục để Layout tìm được dữ liệu khi đặt linh kiện.'
old[3]['selected_frames'][0]['caption']='Danh sách file trong thư mục footprint, có các đuôi .pad, .dra và .psm.'
focus(old[3]['selected_frames'][0],(270,140,890,480),'files')
old[3]['match_status']='matched'
old[4]['title']='Mở Place → Manually để đặt linh kiện'
old[4]['instruction']='Mở file board .brd trong Allegro PCB Designer. Trên thanh menu, chọn Place → Manually… để mở hộp thoại Placement. Trong tab Placement List, chọn Components by refdes để xem danh sách linh kiện theo ký hiệu tham chiếu.'
focus(old[4]['selected_frames'][0],(285,0,580,230),'menu')
focus(old[4]['selected_frames'][1],(545,75,1110,710),'placement')
old[4]['selected_frames'][0]['caption']='Menu Place có lệnh Manually… để mở chế độ đặt linh kiện thủ công.'
old[6]['instruction']='Nếu thao tác đặt linh kiện không thành công và phần Command báo không nạp được symbol, hãy kiểm tra các file .dra và .psm của footprint đó. Theo bài giảng, các file cần có trong thư mục chứa board .brd. Sao chép hoặc lưu các file vào đúng thư mục, rồi thử đặt linh kiện lại.'
old[6]['match_status']='partial';old[6]['review_note']='Ảnh minh họa là sơ đồ giải thích các file; đoạn ảnh được chọn không hiển thị trực tiếp thông báo lỗi.'
old[7]['title']='Sửa lỗi không tìm thấy padstack (.pad)'
old[7]['instruction']='Nếu phần mềm đã tìm thấy footprint nhưng vẫn báo không nạp được padstack, hãy kiểm tra các file .pad mà footprint sử dụng. Đảm bảo các file .dra, .psm và các file .pad liên quan có trong thư mục chứa board. Khi thiếu padstack, thực hiện xuất thư viện như hướng dẫn ở phần sau.'
old[7]['selected_frames'][0]['caption']='Sơ đồ giải thích: footprint sử dụng các padstack có đuôi .pad.'
old[7]['match_status']='partial'
old[8]['instruction']='Khi một linh kiện chưa đặt được, kiểm tra vị trí lưu các file footprint của linh kiện đó. C1 và R1 trong ví dụ có thể đã có dữ liệu được cung cấp sẵn, còn D1, J1/J2 và U1 cần được kiểm tra riêng. Xác nhận các file .dra, .psm và padstack liên quan nằm trong thư mục chứa board.'
old[8]['selected_frames'][0]['caption']='Kiểm tra các file .dra và .psm trong thư mục linh kiện.'

lookup_step=copy.deepcopy(old[9]);lookup_step['title']='Đối chiếu tên PCB Footprint trong Schematic'
lookup_step['instruction']='Mở thuộc tính của linh kiện cần đặt trong OrCAD Capture. Tìm trường PCB Footprint và kiểm tra tên footprint đang gán cho linh kiện. Sao chép hoặc ghi lại tên này để tìm đúng file footprint cần mở; trong ảnh ví dụ, giá trị hiển thị là SOT-223.'
assign_source(lookup_step,752,803)
lookup_step['selected_frames']=[copy.deepcopy(old[9]['selected_frames'][0])]
focus(lookup_step['selected_frames'][0],(450,125,955,250),'property')
lookup_step['match_status']='matched'

save_step=copy.deepcopy(old[9]);save_step['title']='Lưu file .dra vào thư mục chứa board'
save_step['instruction']='Mở file .dra của footprint cần dùng. Chọn File → Save As…, chuyển đến thư mục chứa board .brd, rồi nhấn Save. Bài giảng dùng cách này để đưa dữ liệu footprint vào đúng thư mục; sau khi lưu, kiểm tra các file .dra và .psm tương ứng.'
assign_source(save_step,803,845)
save_frame={'id':'save_as_828','time':828.0,'path':'frames/save_as_828.jpg','caption':'Hộp thoại Save As: chọn thư mục chứa board và lưu file Symbol Drawing (*.dra).'}
focus(save_frame,(325,130,1245,565),'dialog')
save_step['selected_frames']=[save_frame];save_step['match_status']='matched'

old[10]['title']='Xuất padstack bằng Export Libraries'
old[10]['instruction']='Trong cửa sổ footprint, vào File → Export và mở hộp thoại Export Libraries. Chọn All On như lời hướng dẫn trong video, rồi nhấn Export để xuất dữ liệu thư viện, bao gồm padstack. Kiểm tra các file đã được xuất vào thư mục chứa board trước khi thử đặt linh kiện lại.'
focus(old[10]['selected_frames'][0],(0,0,300,430),'menu')
focus(old[10]['selected_frames'][1],(505,65,905,420),'dialog')
old[10]['selected_frames'][1]['caption']='Hộp thoại Export Libraries có nút All On và Export; ảnh cho thấy các mục Shape and flash symbols và Padstacks được chọn.'
old[10]['review_note']='Khung Command trong video còn có dòng báo lỗi và yêu cầu kiểm tra logfile. Ảnh minh họa vị trí lệnh; chưa xác nhận lần xuất này đã thành công.'
old[10]['match_status']='partial'
old[11]['instruction']='Mở Display → Status để kiểm tra trạng thái board. Sau khi đặt hết linh kiện, dòng Unplaced symbols cần có số lượng chưa đặt bằng 0; trong ảnh ví dụ là 0/9. Các chỉ số Unrouted nets và Unrouted connections được giảng viên giới thiệu để theo dõi kết nối; việc đi dây không nằm trong thao tác đặt linh kiện này.'
focus(old[11]['selected_frames'][0],(560,115,1090,720),'status')
old[12]['title']='Sửa lỗi số chân không khớp giữa symbol và footprint'
old[12]['instruction']='Khi gặp lỗi số chân không khớp, đối chiếu cả số lượng chân và các số pin giữa symbol trong Schematic với footprint. Ví dụ, symbol có pin 1 và 2 thì footprint cũng cần pin 1 và 2, không thay thành 3 và 4 hoặc thêm một pin khác. Sửa phần không khớp rồi thử đặt linh kiện lại.'
old[12]['selected_frames']=[copy.deepcopy(old[2]['selected_frames'][0])]
old[12]['selected_frames'][0]['caption']='Ảnh sơ đồ nguyên lý ở phần trước của video, dùng để minh họa việc đối chiếu số pin trên symbol.'
old[12]['match_status']='partial'
old[12]['review_note']='Video giải thích lỗi này bằng lời; ảnh minh họa được lấy từ phần sơ đồ nguyên lý trước đó, không phải ảnh chụp thông báo lỗi.'
old[13]['instruction']='Double click vào symbol trong Schematic để kiểm tra thuộc tính, đặc biệt trường PCB Footprint. Đối chiếu tên footprint và kiểm tra số lượng, số pin của symbol với footprint đã tạo. Nếu hai bên không khớp, chỉnh lại dữ liệu trước khi tiếp tục đặt linh kiện.'
old[13]['review_note']='Ảnh cho thấy trường PCB Footprint; việc đối chiếu toàn bộ số pin cần mở thêm symbol và footprint.'

status={'title':'Xem trạng thái board sau khi import netlist','instruction':'Sau khi mở board đã import netlist, vào Display → Status để xem trạng thái thiết kế. Hộp thoại cho biết số linh kiện chưa đặt (Unplaced symbols), số net chưa đi dây và số kết nối chưa đi dây. Dùng thông tin này để theo dõi tiến độ khi đưa linh kiện vào board.','terms_to_review':[],'selected_frames':[{'id':'display_status_163','time':163.0,'path':'frames/display_status_163.jpg','original_path':'frames/display_status_163_original.jpg','caption':'Hộp thoại Status hiển thị các mục Symbols and nets của board.'}],'match_status':'matched','selection_complete':True}
assign_source(status,142,183)
focus(status['selected_frames'][0],(525,140,1015,775),'status')

newsteps=[old[1],status,old[2],old[3],old[4],old[5],old[6],old[7],old[8],lookup_step,save_step,old[10],old[11],old[12],old[13]]
for i,s in enumerate(newsteps,1):
    s['id']=f'step_{i:03d}';s['number']=i;s['selection_complete']=True
    s['review_status']='needs_review' if s.get('review_note') or s.get('match_status')!='matched' else 'draft'
    s['editorial_review']='Checked file extensions, source screenshots, and menu labels; not a validation of the circuit design.'
doc['steps']=newsteps
doc['title']='Bài 7: Đặt linh kiện vào Layout và sửa lỗi import netlist'
doc['summary']='Tìm hiểu các file .brd, .dra, .psm và .pad; chuẩn bị footprint và đưa linh kiện vào board bằng Place → Manually. Bài hướng dẫn cũng trình bày cách xử lý lỗi thiếu symbol, thiếu padstack và số chân không khớp giữa sơ đồ nguyên lý với footprint.'
covered={id_ for s in newsteps for id_ in s['source_segment_ids']}
doc['uncovered_segment_ids']=[r['id'] for r in rows if r['id'] not in covered]
doc['editorial_corrections']=['.bsm/.bat from ASR corrected to .psm/.pad using visible filenames and the instructor diagram','Replaced inferred inductor LB with source-visible IC U1','Added source-backed Display Status section','Separated footprint lookup and Save As; found actual Save As dialog at 13:48','Flagged visible export-log error and illustrative screenshots']
dump(OUT/'steps.reviewed.json',doc)
export(doc)
