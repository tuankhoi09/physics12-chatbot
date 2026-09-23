# ⚛️ Trợ lý học Vật lý 12 (Gemini API + RAG)

Chatbot giúp học sinh lớp 12 học Vật lý, có thể tham khảo tài liệu riêng
(sách giáo khoa, đề thi, tóm tắt lý thuyết...) mà bạn tải lên, sử dụng
Gemini API (bản miễn phí) và Streamlit.

## Cách hoạt động

1. Bạn tải lên các file PDF/TXT (sách, tài liệu ôn tập Vật lý 12).
2. Ứng dụng chia nhỏ tài liệu và tạo "embedding" (vector đại diện ý nghĩa)
   cho từng đoạn, lưu vào thư mục `vectorstore/`.
3. Khi học sinh đặt câu hỏi, ứng dụng tìm các đoạn tài liệu liên quan nhất
   (kỹ thuật gọi là **RAG - Retrieval-Augmented Generation**), gửi kèm câu hỏi
   cho Gemini để trả lời chính xác theo đúng nội dung tài liệu.
4. Nếu không có tài liệu liên quan, Gemini vẫn trả lời bằng kiến thức chung.

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

Trình duyệt sẽ tự mở ra `http://localhost:8501`.

- Ở thanh bên trái: tải lên file PDF/TXT rồi bấm **"Xử lý tài liệu vừa tải lên"**.
- Sau khi xử lý xong, gõ câu hỏi Vật lý vào ô chat bên dưới.

## Cấu trúc thư mục

```
physics12_chatbot/
├── app.py              # Giao diện Streamlit chính
├── rag_utils.py         # Đọc file, chia đoạn, tạo embedding, tìm kiếm
├── config.py             # Cấu hình model, persona, tham số chunking
├── data/                  # Nơi lưu tài liệu gốc bạn tải lên
├── vectorstore/            # Nơi lưu embeddings đã xử lý (tự tạo)
├── requirements.txt
└── .env.example
```

## Có thể mở rộng thêm

- Thêm nút "Tạo đề kiểm tra" dựa trên chương đang học.
- Lưu lịch sử chat theo từng học sinh (thêm đăng nhập đơn giản).
- Dùng `st.latex()` để hiển thị công thức đẹp hơn thay vì markdown thường.
- Deploy miễn phí lên [Streamlit Community Cloud](https://streamlit.io/cloud).

## Model đang dùng

File `config.py` đang dùng `gemini-2.5-flash` để trả lời và
`gemini-embedding-001` để tạo embedding — cả hai đều nằm trong gói miễn phí
tại thời điểm viết dự án này (9/2026). Google thỉnh thoảng đổi tên/thế hệ
model, nếu sau này thấy lỗi "model not found", hãy kiểm tra danh sách model
mới nhất tại https://ai.google.dev/gemini-api/docs/models và sửa lại 2 dòng
`MODEL_NAME` / `EMBED_MODEL` trong `config.py`.
