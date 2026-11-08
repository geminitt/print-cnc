# PROMPT CHO CODEX — XY PLOTTER: INPUT → G-CODE + GUI GIÁM SÁT

## 1. Vai trò của bạn

Bạn là coding agent hỗ trợ phát triển phần mềm Python cho đồ án **máy vẽ CNC dạng XY Plotter** (máy dùng bút vẽ trên giấy). Hãy **khảo sát repository trước khi sửa mã**, đối chiếu chương trình đang có với yêu cầu dưới đây, sau đó lập kế hoạch và triển khai theo phạm vi thực tế của dự án.

Đây là bản mô tả ngữ cảnh từ cuộc trao đổi với người yêu cầu. **Không coi các chi tiết chưa được xác nhận là đặc tả kỹ thuật bắt buộc.**

## 2. Bối cảnh đã xác nhận

- Nhóm đã có **quy trình máy vẽ** và đang phân chia công việc giữa các thành viên.
- Máy sử dụng **Arduino**; **Arduino IDE** được dùng cho phần firmware/nạp chương trình. Arduino không thuộc phần phải viết lại trong nhiệm vụ này.
- Trước đây quy trình sử dụng **Inkscape** ở phía chuẩn bị dữ liệu/hình vẽ. Giảng viên **không cho nhóm dùng Inkscape cho phần chức năng mà nhóm phải tự phát triển**, và yêu cầu triển khai bằng **Python**.
- Người phụ trách nhiệm vụ này đang làm **phần chuyển dữ liệu đầu vào (input) thành G-code**.
- Người đó cũng phải làm **giao diện trực quan chỉ để hiển thị tiến độ khi máy đang vẽ/in**.
- **Từ G-code đến điều khiển Arduino, động cơ và phần cứng do thành viên khác phụ trách**. Giữ rõ ranh giới tích hợp giữa hai phần.

**Lưu ý quan trọng:** Không phát triển một ứng dụng thay thế toàn bộ Inkscape. Không mặc định phải làm graphic editor hay giao diện chỉnh sửa bản vẽ. GUI trong phạm vi này là **progress monitor**, không phải CAD editor.

## 3. Phạm vi công việc

### 3.1. Phần phải làm

**Module A — Input-to-G-code pipeline (Python)**

1. Nhận dữ liệu đầu vào đúng với loại dữ liệu mà đề tài/repository thực tế hỗ trợ.
2. Phân tích dữ liệu, trích xuất đối tượng hoặc đường nét cần vẽ.
3. Chuẩn hóa hệ tọa độ, đơn vị và tỷ lệ theo vùng làm việc của máy.
4. Biến các nét thành **toolpath** (quỹ đạo di chuyển đầu bút), có phân biệt chuyển động vẽ và chuyển động không vẽ.
5. Sinh G-code tương thích với firmware và cơ cấu nâng/hạ bút đã được nhóm xác nhận.
6. Kiểm tra tính hợp lệ và lưu hoặc bàn giao G-code cho module điều khiển của thành viên khác thông qua giao diện thống nhất.

**Module B — GUI theo dõi quá trình vẽ (Python)**

1. Hiển thị trạng thái công việc: chưa bắt đầu, đang vẽ, tạm dừng, hoàn thành hoặc lỗi (tên trạng thái có thể thay đổi theo giao thức thật).
2. Hiển thị **tiến độ thực thi** từ thông tin phản hồi của phần điều khiển, không chỉ từ số lệnh đã gửi.
3. Hiển thị trực quan phần đường vẽ đã hoàn thành so với đường vẽ còn lại, **nếu** giao thức phản hồi có đủ dữ liệu để đối chiếu tiến độ với toolpath.
4. Hiển thị thông tin cơ bản như số lệnh/đoạn đã hoàn thành hoặc vị trí đầu bút **nếu có dữ liệu thực tế**.
5. Xử lý mất kết nối, lỗi và tình huống không có dữ liệu; tuyệt đối không biểu diễn tiến độ giả như tiến độ thật.
6. Chỉ thêm các nút điều khiển máy (start/pause/stop) nếu nhóm xác nhận giao diện này chịu trách nhiệm phát lệnh đó. Mặc định GUI là **chỉ giám sát**.

### 3.2. Phần ngoài phạm vi

- Không viết lại firmware Arduino, GRBL hoặc thuật toán điều khiển động cơ.
- Không thiết kế lại mạch điện, driver động cơ, kết nối chân hay hệ cơ khí.
- Không tự viết lại module G-code sender/controller nếu đã có thành viên khác đảm nhiệm.
- Không xây dựng trình vẽ tương tác như Inkscape (canvas thiết kế, chọn/di chuyển hình, chỉnh vector, typography...).
- Không thêm OCR, AI, nhận dạng ảnh hoặc hỗ trợ ảnh raster nếu không được yêu cầu và chưa có trong quy trình đã xác nhận.
- Không tuyên bố máy đã thực hiện xong một nét chỉ vì lệnh đã được gửi qua serial.

## 4. Workflow hệ thống

```text
                 [NGƯỜI DÙNG / FILE INPUT]
                            |
                            v
               +-------------------------+
               | Python: Input Parsing   |
               | đọc định dạng đã chốt   |
               +-------------------------+
                            |
                            v
               +-------------------------+
               | Geometry Processing     |
               | các đường / tọa độ      |
               +-------------------------+
                            |
                            v
               +-------------------------+
               | Toolpath Planning       |
               | thứ tự nét, nâng/hạ bút |
               +-------------------------+
                            |
                            v
               +-------------------------+
               | G-code Generation       |
               | + Validation            |
               +-------------------------+
                            |
                  G-code + metadata
                            |
        ====================|===================
             RANH GIỚI GIỮA HAI THÀNH VIÊN
                            |
                            v
               +-------------------------+
               | G-code Sender /         |
               | Arduino Firmware        |  <-- Thành viên khác
               +-------------------------+
                            |
                            v
               +-------------------------+
               | Drivers / XY Plotter    |  <-- Thành viên khác
               +-------------------------+
                            |
                     Trạng thái thực thi
                            |
                            v
               +-------------------------+
               | Progress Event Adapter  |
               | (giao thức thống nhất)  |
               +-------------------------+
                            |
                            v
               +-------------------------+
               | Python Progress GUI     |
               | tiến độ / đường đã vẽ   |
               +-------------------------+
```

**Quan trọng:** GUI hoạt động **đồng thời** với quá trình máy thực hiện lệnh. Nó cần thông tin phản hồi từ controller hoặc một event stream đáng tin cậy. Đường đi của G-code sang phần cứng là chiều đi; trạng thái thực thi phản hồi về GUI là chiều về.

## 5. Những thông tin CHƯA được xác nhận

Không tự bịa hoặc hardcode các mục sau. Trước hết tìm trong repo và các tài liệu đi kèm. Nếu chưa có, định nghĩa interface và dùng mock có ghi nhãn rõ:

- Input thực tế là SVG, PNG/JPG, dữ liệu nét tự do, văn bản, hay định dạng khác?
- Inkscape trước đây đang thực hiện chính xác những tác vụ nào (chỉ chuẩn bị SVG, chuyển G-code bằng extension, hay cả hai)?
- Loại board Arduino và firmware thực tế là gì? Có dùng GRBL hay firmware tự viết không?
- Cơ cấu nâng/hạ bút sử dụng servo, trục Z hay cách khác? Lệnh G-code tương ứng là gì?
- Hệ tọa độ, giới hạn vùng vẽ, độ phân giải và tốc độ phù hợp của máy?
- Hình thức bàn giao G-code: xuất file, API, hàng đợi hay chuyển trực tiếp cho một tiến trình khác?
- Controller phản hồi tiến độ ở mức **lệnh hoàn tất**, **đoạn đường hoàn tất**, **vị trí thực tế**, hay chỉ có thông báo kết thúc?
- Giao diện có bắt buộc phải sử dụng framework cụ thể nào không? Nếu chưa có, cân nhắc PySide6 nhưng đừng thay framework đang hoạt động mà không có lý do.

## 6. Các nguyên tắc thiết kế

1. **Tách rời pipeline và GUI**: phần sinh G-code phải hoạt động được ở chế độ không có giao diện (CLI hoặc API nội bộ), để có thể kiểm thử độc lập.
2. **Tách adapter tích hợp với controller**: nhận trạng thái qua interface rõ ràng. Trong khi chưa có phần cứng, dùng fake/mock adapter để mô phỏng.
3. **Định nghĩa hợp đồng dữ liệu** giữa các thành viên: định dạng G-code, quy ước nâng/hạ bút, trục tọa độ, đơn vị, cách nhận event và xác nhận hoàn thành.
4. **Không đánh đồng số lệnh đã gửi với tiến độ thực thi**. Tiến độ theo số lệnh hoàn thành cũng không đồng nghĩa với phần trăm thời gian còn lại. Ghi rõ chỉ số đang dùng.
5. **GUI không được đơ** khi xử lý file hoặc chờ dữ liệu serial/network: dùng worker/thread hoặc cơ chế bất đồng bộ tương thích với framework.
6. **Kiểm soát an toàn**: kiểm tra tọa độ ngoài vùng vẽ, lệnh sai, chuyển động liên tục khi bút cần nâng, file trống/hỏng, phản hồi lỗi hoặc mất kết nối.
7. Viết mã có cấu trúc, có type hints khi phù hợp, log lỗi và unit tests cho logic cốt lõi. Không thêm dependency lớn nếu thư viện hiện có đủ dùng.
8. **Không viết lại những phần đã có**: ưu tiên tích hợp với kiến trúc và quy ước repository.

## 7. Các bước Codex phải thực hiện

### Bước 1 — Khảo sát

- Đọc `README`, tài liệu đồ án, sơ đồ kiến trúc, mã nguồn và các file chỉ dẫn agent nếu có (`AGENTS.md`, `CLAUDE.md`, `PLAN.md`, `STATUS.md`, `REFERENCE.md`).
- Xác định ngôn ngữ, framework, pipeline, GUI, test, phương thức tích hợp và các phần đã hoàn thành.
- Đánh dấu rõ: **đã có / chưa có / chưa xác minh** cho từng yêu cầu.
- Không kết luận firmware là GRBL chỉ từ việc thấy G-code; cần bằng chứng trong mã/tài liệu.

### Bước 2 — Lập kế hoạch ngắn, có ranh giới

- Liệt kê các thay đổi tối thiểu để tạo luồng Input → G-code và hiển thị progress.
- Nêu rõ interface phải thống nhất với thành viên phụ trách controller.
- Xác định những gì có thể mock ngay để phát triển độc lập với phần cứng.
- Nếu thiếu thông tin quan trọng, không tự chế các giá trị máy. Cô lập chúng trong cấu hình/adapter và ghi rõ giả định; chỉ hỏi khi thực sự chặn triển khai.

### Bước 3 — Triển khai theo thứ tự

1. Hoàn thiện hoặc điều chỉnh xử lý input đã được xác nhận.
2. Tạo biểu diễn trung gian cho các nét/toolpath, phân biệt `pen_up` và `pen_down`.
3. Xây dựng/hoàn thiện generator và validator G-code theo cấu hình controller.
4. Tạo API/event contract để đưa dữ liệu trạng thái từ controller về GUI.
5. Tạo GUI **giám sát** tối giản: trạng thái, progress bar, vùng xem tiến trình vẽ, lỗi.
6. Dùng controller mock để chạy thử luồng end-to-end khi chưa có phần cứng thật.
7. Tích hợp với module thật chỉ khi có protocol và bộ điều khiển tương ứng.

### Bước 4 — Kiểm thử

- Test hình cơ bản: đường thẳng, hình chữ nhật, đường cong, nhiều nét rời.
- Test bút nâng/hạ đúng trước và sau các nét rời.
- Test tọa độ âm, vượt giới hạn, file lỗi và dữ liệu rỗng.
- Test tính nhất quán giữa path preview và G-code được tạo.
- Test GUI nhận trạng thái từ mock: running, paused, completed, error, disconnect.
- Test không báo hoàn thành trước khi controller xác nhận hoàn tất.
- Chạy lint/typecheck/tests có sẵn; không tuyên bố kiểm thử hardware nếu chưa có hardware.

### Bước 5 — Báo cáo kết quả

Trình bày ngắn gọn:

- Những thành phần đã có từ trước.
- Những file và thành phần đã thay đổi.
- Flow Input → G-code và flow phản hồi → GUI sau triển khai.
- Cách chạy thử không cần phần cứng.
- Các bài kiểm thử và kết quả thực tế.
- Danh sách thông tin còn phải thống nhất với thành viên làm Arduino/controller.

## 8. Tiêu chí hoàn thành

- Có thể đưa **loại input được dự án chốt** vào chương trình Python và nhận G-code hợp lệ theo contract đã thống nhất.
- Có thể kiểm tra toolpath trước khi đưa xuống phần cứng.
- Có giao diện **chỉ giám sát** hiển thị trạng thái và tiến độ khi nhận sự kiện thực thi (ít nhất bằng mock adapter).
- GUI không tự nhận số lệnh đã gửi là số lệnh đã chạy xong.
- Phần Input → G-code hoạt động độc lập với firmware/driver; không chỉnh sửa trách nhiệm của thành viên khác.
- Có hướng dẫn chạy, cấu hình và kiểm thử để nhóm có thể tích hợp thật.

## 9. Cách phản hồi

- Trả lời bằng **tiếng Việt rõ ràng, ngắn, chính xác**, theo tinh thần ASD-STE100: câu ngắn; thuật ngữ thống nhất; phân biệt giả định và dữ kiện.
- Bắt đầu bằng **đánh giá trạng thái repository thực tế và các khoảng trống**, không bắt đầu bằng việc viết mới cả dự án từ đầu.
- Chỉ thực hiện những thay đổi có căn cứ vào yêu cầu trên và nguồn mã đã đọc.

**Nhiệm vụ ngay bây giờ:** Khảo sát repository hiện tại, đối chiếu với prompt này, rồi lập kế hoạch và triển khai phần còn thiếu trong phạm vi **Input → G-code + Progress Monitoring GUI**. Không chạm sang lớp điều khiển Arduino/phần cứng nếu không có yêu cầu tích hợp cụ thể.
