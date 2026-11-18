# 🐱 Neko Overlay Studio (Unified FreeMode + MultiPK)

Hệ thống điều khiển & hiển thị Overlay livestream TikTok thống nhất, tích hợp hoàn hảo 2 chế độ:
1. **🎯 Chế độ Tự Do (FreeMode)**: Chế độ từng idol độc diễn / nhận quà, hỗ trợ tính năng Mục tiêu điểm (Target Score), Bù giờ (Grace Period), popup nhận quà động, hiệu ứng combo.
2. **⚔️ Chế độ MultiPK (2 - 5 Người)**: Chế độ Battle đa phe, gán Idol vào từng vị trí, quà tặng kích hoạt phe, sương mù ẩn điểm (Fog of War), khóa điểm thống kê cuối hiệp (Score Lock), thanh năng lượng battle đa màu sắc.

Tất cả chạy trên **một server Python FastAPI duy nhất**, sử dụng **chung một danh sách Idol**, **một kết nối phòng TikTok Live**, và **chung WebSocket realtime**.

---

## 🚀 Cài đặt & Khởi động

### 1. Khởi động nhanh (Windows):
Double click vào file:
```
run.bat
```

### 2. Hoặc chạy qua dòng lệnh:
```bash
cd c:\Users\Admin\Downloads\neko-ovl-unified
pip install -r requirements.txt
python server.py
```

Server sẽ chạy tại cổng `8000`:
- **Bảng điều khiển (Control Dashboard)**: `http://localhost:8000/control`

---

## 📺 Danh sách Link OBS Browser Source

| Tên Overlay | URL Browser Source | Mô tả |
| :--- | :--- | :--- |
| **🎯 FreeMode Popup** | `http://localhost:8000/overlay/popup` | Hiển thị thẻ idol đang thi đấu, điểm số, ribbon tên, mục tiêu điểm & combo chuẩn MCA |
| **⚔️ MultiPK Battle Bar** | `http://localhost:8000/overlay/pk` | Thanh battle PK 2-5 phe chuẩn MCA: avatar, tỷ lệ điểm số, vệt sáng leader, sương mù Fog |
| **🏆 Bảng Xếp Hạng Rank** | `http://localhost:8000/overlay/rank` | Bảng xếp hạng danh sách idol chuẩn MCA, cờ loại OUT, top fan cống hiến |
| **🤖 Overlay Tự Động** | `http://localhost:8000/overlay` | Link OBS thông minh duy nhất: tự động chuyển đổi giữa FreeMode và MultiPK theo Control Panel |

*Đề xuất kích thước trong OBS: `1080 x 1920` (dọc) hoặc `1920 x 1080` (ngang), tích hợp tính năng tự động co giãn.*

---

## ✨ Các tính năng nổi bật trong Giao diện Gộp

### 1. Thanh điều hướng & Chuyển chế độ (Top Bar):
- **Tab chuyển Mode 1-chạm**: Chuyển đổi qua lại giữa `🎯 Chế độ Tự Do` và `⚔️ Chế độ MultiPK` ngay lập tức mà không làm mất danh sách idol hay kết nối phòng live.
- **Kết nối TikTok Live**: Nhập username `@id` và bấm kết nối. Có đèn tín hiệu xanh/đỏ báo trạng thái kết nối realtime.
- **OBS Links Modal**: Nút mở danh sách các link OBS kèm nút sao chép 1-click.
- **Hỗ trợ 2 ngôn ngữ**: Tiếng Việt (`VN`) và Tiếng Anh (`EN`).

### 2. Cột Trái - Quản lý Idol dùng chung (Shared Idol Pool):
- **Thêm Idol**: Hỗ trợ 3 cách:
  - Thêm lẻ (Tên, TikTok ID, tự động fetch avatar từ TikTok profile).
  - Thêm hàng loạt (dán danh sách mỗi dòng 1 tên).
  - Import / Export (hỗ trợ cả JSON và định dạng văn bản `name|tiktok_id|score|live/out|avatar`).
- **Tìm kiếm & Lọc nhanh**: Tìm theo tên, tiktok ID; lọc theo *Tất cả*, *Đang đấu*, *Đã loại*.
- **Tự động quét Avatar**: Nút `🔄 Tìm avatar còn thiếu` tự động lấy ảnh đại diện của tất cả các idol chưa có avatar.
- **Hành động trực quan trên từng thẻ Idol**:
  - Khi ở **FreeMode**: Nút `⭐ Chọn nhận quà` (sáng viền vàng khi active), `+100`, `+500`, `+1000`, `Loại / Hồi sinh`, `Xóa`, `Reset điểm`.
  - Khi ở **MultiPK**: Thẻ hiển thị màu sắc và vị trí idol đang đảm nhiệm (V1 hồng, V2 xanh, V3 cam, V4 tím, V5 đỏ); các nút gán nhanh `Gán V1`, `Gán V2`, v.v.

### 3. Cột Phải - Bảng điều khiển chuyên sâu theo từng Mode:

#### Khi chọn FreeMode (Chế độ Tự Do):
- **Thẻ Idol Active lớn**: Xem ngay avatar to, tên, điểm số, nút cộng điểm tay.
- **Thời gian (Timer)**: Đếm ngược, đặt phút/giây, bù giờ Grace period (3s/5s), nút cộng nhanh +30s, +60s, +120s.
- **Mục tiêu điểm (Target Score)**: Đặt điểm mục tiêu (ví dụ 1.000 xu), có thanh tiến độ % trực quan, tự động thông báo khi idol đạt mốc.
- **Cơ chế nhận điểm Gift**: Chế độ Tự động (theo timer) hoặc Thủ công (bật/tắt nhận điểm bằng nút bấm).

#### Khi chọn MultiPK (Chế độ PK 2 - 5 người):
- **Cấu hình Vị trí**: Chọn 2, 3, 4 hoặc 5 người. Mỗi vị trí chọn 1 idol đại diện và 1 quà kích hoạt phe.
- **Thư viện quà tặng (Gift Catalog - 5.291+ quà tặng chuẩn MCAClone)**:
  - Tích hợp sẵn toàn bộ kho dữ liệu quà tặng TikTok từ MCAClone với hơn 5.200 quà, đầy đủ tên, icon, và số xu kim cương.
  - Hỗ trợ nút `🔄 Tải mới từ TikTok` gọi trực tiếp API Webcast của TikTok (`https://webcast.tiktok.com/webcast/gift/list/?aid=1988`) để cập nhật quà sự kiện mới nhất.
  - Tự động nhận diện và nạp quà mới động khi có người gửi quà trong lúc live.
  - Bộ lọc mức giá tiện lợi: `Tất cả` | `1 xu` | `2 - 99 xu` | `100 - 999 xu` | `1.000+ xu`.
  - Ô tìm kiếm thông minh theo tên hoặc ID quà tặng, hiển thị mượt mà không giật lag.
- **Điều khiển trận đấu**: Đếm ngược thời gian, bắt đầu, tạm dừng, reset, kết thúc trận.
- **Sương mù (Fog of War)**: Ẩn điểm số trên màn hình PK để tăng kịch tính. Tùy chọn kích hoạt từ đầu hoặc chỉ kích hoạt trong N giây cuối.
- **Thống kê cuối hiệp (Score Lock)**: Tiếp tục nhận điểm thêm N giây sau khi hết giờ để không bị mất các combo quà gửi vào giây chót.
