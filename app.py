"""
Chatbot hỗ trợ học Vật lý 12 - giao diện Streamlit.
Có 2 chế độ:
  - "Hỏi đáp": hỏi gì đáp nấy, có RAG dựa trên tài liệu bạn tải lên.
  - "Gia sư AI": mô phỏng buổi học 1-1, chủ động dẫn dắt, đặt câu hỏi,
     chờ học sinh trả lời, phân tích và điều chỉnh cách giảng.

KHÔNG yêu cầu đăng nhập (bản một-người-dùng) - tính năng tài khoản/đăng
nhập, lớp học, giao bài tập đang được TẠM DỪNG, xem README.md mục "Có thể
mở rộng thêm" nếu muốn bật lại sau này (school.py/manage.py vẫn còn trong
dự án nhưng không được gọi tới từ giao diện chính nữa).

Chạy bằng lệnh:
    streamlit run app.py
"""

import os
import json
import re
import datetime
import uuid
import streamlit as st
from google import genai
from google.genai import types
from dotenv import load_dotenv

import config
import rag_utils
import school
import tts
import mindmap
import youtube_utils

load_dotenv()  # đọc file .env để lấy GEMINI_API_KEY

st.set_page_config(page_title="Trợ lý Vật lý 12", page_icon="⚛️", layout="wide")


# ---------- "TÀI KHOẢN" CỐ ĐỊNH (không đăng nhập) ----------
# Bản này không có hệ thống đăng nhập - toàn bộ dữ liệu (tài liệu, lịch sử
# chat...) được lưu chung vào đúng 1 bộ thư mục/file ứng với username cố
# định dưới đây, dùng lại nguyên các hàm config.*_file(username) đã có sẵn.
username = "local"
name = "Bạn"

# ---------- ĐƯỜNG DẪN FILE RIÊNG CỦA "TÀI KHOẢN" ----------

DATA_DIR = config.data_dir(username)
EMBEDDINGS_FILE = config.embeddings_file(username)
CHUNKS_FILE = config.chunks_file(username)
CHAT_HISTORY_FILE = config.chat_history_file(username)
TUTOR_HISTORY_FILE = config.tutor_history_file(username)
TUTOR_STATE_FILE = config.tutor_state_file(username)
QNA_SESSIONS_FILE = config.qna_sessions_file(username)
SOLVE_SESSIONS_FILE = config.solve_sessions_file(username)
QNA_ACTIVE_ID_FILE = config.qna_active_id_file(username)


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
            # Markdown chỉ xuống dòng đúng khi có 2 dấu cách trước dấu xuống dòng - nếu không,
            # nhiều dòng liền nhau sẽ bị dính thành 1 dòng dài. Gemini chỉ trả về "\n" đơn thuần
            # nên phải tự thêm 2 dấu cách vào đây.
            yield chunk.text.replace("\n", "  \n")


@st.cache_resource
def get_youtube_key():
    api_key = None
    try:
        api_key = st.secrets.get("YOUTUBE_API_KEY")
    except Exception:
        pass
    return api_key or os.environ.get("YOUTUBE_API_KEY")


# ---------- SIDEBAR: TÀI KHOẢN + QUẢN LÝ TÀI LIỆU (dùng chung cho cả 3 chế độ) ----------

with st.sidebar:
    with st.expander("🔊 Đổi giọng đọc", expanded=False):
        tts.voice_picker()
    st.divider()

    st.header("📚 Tài liệu Vật lý 12")

    embeddings, chunks = rag_utils.load_vectorstore(EMBEDDINGS_FILE, CHUNKS_FILE)
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
        os.makedirs(DATA_DIR, exist_ok=True)
        for f in uploaded_files:
            with open(os.path.join(DATA_DIR, f.name), "wb") as out:
                out.write(f.getbuffer())

        progress = st.progress(0.0, text="Đang xử lý tài liệu...")

        def on_progress(done, total):
            progress.progress(done / total, text=f"Đang tạo embedding: {done}/{total} đoạn")

        n = rag_utils.build_vectorstore(
            client, DATA_DIR, EMBEDDINGS_FILE, CHUNKS_FILE, progress_callback=on_progress
        )
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

    existing_files = []
    if os.path.isdir(DATA_DIR):
        existing_files = sorted(
            f for f in os.listdir(DATA_DIR) if f.lower().endswith((".pdf", ".txt"))
        )

    if existing_files:
        with st.expander(f"📁 Quản lý file đã tải ({len(existing_files)})"):
            st.caption("Đổi tên hoặc xoá bớt file không cần - xong sẽ tự xử lý lại tài liệu.")
            for fname in existing_files:
                new_name = st.text_input(
                    fname, value=fname, key=f"rename_input_{fname}", label_visibility="collapsed"
                )
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✏️ Đổi tên", key=f"rename_btn_{fname}", use_container_width=True):
                        if not new_name.strip() or new_name == fname:
                            st.warning("Chưa đổi tên gì cả.")
                        elif os.path.exists(os.path.join(DATA_DIR, new_name)):
                            st.error(f"Đã có file tên \"{new_name}\" rồi, chọn tên khác.")
                        else:
                            os.rename(
                                os.path.join(DATA_DIR, fname),
                                os.path.join(DATA_DIR, new_name),
                            )
                            with st.spinner("Đang cập nhật lại chỉ mục tài liệu..."):
                                rag_utils.build_vectorstore(client, DATA_DIR, EMBEDDINGS_FILE, CHUNKS_FILE)
                            st.session_state["process_result"] = (
                                "success",
                                f'Đã đổi tên "{fname}" thành "{new_name}" và cập nhật lại tài liệu.',
                            )
                            st.rerun()
                with c2:
                    if st.button("🗑️ Xoá file", key=f"delete_btn_{fname}", use_container_width=True):
                        os.remove(os.path.join(DATA_DIR, fname))
                        with st.spinner("Đang cập nhật lại chỉ mục tài liệu..."):
                            n = rag_utils.build_vectorstore(client, DATA_DIR, EMBEDDINGS_FILE, CHUNKS_FILE)
                        st.session_state["process_result"] = (
                            "success" if n > 0 else "warning",
                            f'Đã xoá "{fname}" và cập nhật lại tài liệu.'
                            if n > 0 else f'Đã xoá "{fname}". Không còn tài liệu nào được lập chỉ mục.',
                        )
                        st.rerun()
                st.divider()

    if st.session_state.get("messages"):
        chat_text = "\n\n".join(
            f"{'Bạn' if m['role'] == 'user' else 'Mình (Chatbot nhóm 2)'}: {m['content']}"
            for m in st.session_state.messages
        )
        st.download_button(
            "💾 Tải cuộc trò chuyện Hỏi đáp (.txt)",
            data=chat_text,
            file_name="cuoc_tro_chuyen_vatly12.txt",
            mime="text/plain",
        )


def _make_session_title(messages: list) -> str:
    """Tạo tiêu đề ngắn cho 1 cuộc trò chuyện, lấy từ câu hỏi đầu tiên của học sinh."""
    for m in messages:
        if m["role"] == "user":
            text = m["content"].strip().replace("\n", " ")
            return (text[:45] + "…") if len(text) > 45 else text
    return "Cuộc trò chuyện"


def _sync_current_qna_session():
    """
    Đồng bộ cuộc trò chuyện ĐANG MỞ vào danh sách lịch sử - CẬP NHẬT đúng 1 bản ghi
    (theo qna_active_id) thay vì thêm bản mới mỗi lần, để không bị nhân bản khi
    chuyển qua lại giữa các cuộc.
    """
    if not st.session_state.get("messages"):
        return
    sessions = rag_utils.load_chat_history(QNA_SESSIONS_FILE)
    active_id = st.session_state.get("qna_active_id")

    if active_id:
        for s in sessions:
            if s["id"] == active_id:
                s["messages"] = st.session_state.messages
                s["title"] = _make_session_title(st.session_state.messages)
                break
        else:
            # id đang mở không còn trong danh sách (ví dụ vừa bị xoá) -> thêm lại
            sessions.insert(0, {
                "id": active_id,
                "title": _make_session_title(st.session_state.messages),
                "created_at": datetime.datetime.now().strftime("%d/%m %H:%M"),
                "messages": st.session_state.messages,
            })
    else:
        # Cuộc hoàn toàn mới, chưa có id -> tạo id và thêm đúng 1 lần
        new_id = str(uuid.uuid4())
        st.session_state.qna_active_id = new_id
        rag_utils.save_tutor_state({"id": new_id}, QNA_ACTIVE_ID_FILE)
        sessions.insert(0, {
            "id": new_id,
            "title": _make_session_title(st.session_state.messages),
            "created_at": datetime.datetime.now().strftime("%d/%m %H:%M"),
            "messages": st.session_state.messages,
        })

    rag_utils.save_chat_history(sessions, QNA_SESSIONS_FILE)


# ---------- CHẾ ĐỘ 1: HỎI ĐÁP ----------

def render_qna_mode():
    st.subheader("💬 Hỏi đáp Vật lý 12")
    st.caption("Hỏi bất cứ điều gì về chương trình Vật lý lớp 12 - có thể dựa trên tài liệu bạn tải lên.")

    if "messages" not in st.session_state:
        st.session_state.messages = rag_utils.load_chat_history(CHAT_HISTORY_FILE)
    if "qna_active_id" not in st.session_state:
        st.session_state.qna_active_id = rag_utils.load_tutor_state(QNA_ACTIVE_ID_FILE).get("id")

    col_new, col_hist = st.columns([1.3, 3])
    with col_new:
        if st.button("➕ Cuộc trò chuyện mới", key="qna_new_chat"):
            st.session_state.messages = []
            st.session_state.qna_active_id = None
            rag_utils.clear_chat_history(CHAT_HISTORY_FILE)
            rag_utils.save_tutor_state({"id": None}, QNA_ACTIVE_ID_FILE)
            st.rerun()

    qna_sessions = rag_utils.load_chat_history(QNA_SESSIONS_FILE)
    with col_hist:
        with st.expander(f"🕘 Lịch sử trò chuyện ({len(qna_sessions)})"):
            if not qna_sessions:
                st.caption("Chưa có cuộc trò chuyện nào được lưu.")
            else:
                with st.container(height=300):  # khung cố định, tự cuộn khi danh sách dài
                    for s in qna_sessions:
                        c1, c2, c3 = st.columns([4, 1, 0.6])
                        with c1:
                            st.caption(f"{s['created_at']} — {s['title']}")
                        with c2:
                            if st.button("Mở lại", key=f"qna_open_{s['id']}"):
                                st.session_state.messages = s["messages"]
                                st.session_state.qna_active_id = s["id"]
                                rag_utils.save_chat_history(st.session_state.messages, CHAT_HISTORY_FILE)
                                rag_utils.save_tutor_state({"id": s["id"]}, QNA_ACTIVE_ID_FILE)
                                st.rerun()
                        with c3:
                            if st.button("🗑️", key=f"qna_del_{s['id']}", help="Xoá cuộc trò chuyện này"):
                                remaining = [x for x in qna_sessions if x["id"] != s["id"]]
                                rag_utils.save_chat_history(remaining, QNA_SESSIONS_FILE)
                                if st.session_state.get("qna_active_id") == s["id"]:
                                    st.session_state.messages = []
                                    st.session_state.qna_active_id = None
                                    rag_utils.clear_chat_history(CHAT_HISTORY_FILE)
                                    rag_utils.save_tutor_state({"id": None}, QNA_ACTIVE_ID_FILE)
                                st.rerun()

    for i, msg in enumerate(st.session_state.messages):
        with st.chat_message("user" if msg["role"] == "user" else "assistant"):
            st.markdown(msg["content"])
            if msg["role"] != "user":
                tts.speak_button(msg["content"], key=f"qna_hist_{i}")
            if msg.get("sources"):
                with st.expander("📎 Nguồn tài liệu đã tham khảo"):
                    for s in msg["sources"]:
                        st.caption(f"{s['source']} — trang {s['page']}")
                        st.text(s["text"][:300] + ("..." if len(s["text"]) > 300 else ""))

    question = st.chat_input("Nhập câu hỏi Vật lý của bạn...", key="qna_input")

    if question:
        st.session_state.messages.append({"role": "user", "content": question})
        rag_utils.save_chat_history(st.session_state.messages, CHAT_HISTORY_FILE)
        _sync_current_qna_session()
        with st.chat_message("user"):
            st.markdown(question)

        embeddings, chunks = rag_utils.load_vectorstore(EMBEDDINGS_FILE, CHUNKS_FILE)
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
                if answer:
                    tts.speak_button(answer, key=f"qna_live_{len(st.session_state.messages)}")
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
            st.session_state.messages.append(
                {"role": "model", "content": answer, "sources": sources or []}
            )
            rag_utils.save_chat_history(st.session_state.messages, CHAT_HISTORY_FILE)
            _sync_current_qna_session()
            st.rerun()


# ---------- CHẾ ĐỘ 2: GIA SƯ AI ----------

def _tutor_turn(user_text: str):
    """Gửi 1 lượt (câu trả lời của học sinh, hoặc yêu cầu ẩn) tới Gia sư AI, hiển thị + lưu kết quả."""
    st.session_state.tutor_messages.append({"role": "user", "content": user_text})
    rag_utils.save_chat_history(st.session_state.tutor_messages, TUTOR_HISTORY_FILE)
    with st.chat_message("user"):
        st.markdown(user_text)

    # Tìm lại đoạn tài liệu liên quan tới lượt NÀY (không chỉ lúc mở đầu bài), để bám sát tài liệu xuyên suốt.
    # Nếu học sinh đã chọn đúng 1 file cho bài này, CHỈ tìm trong file đó - tránh lẫn nội dung bài khác.
    augmented_text = user_text
    embeddings, chunks = rag_utils.load_vectorstore(EMBEDDINGS_FILE, CHUNKS_FILE)
    if embeddings is not None and len(chunks) > 0:
        allowed = [st.session_state.tutor_source] if st.session_state.get("tutor_source") else None
        results = rag_utils.retrieve(client, user_text, embeddings, chunks, allowed_sources=allowed)
        context_text = ""
        for chunk, score in results:
            context_text += f"\n---\n(Nguồn: {chunk['source']}, trang {chunk['page']})\n{chunk['text']}\n"
        if context_text:
            augmented_text = f"TÀI LIỆU THAM KHẢO:{context_text}\n\n{user_text}"

    history = [
        types.Content(role=("user" if m["role"] == "user" else "model"), parts=[types.Part(text=m["content"])])
        for m in st.session_state.tutor_messages[:-1]
    ]
    history.append(types.Content(role="user", parts=[types.Part(text=augmented_text)]))

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
        rag_utils.save_chat_history(st.session_state.tutor_messages, TUTOR_HISTORY_FILE)
        st.rerun()


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

        # Lưu vào lịch sử điểm (chỉ lưu 1 lần/bộ câu hỏi, tránh lưu lặp mỗi lần rerun)
        if not st.session_state.get("tutor_quiz_recorded"):
            school.append_quiz_record(
                username, topic=st.session_state.tutor_topic, score=score, total=len(quiz), source="tutor"
            )
            st.session_state.tutor_quiz_recorded = True

        if st.button("🔄 Làm bộ câu hỏi khác"):
            for i in range(len(quiz)):
                st.session_state.pop(f"quiz_radio_{i}", None)
            st.session_state.tutor_quiz = None
            st.session_state.tutor_quiz_submitted = False
            st.session_state.tutor_quiz_recorded = False
            st.rerun()


def _generate_mindmap_md(client, topic: str) -> str:
    """Yêu cầu Gemini tóm tắt buổi học thành 1 outline markdown để vẽ mindmap."""
    history_text = "\n".join(
        f"{'Học sinh' if m['role'] == 'user' else 'Gia sư'}: {m['content']}"
        for m in st.session_state.tutor_messages
    )
    prompt = config.MINDMAP_PROMPT_TEMPLATE.format(topic=topic, history=history_text[:8000])

    response = rag_utils.call_with_retry(
        client.models.generate_content,
        model=config.MODEL_NAME,
        contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
        config=types.GenerateContentConfig(temperature=0.3, max_output_tokens=700),
    )
    md = response.text.strip()
    if md.startswith("```"):
        md = md.strip("`")
        if md.lower().startswith("markdown"):
            md = md[len("markdown"):]
    return md.strip()


def _filter_relevant_videos(client, topic: str, candidates: list) -> list:
    """Nhờ Gemini chọn lọc lại, chỉ giữ tối đa 2 video THỰC SỰ liên quan đến bài học (có thể 0 hoặc 1)."""
    if not candidates:
        return []

    listing = "\n".join(f"{i}. {v['title']} (kênh: {v['channel']})" for i, v in enumerate(candidates))
    prompt = (
        f'Bài học đang dạy: "{topic}".\n\n'
        f"Danh sách video tìm được trên YouTube:\n{listing}\n\n"
        "Trong số này, chọn TỐI ĐA 2 video mà tên video cho thấy THỰC SỰ minh hoạ trực tiếp đúng hiện "
        "tượng/kiến thức của bài học trên - bỏ qua video không liên quan, chung chung, hoặc không chắc chắn. "
        "Nếu không video nào thực sự phù hợp, trả về mảng rỗng. CHỈ trả lời bằng JSON dạng mảng chỉ số "
        "(index, bắt đầu từ 0), ví dụ [0, 2] hoặc [1] hoặc []. Không thêm chữ nào khác."
    )
    response = rag_utils.call_with_retry(
        client.models.generate_content,
        model=config.MODEL_NAME,
        contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
        config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=60),
    )
    raw = response.text.strip()
    match = re.search(r"\[.*?\]", raw, re.DOTALL)
    indices = json.loads(match.group(0)) if match else []
    return [candidates[i] for i in indices if isinstance(i, int) and 0 <= i < len(candidates)]


def render_tutor_mode():
    st.subheader("🎓 Gia sư AI - học 1 kèm 1")
    st.caption(
        "Gia sư sẽ chủ động dẫn dắt: mở đầu bằng một tình huống thực tế, đặt câu hỏi, "
        "chờ em trả lời, rồi mới giảng bài theo từng phần nhỏ - không phải chỉ hỏi gì đáp nấy."
    )

    if "tutor_messages" not in st.session_state:
        st.session_state.tutor_messages = rag_utils.load_chat_history(TUTOR_HISTORY_FILE)
    if "tutor_topic" not in st.session_state:
        tutor_state = rag_utils.load_tutor_state(TUTOR_STATE_FILE)
        st.session_state.tutor_topic = tutor_state.get("topic")
        st.session_state.tutor_source = tutor_state.get("source")  # tên file, hoặc None = không giới hạn

    # ----- CHƯA CHỌN BÀI: chỉ cần chọn 1 file tài liệu, Gia sư tự đọc và dạy theo đúng nội dung đó -----
    if not st.session_state.tutor_topic:
        embeddings, chunks = rag_utils.load_vectorstore(EMBEDDINGS_FILE, CHUNKS_FILE)
        available_sources = sorted({c["source"] for c in chunks}) if chunks else []

        if not available_sources:
            st.warning(
                "Chưa có tài liệu nào được xử lý. Vào tab 💬 Hỏi đáp, tải file bài học lên và bấm "
                '"Xử lý tài liệu" trước, rồi quay lại đây chọn bài.'
            )
            return

        selected_source = st.selectbox(
            "Chọn file tài liệu muốn học (Gia sư sẽ dạy đúng theo nội dung trong file này)",
            available_sources,
        )

        if st.button("🚀 Bắt đầu buổi học", type="primary"):
            with st.spinner("Gia sư đang đọc tài liệu và chuẩn bị bài học..."):
                # Lấy TOÀN BỘ nội dung của đúng file đã chọn (không tìm theo từ khoá), sắp theo trang
                source_chunks = sorted(
                    (c for c in chunks if c["source"] == selected_source),
                    key=lambda c: c.get("page", 0),
                )
                full_text = "\n---\n".join(c["text"] for c in source_chunks)

                max_chars = 15000  # phòng khi lỡ chọn nhầm 1 file rất lớn, tránh prompt quá dài
                truncated_note = ""
                if len(full_text) > max_chars:
                    full_text = full_text[:max_chars]
                    truncated_note = "\n\n(Tài liệu khá dài, chỉ lấy phần đầu để giảng dạy.)"

                topic = os.path.splitext(selected_source)[0]

                kickoff = (
                    f'Học sinh muốn được dạy TOÀN BỘ nội dung trong tài liệu "{selected_source}".\n\n'
                    f"TOÀN BỘ NỘI DUNG TÀI LIỆU:\n{full_text}{truncated_note}\n\n"
                    "Hãy tự xác định đây là bài học gì, chia thành các phần kiến thức nhỏ dựa ĐÚNG theo "
                    "nội dung trên, rồi bắt đầu buổi học đúng quy trình: BƯỚC 1 - tạo tình huống mở đầu "
                    "gây tò mò liên quan trực tiếp đến nội dung này, rồi DỪNG LẠI chờ học sinh trả lời. "
                    "Không giảng lý thuyết ngay, không tự hỏi rồi tự trả lời thay học sinh."
                )

                try:
                    response = rag_utils.call_with_retry(
                        client.models.generate_content,
                        model=config.MODEL_NAME,
                        contents=[types.Content(role="user", parts=[types.Part(text=kickoff)])],
                        config=types.GenerateContentConfig(
                            system_instruction=config.TUTOR_SYSTEM_INSTRUCTION,
                            temperature=0.6,
                            max_output_tokens=config.MAX_OUTPUT_TOKENS_TUTOR,
                        ),
                    )
                    st.session_state.tutor_topic = topic
                    st.session_state.tutor_source = selected_source
                    st.session_state.tutor_messages = [{"role": "model", "content": response.text}]
                    rag_utils.save_tutor_state(
                        {"topic": st.session_state.tutor_topic, "source": selected_source},
                        TUTOR_STATE_FILE,
                    )
                    rag_utils.save_chat_history(st.session_state.tutor_messages, TUTOR_HISTORY_FILE)
                    st.rerun()
                except Exception as e:
                    st.error(f"Không khởi động được buổi học, thử lại nhé.\n\n(Chi tiết: {e})")
        return

    # ----- ĐANG TRONG BUỔI HỌC -----
    col1, col2 = st.columns([5, 1.3])
    with col1:
        source_note = f" (tài liệu: {st.session_state.tutor_source})" if st.session_state.get("tutor_source") else ""
        st.info(f"📖 Đang học: **{st.session_state.tutor_topic}**{source_note}")
    with col2:
        if st.button("🔁 Đổi bài học"):
            st.session_state.tutor_topic = None
            st.session_state.tutor_source = None
            st.session_state.tutor_messages = []
            rag_utils.save_tutor_state({"topic": None, "source": None}, TUTOR_STATE_FILE)
            rag_utils.clear_chat_history(TUTOR_HISTORY_FILE)
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
    col_summary, col_quiz, col_mindmap, col_video = st.columns(4)
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
                    st.session_state.tutor_quiz_recorded = False
                    st.rerun()
                except Exception as e:
                    st.error(f"Không soạn được trắc nghiệm, thử lại nhé.\n\n(Chi tiết: {e})")
    with col_mindmap:
        if st.button("🧠 Tạo Mindmap buổi học"):
            with st.spinner("Gia sư đang vẽ sơ đồ tư duy..."):
                try:
                    st.session_state.tutor_mindmap_md = _generate_mindmap_md(client, st.session_state.tutor_topic)
                    st.rerun()
                except Exception as e:
                    st.error(f"Không tạo được mindmap, thử lại nhé.\n\n(Chi tiết: {e})")
    with col_video:
        if st.button("🎬 Tìm video minh hoạ"):
            st.session_state.show_video_search = True
            st.rerun()

    if st.session_state.get("tutor_quiz"):
        st.divider()
        _render_quiz()

    if st.session_state.get("tutor_mindmap_md"):
        st.divider()
        st.markdown("### 🧠 Mindmap buổi học")
        st.caption("Kéo để di chuyển, cuộn chuột để phóng to/thu nhỏ, bấm vào 1 nhánh để thu gọn/mở rộng.")
        mindmap.render_mindmap(st.session_state.tutor_mindmap_md)
        st.download_button(
            "💾 Tải outline mindmap (.md)",
            data=st.session_state.tutor_mindmap_md,
            file_name=f"mindmap_{st.session_state.tutor_topic}.md",
            mime="text/markdown",
        )
        if st.button("🔄 Tạo mindmap khác"):
            st.session_state.tutor_mindmap_md = None
            st.rerun()

    if st.session_state.get("show_video_search"):
        st.divider()
        st.markdown("### 🎬 Video minh hoạ (YouTube, dưới 3 phút)")
        youtube_key = get_youtube_key()
        if not youtube_key:
            st.warning(
                "Chưa cấu hình YOUTUBE_API_KEY. Xem hướng dẫn tạo key trong README.md, rồi thêm vào "
                "file `.env` (máy local) hoặc Secrets (Streamlit Cloud) với tên `YOUTUBE_API_KEY`."
            )
        else:
            search_query = st.text_input(
                "Tìm video về hiện tượng nào?",
                value=st.session_state.tutor_topic,
                key="video_search_query",
            )
            if st.button("🔍 Tìm video", key="video_search_button"):
                with st.spinner("Đang tìm và chọn lọc video phù hợp..."):
                    try:
                        candidates = youtube_utils.search_short_videos(
                            youtube_key, search_query + " vật lý thí nghiệm minh hoạ", max_results=8
                        )
                        st.session_state.tutor_videos = _filter_relevant_videos(
                            client, search_query, candidates
                        )
                    except Exception as e:
                        st.error(f"Không tìm được video, thử lại nhé.\n\n(Chi tiết: {e})")

            videos = st.session_state.get("tutor_videos")
            if videos:
                for v in videos:
                    vcol1, vcol2 = st.columns([1, 3])
                    with vcol1:
                        st.image(v["thumbnail"])
                    with vcol2:
                        st.markdown(f"**[{v['title']}]({v['url']})**")
                        st.caption(f"{v['channel']} • {youtube_utils.format_duration(v['duration_seconds'])}")
            elif videos is not None:
                st.info("Không tìm thấy video nào thực sự phù hợp với đúng nội dung bài học, thử đổi từ khoá khác xem sao.")


# ---------- CHẾ ĐỘ 3: QUÉT & GIẢI ĐỀ TỪ ẢNH ----------

def render_solve_mode():
    st.subheader("📷 Quét & giải đề từ ảnh")
    st.caption(
        "Chụp hoặc chọn ảnh đề bài Vật lý (viết tay hoặc in), tải lên, Gemini sẽ đọc và giải chi tiết."
    )

    if "solve_uploader_key" not in st.session_state:
        st.session_state.solve_uploader_key = 0

    if st.button("➕ Giải bài mới", key="solve_new"):
        st.session_state.solve_uploader_key += 1  # đổi key -> uploader tự làm mới, ảnh/ghi chú cũ mất đi
        st.rerun()

    solve_sessions = rag_utils.load_chat_history(SOLVE_SESSIONS_FILE)
    st.markdown(f"#### 🕘 Lịch sử đã giải ({len(solve_sessions)})")
    if not solve_sessions:
        st.caption("Chưa giải đề nào được lưu.")
    else:
        with st.container(height=220):  # khung cố định, tự cuộn khi danh sách dài - không phình trang
            for s in solve_sessions:
                with st.expander(f"{s['created_at']} — {s['title']}"):
                    if st.button("🗑️ Xoá mục này", key=f"solve_del_{s['id']}"):
                        remaining = [x for x in solve_sessions if x["id"] != s["id"]]
                        rag_utils.save_chat_history(remaining, SOLVE_SESSIONS_FILE)
                        st.rerun()
                    st.markdown(s["answer"])
                    tts.speak_button(s["answer"], key=f"solve_hist_{s['id']}")
    st.divider()

    image_file = st.file_uploader(
        "Tải ảnh đề bài",
        type=["png", "jpg", "jpeg", "webp"],
        key=f"solve_image_uploader_{st.session_state.solve_uploader_key}",
    )

    if image_file:
        st.image(image_file, caption="Đề bài đã tải lên", width=380)

        extra_note = st.text_input(
            "Ghi chú thêm cho Gia sư (không bắt buộc)",
            placeholder="Ví dụ: chỉ cần đáp số, hoặc giải câu b thôi...",
            key=f"solve_extra_note_{st.session_state.solve_uploader_key}",
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
                answer_text = st.write_stream(_stream_text(response_stream))

                new_id = str(uuid.uuid4())
                if answer_text:
                    tts.speak_button(answer_text, key=f"solve_live_{new_id}")

                solve_sessions = rag_utils.load_chat_history(SOLVE_SESSIONS_FILE)
                solve_sessions.insert(0, {
                    "id": new_id,
                    "title": extra_note.strip() if extra_note.strip() else "Đề bài không ghi chú",
                    "created_at": datetime.datetime.now().strftime("%d/%m %H:%M"),
                    "answer": answer_text,
                })
                rag_utils.save_chat_history(solve_sessions, SOLVE_SESSIONS_FILE)
            except Exception as e:
                st.error(
                    "Không đọc/giải được ảnh này, có thể do Gemini đang quá tải hoặc ảnh quá mờ. "
                    f"Thử lại hoặc chụp rõ hơn nhé.\n\n(Chi tiết: {e})"
                )
    else:
        st.info("Chưa có ảnh nào được tải lên.")


# ---------- CHẾ ĐỘ 4 (HỌC SINH): BÀI TẬP ĐƯỢC GIAO ----------

def _render_assignment_quiz(assignment: dict):
    quiz = assignment["quiz"]
    submitted = st.session_state.get("assignment_submitted", False)

    st.markdown(f"### 📝 {assignment['title']}")
    st.caption(f"Chủ đề: {assignment['topic']} • Hạn nộp: {assignment['due_date']}")

    for i, q in enumerate(quiz):
        st.markdown(f"**Câu {i + 1}. {q['question']}**")
        option_keys = sorted(q["options"].keys())
        labels = [f"{k}. {q['options'][k]}" for k in option_keys]
        st.radio(
            f"Câu {i + 1}", labels, key=f"assign_radio_{i}", index=None, label_visibility="collapsed"
        )
        if submitted:
            chosen = st.session_state.get(f"assign_radio_{i}")
            chosen_letter = chosen[0] if chosen else None
            if chosen_letter == q["correct"]:
                st.success(f"✔️ Đúng! {q.get('explanation', '')}")
            else:
                st.error(f"❌ Đáp án đúng là **{q['correct']}**. {q.get('explanation', '')}")
        st.divider()

    if not submitted:
        if st.button("✅ Nộp bài", key="assign_submit_btn", type="primary"):
            answers = [st.session_state.get(f"assign_radio_{i}") for i in range(len(quiz))]
            score = sum(1 for i, q in enumerate(quiz) if (answers[i] or " ")[0] == q["correct"])
            school.record_submission(assignment["id"], username, answers, score, len(quiz))
            school.append_quiz_record(
                username, topic=assignment["topic"], score=score, total=len(quiz),
                source="assignment", assignment_id=assignment["id"],
            )
            st.session_state.assignment_submitted = True
            st.rerun()
    else:
        sub = school.get_submission(assignment["id"], username)
        if sub:
            st.info(f"🎯 Điểm của bạn: **{sub['score']}/{sub['total']}** (đã nộp lúc {sub['submitted_at']})")


def render_assignments_mode():
    st.subheader("📌 Bài tập được giao")

    if not MY_CLASS_ID:
        st.info("Tài khoản của bạn chưa được gán vào lớp nào. Liên hệ giáo viên để được thêm vào lớp.")
        return

    assignments = sorted(
        school.list_assignments_for_class(MY_CLASS_ID), key=lambda a: a["created_at"], reverse=True
    )
    if not assignments:
        st.caption("Chưa có bài tập nào được giao.")
        return

    open_id = st.session_state.get("open_assignment_id")
    if open_id:
        assignment = school.get_assignment(open_id)
        if assignment is None:
            st.session_state.open_assignment_id = None
        else:
            if st.button("← Quay lại danh sách bài tập"):
                st.session_state.open_assignment_id = None
                st.session_state.assignment_submitted = False
                for i in range(len(assignment["quiz"])):
                    st.session_state.pop(f"assign_radio_{i}", None)
                st.rerun()
            if school.get_submission(assignment["id"], username):
                st.session_state.assignment_submitted = True
            _render_assignment_quiz(assignment)
            return

    for a in assignments:
        sub = school.get_submission(a["id"], username)
        with st.container(border=True):
            c1, c2 = st.columns([4, 1.4])
            with c1:
                st.markdown(f"**{a['title']}**")
                st.caption(f"Chủ đề: {a['topic']} • Hạn nộp: {a['due_date']} • {len(a['quiz'])} câu hỏi")
            with c2:
                if sub:
                    st.success(f"Đã nộp: {sub['score']}/{sub['total']}")
                else:
                    if st.button("Làm bài", key=f"do_assign_{a['id']}"):
                        st.session_state.open_assignment_id = a["id"]
                        st.session_state.assignment_submitted = False
                        st.rerun()


# ---------- GIÁO VIÊN: QUẢN LÝ LỚP + GIAO BÀI TẬP ----------

def render_teacher_class_mode():
    st.subheader("🏫 Quản lý lớp")

    my_classes = school.list_classes_for_teacher(username)
    if not my_classes:
        st.warning(
            "Bạn chưa phụ trách lớp nào. Mở terminal ở máy đang chạy app và chạy "
            "`python manage.py` để tạo lớp mới (menu 1)."
        )
        return

    class_names = {c["id"]: c["name"] for c in my_classes}
    selected_class_id = st.selectbox(
        "Chọn lớp", options=list(class_names.keys()), format_func=lambda cid: class_names[cid],
        key="teacher_selected_class",
    )

    students = school.list_students_in_class(selected_class_id)
    st.caption(f"Sĩ số: {len(students)} học sinh")
    if students:
        with st.expander(f"👥 Danh sách học sinh ({len(students)})"):
            for s in students:
                st.write(f"- {s['name']} (`{s['username']}`)")
    else:
        st.info("Lớp này chưa có học sinh. Chạy `python manage.py` (menu 3) để thêm.")

    st.divider()
    st.markdown("### 📌 Giao bài tập trắc nghiệm mới")

    embeddings, chunks = rag_utils.load_vectorstore(EMBEDDINGS_FILE, CHUNKS_FILE)
    available_sources = sorted({c["source"] for c in chunks}) if chunks else []

    if not available_sources:
        st.info(
            "Bạn cần tải lên ít nhất 1 tài liệu (ở sidebar bên trái) và bấm \"Xử lý tài liệu\" "
            "trước, để dùng làm nguồn soạn câu hỏi."
        )
    else:
        selected_source = st.selectbox("Tài liệu nguồn", available_sources, key="assign_source_select")
        default_topic = os.path.splitext(selected_source)[0]
        title = st.text_input("Tiêu đề bài tập", value=f"Bài tập: {default_topic}", key="assign_title")
        col_n, col_d = st.columns(2)
        with col_n:
            num_questions = st.number_input(
                "Số câu hỏi", min_value=3, max_value=15, value=5, key="assign_numq"
            )
        with col_d:
            due_date = st.date_input("Hạn nộp", key="assign_due")

        if st.button("🚀 Tạo & giao bài tập", type="primary"):
            with st.spinner("Đang soạn câu hỏi từ tài liệu..."):
                try:
                    source_chunks = sorted(
                        (c for c in chunks if c["source"] == selected_source),
                        key=lambda c: c.get("page", 0),
                    )
                    full_text = "\n---\n".join(c["text"] for c in source_chunks)
                    max_chars = 15000
                    if len(full_text) > max_chars:
                        full_text = full_text[:max_chars]

                    prompt = config.ASSIGNMENT_QUIZ_PROMPT_TEMPLATE.format(
                        topic=default_topic, num_questions=int(num_questions), content=full_text
                    )
                    response = rag_utils.call_with_retry(
                        client.models.generate_content,
                        model=config.MODEL_NAME,
                        contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
                        config=types.GenerateContentConfig(temperature=0.4, max_output_tokens=2500),
                    )
                    raw = response.text.strip()
                    match = re.search(r"\[.*\]", raw, re.DOTALL)
                    quiz = json.loads(match.group(0) if match else raw)

                    school.create_assignment(
                        class_id=selected_class_id,
                        title=title,
                        topic=default_topic,
                        due_date=due_date.strftime("%d/%m/%Y"),
                        quiz=quiz,
                        created_by=username,
                        source_doc=selected_source,
                    )
                    st.success(f'Đã giao bài tập "{title}" cho lớp {class_names[selected_class_id]}.')
                    st.rerun()
                except Exception as e:
                    st.error(f"Không soạn được bài tập, thử lại nhé.\n\n(Chi tiết: {e})")

    st.divider()
    st.markdown("### 📋 Bài tập đã giao")
    assignments = sorted(
        school.list_assignments_for_class(selected_class_id), key=lambda a: a["created_at"], reverse=True
    )
    if not assignments:
        st.caption("Chưa giao bài tập nào cho lớp này.")
    for a in assignments:
        with st.expander(f"{a['title']} — hạn {a['due_date']} (giao lúc {a['created_at']})"):
            submissions = school.load_submissions(a["id"])
            rows = [
                {
                    "Học sinh": s["name"],
                    "Trạng thái": "Đã nộp" if submissions.get(s["username"]) else "Chưa nộp",
                    "Điểm": (
                        f"{submissions[s['username']]['score']}/{submissions[s['username']]['total']}"
                        if submissions.get(s["username"]) else "-"
                    ),
                    "Nộp lúc": submissions.get(s["username"], {}).get("submitted_at", "-"),
                }
                for s in students
            ]
            if rows:
                st.dataframe(rows, use_container_width=True, hide_index=True)
            else:
                st.caption("Lớp chưa có học sinh nào để nộp bài.")
            if st.button("🗑️ Xoá bài tập này", key=f"del_assign_{a['id']}"):
                school.delete_assignment(a["id"])
                st.rerun()


# ---------- GIÁO VIÊN: THEO DÕI TIẾN ĐỘ HỌC SINH ----------

def render_teacher_progress_mode():
    st.subheader("📈 Theo dõi học sinh")

    my_classes = school.list_classes_for_teacher(username)
    if not my_classes:
        st.warning("Bạn chưa phụ trách lớp nào.")
        return

    class_names = {c["id"]: c["name"] for c in my_classes}
    selected_class_id = st.selectbox(
        "Chọn lớp", options=list(class_names.keys()), format_func=lambda cid: class_names[cid],
        key="progress_selected_class",
    )

    students = school.list_students_in_class(selected_class_id)
    if not students:
        st.caption("Lớp này chưa có học sinh.")
        return

    student_names = {s["username"]: s["name"] for s in students}
    selected_student = st.selectbox(
        "Chọn học sinh", options=list(student_names.keys()), format_func=lambda u: student_names[u],
        key="progress_selected_student",
    )

    st.markdown("### 🎯 Lịch sử điểm trắc nghiệm")
    quiz_history = school.load_quiz_history(selected_student)
    if not quiz_history:
        st.caption("Học sinh này chưa làm bài trắc nghiệm nào.")
    else:
        rows = [
            {
                "Ngày": r["date"],
                "Chủ đề": r["topic"],
                "Điểm": f"{r['score']}/{r['total']}",
                "Tỉ lệ (%)": round(100 * r["score"] / r["total"]) if r["total"] else 0,
                "Nguồn": "Bài được giao" if r["source"] == "assignment" else "Tự ôn (Gia sư AI)",
            }
            for r in quiz_history
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)
        st.caption("Biểu đồ tỉ lệ điểm (%) qua từng lần làm bài, theo thứ tự thời gian:")
        st.line_chart([r["Tỉ lệ (%)"] for r in rows])

    st.divider()
    st.markdown("### 💬 Lịch sử hỏi đáp gần đây")
    qna_sessions = rag_utils.load_chat_history(config.qna_sessions_file(selected_student))
    if not qna_sessions:
        st.caption("Chưa có cuộc hỏi đáp nào.")
    else:
        for s in qna_sessions[:10]:
            with st.expander(f"{s['created_at']} — {s['title']}"):
                for m in s["messages"]:
                    role_label = "Học sinh" if m["role"] == "user" else "Chatbot"
                    st.markdown(f"**{role_label}:** {m['content']}")

    st.divider()
    st.markdown("### 🎓 Buổi học với Gia sư AI")
    tutor_state = rag_utils.load_tutor_state(config.tutor_state_file(selected_student))
    tutor_topic = tutor_state.get("topic")
    if not tutor_topic:
        st.caption("Chưa học buổi nào với Gia sư AI.")
    else:
        st.caption(f"Đang/đã học: **{tutor_topic}**")
        tutor_messages = rag_utils.load_chat_history(config.tutor_history_file(selected_student))
        with st.expander(f"Xem transcript buổi học ({len(tutor_messages)} lượt)"):
            for m in tutor_messages:
                role_label = "Học sinh" if m["role"] == "user" else "Gia sư AI"
                st.markdown(f"**{role_label}:** {m['content']}")


# ---------- GIAO DIỆN CHÍNH ----------

st.title("⚛️ Trợ lý học Vật lý 12")

tab_qna, tab_tutor, tab_solve = st.tabs(["💬 Hỏi đáp", "🎓 Gia sư AI", "📷 Giải đề từ ảnh"])
with tab_qna:
    render_qna_mode()
with tab_tutor:
    render_tutor_mode()
with tab_solve:
    render_solve_mode()
