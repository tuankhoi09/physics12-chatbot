"""
Chatbot hỗ trợ học Vật lý 12 - giao diện Streamlit.
Có 2 chế độ:
  - "Hỏi đáp": hỏi gì đáp nấy, có RAG dựa trên tài liệu bạn tải lên.
  - "Gia sư AI": mô phỏng buổi học 1-1, chủ động dẫn dắt, đặt câu hỏi,
     chờ học sinh trả lời, phân tích và điều chỉnh cách giảng.

Chạy bằng lệnh:
    streamlit run app.py
"""

import os
import json
import re
import streamlit as st
from google import genai
from google.genai import types
from dotenv import load_dotenv

import config
import rag_utils
import tts

load_dotenv()  # đọc file .env để lấy GEMINI_API_KEY

st.set_page_config(page_title="Trợ lý Vật lý 12", page_icon="⚛️", layout="wide")


# ---------- KHỞI TẠO CLIENT GEMINI ----------

@st.cache_resource
def get_client():
    # Ưu tiên đọc từ Streamlit Secrets (khi deploy lên Streamlit Community Cloud).
    # Ở máy local thường chưa có secrets.toml -> st.secrets sẽ báo lỗi khi truy cập,
    # nên phải bọc try/except, rồi mới rơi về đọc từ .env / biến môi trường.
    api_key = None
    try:
        api_key = st.secrets.get("GEMINI_API_KEY")
    except Exception:
        pass
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


client = get_client()

if client is None:
    st.error(
        "Chưa tìm thấy GEMINI_API_KEY. Hãy tạo file `.env` (xem `.env.example`) "
        "hoặc set biến môi trường GEMINI_API_KEY rồi chạy lại ứng dụng."
    )
    st.stop()


def _stream_text(response_stream):
    """Chuyển luồng streaming từ Gemini thành từng đoạn text, để st.write_stream hiện dần."""
    for chunk in response_stream:
        if chunk.text:
            yield chunk.text


# ---------- SIDEBAR: QUẢN LÝ TÀI LIỆU (dùng chung cho cả 2 chế độ) ----------

with st.sidebar:
    st.header("📚 Tài liệu Vật lý 12")

    embeddings, chunks = rag_utils.load_vectorstore()
    if chunks:
        st.success(f"Đã sẵn sàng: {len(chunks)} đoạn tài liệu được lập chỉ mục.")
    else:
        st.info("Chưa có tài liệu nào được xử lý.")

    uploaded_files = st.file_uploader(
        "Tải lên sách/tài liệu Vật lý 12 (PDF hoặc TXT)",
        type=["pdf", "txt"],
        accept_multiple_files=True,
    )

    if uploaded_files and st.button("⚙️ Xử lý tài liệu vừa tải lên"):
        os.makedirs(config.DATA_DIR, exist_ok=True)
        for f in uploaded_files:
            with open(os.path.join(config.DATA_DIR, f.name), "wb") as out:
                out.write(f.getbuffer())

        progress = st.progress(0.0, text="Đang xử lý tài liệu...")

        def on_progress(done, total):
            progress.progress(done / total, text=f"Đang tạo embedding: {done}/{total} đoạn")

        n = rag_utils.build_vectorstore(client, progress_callback=on_progress)
        progress.empty()

        if n > 0:
            st.session_state["process_result"] = (
                "success",
                f"Xong! Đã xử lý {n} đoạn tài liệu. Bạn có thể đặt câu hỏi hoặc bắt đầu buổi học ngay.",
            )
        else:
            st.session_state["process_result"] = (
                "warning",
                "Không trích xuất được nội dung nào từ file. Nếu là PDF scan/ảnh chụp "
                "(không phải file text thật), pypdf không đọc được chữ trong ảnh - cần "
                "công cụ OCR khác, báo mình để mình thêm vào.",
            )
        st.rerun()

    if "process_result" in st.session_state:
        kind, message = st.session_state["process_result"]
        (st.success if kind == "success" else st.warning)(message)

    st.divider()
    if st.button("🗑️ Xoá lịch sử chat (Hỏi đáp)"):
        st.session_state.messages = []
        rag_utils.clear_chat_history(config.CHAT_HISTORY_FILE)
        st.rerun()

    if st.session_state.get("messages"):
        chat_text = "\n\n".join(
            f"{'Bạn' if m['role'] == 'user' else 'Mình (Chatbot nhóm 1)'}: {m['content']}"
            for m in st.session_state.messages
        )
        st.download_button(
            "💾 Tải cuộc trò chuyện Hỏi đáp (.txt)",
            data=chat_text,
            file_name="cuoc_tro_chuyen_vatly12.txt",
            mime="text/plain",
        )


# ---------- CHẾ ĐỘ 1: HỎI ĐÁP ----------

def render_qna_mode():
    st.subheader("💬 Hỏi đáp Vật lý 12")
    st.caption("Hỏi bất cứ điều gì về chương trình Vật lý lớp 12 - có thể dựa trên tài liệu bạn tải lên.")

    if "messages" not in st.session_state:
        st.session_state.messages = rag_utils.load_chat_history(config.CHAT_HISTORY_FILE)

    for msg in st.session_state.messages:
        with st.chat_message("user" if msg["role"] == "user" else "assistant"):
            st.markdown(msg["content"])

    question = st.chat_input("Nhập câu hỏi Vật lý của bạn...", key="qna_input")

    if question:
        st.session_state.messages.append({"role": "user", "content": question})
        rag_utils.save_chat_history(st.session_state.messages, config.CHAT_HISTORY_FILE)
        with st.chat_message("user"):
            st.markdown(question)

        embeddings, chunks = rag_utils.load_vectorstore()
        context_text = ""
        sources = []
        if embeddings is not None and len(chunks) > 0:
            results = rag_utils.retrieve(client, question, embeddings, chunks)
            for chunk, score in results:
                context_text += f"\n---\n(Nguồn: {chunk['source']}, trang {chunk['page']})\n{chunk['text']}\n"
                sources.append(chunk)

        if context_text:
            user_prompt = f"TÀI LIỆU THAM KHẢO:{context_text}\n\nCÂU HỎI CỦA HỌC SINH: {question}"
        else:
            user_prompt = question

        history = [
            types.Content(role=("user" if m["role"] == "user" else "model"), parts=[types.Part(text=m["content"])])
            for m in st.session_state.messages[:-1]
        ]
        history.append(types.Content(role="user", parts=[types.Part(text=user_prompt)]))

        with st.chat_message("assistant"):
            answer = None
            try:
                response_stream = rag_utils.call_with_retry(
                    client.models.generate_content_stream,
                    model=config.MODEL_NAME,
                    contents=history,
                    config=types.GenerateContentConfig(
                        system_instruction=config.SYSTEM_INSTRUCTION,
                        temperature=0.4,
                        max_output_tokens=config.MAX_OUTPUT_TOKENS_QNA,
                    ),
                )
                answer = st.write_stream(_stream_text(response_stream))
            except Exception as e:
                st.error(
                    "Gemini đang quá tải hoặc gặp sự cố tạm thời, đã thử lại vài lần "
                    "nhưng chưa được. Bạn đợi khoảng 1-2 phút rồi gửi lại câu hỏi nhé!\n\n"
                    f"(Chi tiết lỗi: {e})"
                )

            if answer and sources:
                with st.expander("📎 Nguồn tài liệu đã tham khảo"):
                    for s in sources:
                        st.caption(f"{s['source']} — trang {s['page']}")
                        st.text(s["text"][:300] + ("..." if len(s["text"]) > 300 else ""))

        if answer:
            st.session_state.messages.append({"role": "model", "content": answer})
            rag_utils.save_chat_history(st.session_state.messages, config.CHAT_HISTORY_FILE)


# ---------- CHẾ ĐỘ 2: GIA SƯ AI ----------

def _tutor_turn(user_text: str):
    """Gửi 1 lượt (câu trả lời của học sinh, hoặc yêu cầu ẩn) tới Gia sư AI, hiển thị + lưu kết quả."""
    st.session_state.tutor_messages.append({"role": "user", "content": user_text})
    rag_utils.save_chat_history(st.session_state.tutor_messages, config.TUTOR_HISTORY_FILE)
    with st.chat_message("user"):
        st.markdown(user_text)

    history = [
        types.Content(role=("user" if m["role"] == "user" else "model"), parts=[types.Part(text=m["content"])])
        for m in st.session_state.tutor_messages
    ]

    with st.chat_message("assistant"):
        answer = None
        try:
            response_stream = rag_utils.call_with_retry(
                client.models.generate_content_stream,
                model=config.MODEL_NAME,
                contents=history,
                config=types.GenerateContentConfig(
                    system_instruction=config.TUTOR_SYSTEM_INSTRUCTION,
                    temperature=0.6,
                    max_output_tokens=config.MAX_OUTPUT_TOKENS_TUTOR,
                ),
            )
            answer = st.write_stream(_stream_text(response_stream))
            if answer:
                tts.speak_button(answer, key=f"live_{len(st.session_state.tutor_messages)}")
        except Exception as e:
            st.error(
                "Gia sư đang gặp sự cố tạm thời (server quá tải), đợi chút rồi thử lại nhé.\n\n"
                f"(Chi tiết: {e})"
            )

    if answer:
        st.session_state.tutor_messages.append({"role": "model", "content": answer})
        rag_utils.save_chat_history(st.session_state.tutor_messages, config.TUTOR_HISTORY_FILE)


def _generate_quiz(client, topic: str):
    """Yêu cầu Gemini soạn 5 câu trắc nghiệm dạng JSON, dựa trên nội dung buổi học đã diễn ra."""
    history_text = "\n".join(
        f"{'Học sinh' if m['role'] == 'user' else 'Gia sư'}: {m['content']}"
        for m in st.session_state.tutor_messages
    )
    prompt = config.QUIZ_PROMPT_TEMPLATE.format(topic=topic, history=history_text[:8000])

    response = rag_utils.call_with_retry(
        client.models.generate_content,
        model=config.MODEL_NAME,
        contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
        config=types.GenerateContentConfig(temperature=0.4, max_output_tokens=1500),
    )
    raw = response.text.strip()
    match = re.search(r"\[.*\]", raw, re.DOTALL)  # phòng khi Gemini lỡ thêm chữ thừa quanh JSON
    quiz = json.loads(match.group(0) if match else raw)
    return quiz


def _render_quiz():
    quiz = st.session_state.tutor_quiz
    submitted = st.session_state.get("tutor_quiz_submitted", False)

    st.markdown("### 📝 Trắc nghiệm ôn tập")
    for i, q in enumerate(quiz):
        st.markdown(f"**Câu {i + 1}. {q['question']}**")
        option_keys = sorted(q["options"].keys())
        labels = [f"{k}. {q['options'][k]}" for k in option_keys]
        st.radio(
            f"Câu {i + 1}", labels, key=f"quiz_radio_{i}", index=None, label_visibility="collapsed"
        )
        if submitted:
            chosen = st.session_state.get(f"quiz_radio_{i}")
            chosen_letter = chosen[0] if chosen else None
            if chosen_letter == q["correct"]:
                st.success(f"✔️ Đúng! {q.get('explanation', '')}")
            else:
                st.error(f"❌ Đáp án đúng là **{q['correct']}**. {q.get('explanation', '')}")
        st.divider()

    if not submitted:
        if st.button("✅ Nộp bài trắc nghiệm"):
            st.session_state.tutor_quiz_submitted = True
            st.rerun()
    else:
        score = sum(
            1 for i, q in enumerate(quiz)
            if (st.session_state.get(f"quiz_radio_{i}") or " ")[0] == q["correct"]
        )
        st.info(f"🎯 Điểm của bạn: **{score}/{len(quiz)}**")
        if st.button("🔄 Làm bộ câu hỏi khác"):
            for i in range(len(quiz)):
                st.session_state.pop(f"quiz_radio_{i}", None)
            st.session_state.tutor_quiz = None
            st.session_state.tutor_quiz_submitted = False
            st.rerun()


def render_tutor_mode():
    st.subheader("🎓 Gia sư AI - học 1 kèm 1")
    st.caption(
        "Gia sư sẽ chủ động dẫn dắt: mở đầu bằng một tình huống thực tế, đặt câu hỏi, "
        "chờ em trả lời, rồi mới giảng bài theo từng phần nhỏ - không phải chỉ hỏi gì đáp nấy."
    )

    if "tutor_messages" not in st.session_state:
        st.session_state.tutor_messages = rag_utils.load_chat_history(config.TUTOR_HISTORY_FILE)
    if "tutor_topic" not in st.session_state:
        st.session_state.tutor_topic = rag_utils.load_tutor_state().get("topic")

    # ----- CHƯA CHỌN BÀI: cho học sinh chọn chủ đề để bắt đầu -----
    if not st.session_state.tutor_topic:
        topic = st.text_input(
            "Bạn muốn học bài nào hôm nay?",
            placeholder="Ví dụ: Cảm ứng điện từ, Dao động điều hoà, Sóng ánh sáng...",
        )
        if st.button("🚀 Bắt đầu buổi học", type="primary") and topic.strip():
            with st.spinner("Gia sư đang chuẩn bị bài học..."):
                embeddings, chunks = rag_utils.load_vectorstore()
                context_text = ""
                if embeddings is not None and len(chunks) > 0:
                    results = rag_utils.retrieve(client, topic, embeddings, chunks)
                    for chunk, score in results:
                        context_text += f"\n---\n(Nguồn: {chunk['source']}, trang {chunk['page']})\n{chunk['text']}\n"

                kickoff = f'Học sinh muốn học bài: "{topic}".'
                if context_text:
                    kickoff += f"\n\nTÀI LIỆU THAM KHẢO:{context_text}"
                kickoff += (
                    "\n\nHãy bắt đầu buổi học đúng quy trình: BƯỚC 1 - tạo tình huống mở đầu gây tò mò "
                    "liên quan trực tiếp đến bài này, rồi DỪNG LẠI chờ học sinh trả lời. Không giảng lý "
                    "thuyết ngay, không tự hỏi rồi tự trả lời thay học sinh."
                )

                try:
                    response = rag_utils.call_with_retry(
                        client.models.generate_content,
                        model=config.MODEL_NAME,
                        contents=[types.Content(role="user", parts=[types.Part(text=kickoff)])],
                        config=types.GenerateContentConfig(
                            system_instruction=config.TUTOR_SYSTEM_INSTRUCTION,
                            temperature=0.6,
                        ),
                    )
                    st.session_state.tutor_topic = topic.strip()
                    st.session_state.tutor_messages = [{"role": "model", "content": response.text}]
                    rag_utils.save_tutor_state({"topic": st.session_state.tutor_topic})
                    rag_utils.save_chat_history(st.session_state.tutor_messages, config.TUTOR_HISTORY_FILE)
                    st.rerun()
                except Exception as e:
                    st.error(f"Không khởi động được buổi học, thử lại nhé.\n\n(Chi tiết: {e})")
        return

    # ----- ĐANG TRONG BUỔI HỌC -----
    col1, col2 = st.columns([5, 1.3])
    with col1:
        st.info(f"📖 Đang học: **{st.session_state.tutor_topic}**")
    with col2:
        if st.button("🔁 Đổi bài học"):
            st.session_state.tutor_topic = None
            st.session_state.tutor_messages = []
            rag_utils.save_tutor_state({"topic": None})
            rag_utils.clear_chat_history(config.TUTOR_HISTORY_FILE)
            st.rerun()

    for i, msg in enumerate(st.session_state.tutor_messages):
        with st.chat_message("user" if msg["role"] == "user" else "assistant"):
            st.markdown(msg["content"])
            if msg["role"] != "user":
                tts.speak_button(msg["content"], key=f"hist_{i}")

    student_reply = st.chat_input("Trả lời Gia sư...", key="tutor_input")
    if student_reply:
        _tutor_turn(student_reply)

    st.divider()
    col_summary, col_quiz = st.columns(2)
    with col_summary:
        if st.button("📋 Tổng kết buổi học"):
            _tutor_turn(
                "Hãy tổng kết lại toàn bộ buổi học hôm nay: tóm tắt kiến thức chính theo gạch đầu dòng, "
                "nhắc lại phần em còn yếu để ôn thêm, và khen ngợi sự tiến bộ của em."
            )
    with col_quiz:
        if st.button("📝 Tạo 5 câu trắc nghiệm ôn tập"):
            with st.spinner("Gia sư đang soạn câu hỏi ôn tập..."):
                try:
                    st.session_state.tutor_quiz = _generate_quiz(client, st.session_state.tutor_topic)
                    st.session_state.tutor_quiz_submitted = False
                    st.rerun()
                except Exception as e:
                    st.error(f"Không soạn được trắc nghiệm, thử lại nhé.\n\n(Chi tiết: {e})")

    if st.session_state.get("tutor_quiz"):
        st.divider()
        _render_quiz()


# ---------- CHẾ ĐỘ 3: QUÉT & GIẢI ĐỀ TỪ ẢNH ----------

def render_solve_mode():
    st.subheader("📷 Quét & giải đề từ ảnh")
    st.caption(
        "Chụp hoặc chọn ảnh đề bài Vật lý (viết tay hoặc in), tải lên, Gemini sẽ đọc và giải chi tiết."
    )

    image_file = st.file_uploader(
        "Tải ảnh đề bài",
        type=["png", "jpg", "jpeg", "webp"],
        key="solve_image_uploader",
    )

    if image_file:
        st.image(image_file, caption="Đề bài đã tải lên", width=380)

        extra_note = st.text_input(
            "Ghi chú thêm cho Gia sư (không bắt buộc)",
            placeholder="Ví dụ: chỉ cần đáp số, hoặc giải câu b thôi...",
            key="solve_extra_note",
        )

        if st.button("🔍 Giải bài này", type="primary"):
            prompt_text = (
                "Đây là đề bài Vật lý 12 chụp/quét từ ảnh. Hãy đọc đúng nội dung đề, sau đó "
                "giải chi tiết từng bước, có công thức áp dụng rõ ràng, và nêu đáp số cuối cùng."
            )
            if extra_note.strip():
                prompt_text += f"\n\nYêu cầu thêm từ học sinh: {extra_note.strip()}"

            contents = [
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_bytes(
                            data=image_file.getvalue(),
                            mime_type=image_file.type or "image/png",
                        ),
                        types.Part(text=prompt_text),
                    ],
                )
            ]

            st.divider()
            try:
                response_stream = rag_utils.call_with_retry(
                    client.models.generate_content_stream,
                    model=config.MODEL_NAME,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=config.SOLVE_SYSTEM_INSTRUCTION,
                        temperature=0.3,
                        max_output_tokens=config.MAX_OUTPUT_TOKENS_SOLVE,
                    ),
                )
                st.write_stream(_stream_text(response_stream))
            except Exception as e:
                st.error(
                    "Không đọc/giải được ảnh này, có thể do Gemini đang quá tải hoặc ảnh quá mờ. "
                    f"Thử lại hoặc chụp rõ hơn nhé.\n\n(Chi tiết: {e})"
                )
    else:
        st.info("Chưa có ảnh nào được tải lên.")


# ---------- GIAO DIỆN CHÍNH: 3 TAB ----------

st.title("⚛️ Trợ lý học Vật lý 12")

tab_qna, tab_tutor, tab_solve = st.tabs(["💬 Hỏi đáp", "🎓 Gia sư AI", "📷 Giải đề từ ảnh"])

with tab_qna:
    render_qna_mode()

with tab_tutor:
    render_tutor_mode()

with tab_solve:
    render_solve_mode()
