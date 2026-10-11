# ⚛️ Trợ lý học Vật lý 12 (Gemini API + RAG)

Chatbot hỗ trợ học Vật lý 12, chạy một-người-dùng, **không cần đăng nhập**.
Có 3 chế độ:

- **💬 Hỏi đáp**: hỏi đáp có RAG dựa trên tài liệu bạn tải lên, có thể đọc to
  câu trả lời.
- **🎓 Gia sư AI**: học 1 kèm 1 theo kiểu Socrates, có trắc nghiệm tự chấm,
  sơ đồ tư duy, gợi ý video, đọc to.
- **📷 Giải đề từ ảnh**: chụp/tải ảnh đề bài, Gemini đọc và giải chi tiết
  từng bước, cũng đọc to được.

Chạy bằng Python, Streamlit và Gemini API (bản miễn phí).

> ℹ️ Tính năng tài khoản/đăng nhập, lớp học, giao bài tập (giáo viên theo
> dõi học sinh) đã được **xây xong nhưng đang tạm dừng** — xem mục
> "Tính năng đang tạm dừng" ở cuối file này nếu muốn bật lại.

## Cách hoạt động

1. Tải lên các file PDF/TXT (sách, tài liệu ôn tập Vật lý 12) ở sidebar.
2. Ứng dụng chia nhỏ tài liệu và tạo "embedding" (vector đại diện ý nghĩa)
   cho từng đoạn, lưu vào thư mục `user_data/local/`.
3. Khi đặt câu hỏi, ứng dụng tìm các đoạn tài liệu liên quan nhất (kỹ thuật
   gọi là **RAG - Retrieval-Augmented Generation**), gửi kèm câu hỏi cho
   Gemini để trả lời chính xác theo đúng nội dung tài liệu.
4. Nếu không có tài liệu liên quan, Gemini vẫn trả lời bằng kiến thức chung.
5. Câu trả lời có dùng icon/emoji (📌💡🧮✅...) để trực quan hơn, và có nút
   🔊 để đọc to ngay trong trình duyệt.

## 1. Cài đặt

```bash
cd physics12_chatbot
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Lấy API key miễn phí

1. Vào https://aistudio.google.com/app/apikey
2. Đăng nhập bằng tài khoản Google, bấm **Create API key**.
3. Copy file `.env.example` thành `.env`, dán key vào:
   ```
   GEMINI_API_KEY=AIzaSy...
   ```

> Lưu ý: gói miễn phí có giới hạn số lượt gọi/phút. Nếu gặp lỗi
> "rate limit" khi xử lý nhiều tài liệu cùng lúc, chỉ cần chờ một chút
> rồi thử lại (code đã có `time.sleep` để giảm bớt tình trạng này).

## 3. Chạy ứng dụng

```bash
streamlit run app.py
```

Trình duyệt sẽ tự mở ra `http://localhost:8501`. Không cần đăng nhập — mở
lên là dùng được ngay, thấy luôn 3 tab: **💬 Hỏi đáp**, **🎓 Gia sư AI**,
**📷 Giải đề từ ảnh**.

## Cấu trúc thư mục

```
physics12_chatbot/
├── app.py              # Giao diện Streamlit chính - 3 tab, không đăng nhập
├── rag_utils.py          # Đọc file, chia đoạn, tạo embedding, tìm kiếm, đọc/ghi JSON
├── config.py                # Cấu hình model, persona từng chế độ, đường dẫn dữ liệu
├── tts.py                      # Đọc to (TTS) - dùng ở cả 3 chế độ
├── mindmap.py                     # Sơ đồ tư duy (Gia sư AI)
├── youtube_utils.py                  # Gợi ý video (Gia sư AI)
├── user_data/local/                    # Toàn bộ dữ liệu của bạn (tự tạo, KHÔNG commit)
│   ├── data/                               # Tài liệu gốc đã tải lên
│   └── vectorstore/                          # Chỉ mục RAG + lịch sử chat
├── requirements.txt
└── .env.example

# Còn trong dự án nhưng KHÔNG được gọi từ app.py nữa (xem mục bên dưới):
├── school.py          # Logic lớp học / bài tập / bài nộp / lịch sử điểm
└── manage.py             # CLI tạo tài khoản GV/HS - cần sửa lại trước khi dùng lại
```

## Tính năng đang tạm dừng: tài khoản, lớp học, giao bài tập

Dự án đã từng có thêm một lớp: đăng nhập (streamlit-authenticator), vai trò
giáo viên/học sinh, tạo lớp, giao bài tập trắc nghiệm, theo dõi tiến độ cả
lớp (`school.py`, `manage.py`). Phần này **đang được tạm dừng** theo yêu
cầu, nên `app.py` hiện không gọi tới đăng nhập/vai trò/lớp học nữa - mọi
người dùng chung 1 bộ dữ liệu cục bộ (`user_data/local/`).

Lý do tạm dừng: bản `streamlit-authenticator` cài trên máy không đúng API
mà `manage.py`/`app.py` cũ kỳ vọng (lỗi `Hasher` không tồn tại) - cần sửa
lại code tạo tài khoản cho khớp phiên bản thực tế trước khi bật lại được.

Nếu sau này muốn bật lại, cần: khôi phục lại phần đăng nhập ở đầu `app.py`
(đọc `auth_config.yaml`, gọi `authenticator.login(...)`), khôi phục nhánh
hiển thị tab theo `ROLE` (giáo viên/học sinh) và tab "Bài tập được giao",
đồng thời sửa `manage.py` cho đúng API của `streamlit-authenticator` đang
cài. `school.py` không cần sửa gì - logic lớp học/bài tập vẫn còn nguyên.

## Có thể mở rộng thêm

- Bật lại hệ thống tài khoản/lớp học/giao bài tập (xem mục trên).
- Để học sinh tự đăng ký bằng mã lớp, thay vì giáo viên tạo thủ công.
- Bài tập tự luận (giáo viên chấm tay) bên cạnh trắc nghiệm tự chấm.
- Dùng `st.latex()` để hiển thị công thức đẹp hơn thay vì markdown thường.
- Deploy miễn phí lên [Streamlit Community Cloud](https://streamlit.io/cloud)
  — lưu ý ổ đĩa trên Streamlit Cloud không bền vững lâu dài (có thể mất dữ
  liệu `user_data/` sau khi app "ngủ" lâu ngày hoặc được khởi động lại),
  nên đây vẫn hợp với quy mô đồ án học tập chứ chưa phải lưu trữ production.

## Model đang dùng

File `config.py` đang dùng `gemini-2.5-flash` để trả lời và
`gemini-embedding-001` để tạo embedding — cả hai đều nằm trong gói miễn phí
tại thời điểm viết dự án này (9/2026). Google thỉnh thoảng đổi tên/thế hệ
model, nếu sau này thấy lỗi "model not found", hãy kiểm tra danh sách model
mới nhất tại https://ai.google.dev/gemini-api/docs/models và sửa lại 2 dòng
`MODEL_NAME` / `EMBED_MODEL` trong `config.py`.
