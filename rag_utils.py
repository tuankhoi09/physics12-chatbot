"""
Các hàm phục vụ RAG (Retrieval-Augmented Generation):
- Đọc văn bản từ PDF / TXT
- Chia văn bản thành từng đoạn nhỏ (chunk)
- Tạo embedding bằng Gemini API
- Lưu / tải vector store (dùng numpy, không cần cài database phức tạp)
- Tìm các đoạn liên quan nhất tới câu hỏi (cosine similarity)
"""

import os
import json
import time
import numpy as np
from pypdf import PdfReader
from google.genai import types
from google.genai import errors as genai_errors

import config


# ---------- 0. GỌI API CÓ THỬ LẠI (retry) KHI SERVER QUÁ TẢI ----------

def call_with_retry(func, *args, max_retries: int = 4, base_delay: float = 2.0, **kwargs):
    """
    Gọi func(*args, **kwargs); nếu gặp lỗi 503 (server quá tải) hoặc 429
    (gọi quá nhanh) thì tự động chờ rồi thử lại, thời gian chờ tăng dần
    (2s, 4s, 8s, 16s...). Sau max_retries lần vẫn lỗi thì mới raise ra ngoài.
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except genai_errors.ServerError as e:
            last_error = e
        except genai_errors.ClientError as e:
            # 429 = vượt rate limit tạm thời, cũng đáng để thử lại
            if getattr(e, "code", None) == 429:
                last_error = e
            else:
                raise  # lỗi khác (vd model không tồn tại) thì báo luôn, thử lại vô ích

        wait = base_delay * (2 ** attempt)
        time.sleep(wait)

    raise last_error


# ---------- 1. ĐỌC FILE ----------

def read_pdf(file_path: str) -> list[tuple[str, int]]:
    """Đọc PDF, trả về danh sách (text, số_trang) cho từng trang có nội dung."""
    reader = PdfReader(file_path)
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            pages.append((text, i + 1))
    return pages


def read_txt(file_path: str) -> list[tuple[str, int]]:
    """Đọc file .txt, coi cả file là 1 'trang'."""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        return [(f.read(), 1)]


# ---------- 2. CHIA NHỎ VĂN BẢN (CHUNKING) ----------

def chunk_text(text: str, chunk_size: int = None, overlap: int = None) -> list[str]:
    """Chia 1 đoạn text dài thành các chunk ~chunk_size ký tự, có overlap để giữ ngữ cảnh."""
    chunk_size = chunk_size or config.CHUNK_SIZE
    overlap = overlap or config.CHUNK_OVERLAP

    text = " ".join(text.split())  # gộp khoảng trắng thừa
    if len(text) <= chunk_size:
        return [text] if text else []

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        if end >= len(text):
            break
        start = end - overlap  # lùi lại một chút để đoạn sau không mất ngữ cảnh
    return chunks


# ---------- 3. TẠO EMBEDDING ----------

def embed_text(client, text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> list[float]:
    """Gọi Gemini API để tạo embedding cho 1 đoạn text."""
    result = call_with_retry(
        client.models.embed_content,
        model=config.EMBED_MODEL,
        contents=text,
        config=types.EmbedContentConfig(task_type=task_type),
    )
    return result.embeddings[0].values


def build_vectorstore(client, progress_callback=None) -> int:
    """
    Đọc toàn bộ file trong DATA_DIR, chia chunk, tạo embedding,
    rồi lưu xuống VECTORSTORE_DIR. Trả về số chunk đã tạo.
    """
    os.makedirs(config.VECTORSTORE_DIR, exist_ok=True)

    all_chunks = []  # mỗi phần tử: {"text": ..., "source": ..., "page": ...}
    for filename in sorted(os.listdir(config.DATA_DIR)):
        path = os.path.join(config.DATA_DIR, filename)
        if filename.lower().endswith(".pdf"):
            pages = read_pdf(path)
        elif filename.lower().endswith(".txt"):
            pages = read_txt(path)
        else:
            continue

        for page_text, page_num in pages:
            for chunk in chunk_text(page_text):
                all_chunks.append({"text": chunk, "source": filename, "page": page_num})

    if not all_chunks:
        # Không còn file nào -> xoá sạch chỉ mục cũ, tránh dữ liệu cũ (đã xoá file) còn sót lại
        if os.path.exists(config.EMBEDDINGS_FILE):
            os.remove(config.EMBEDDINGS_FILE)
        if os.path.exists(config.CHUNKS_FILE):
            os.remove(config.CHUNKS_FILE)
        return 0

    embeddings = []
    for i, item in enumerate(all_chunks):
        vec = embed_text(client, item["text"], task_type="RETRIEVAL_DOCUMENT")
        embeddings.append(vec)
        if progress_callback:
            progress_callback(i + 1, len(all_chunks))
        time.sleep(0.3)  # tránh gọi API quá nhanh, vượt giới hạn free tier

    np.save(config.EMBEDDINGS_FILE, np.array(embeddings, dtype=np.float32))
    with open(config.CHUNKS_FILE, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)

    return len(all_chunks)


# ---------- 4. TẢI VECTOR STORE ----------

def load_vectorstore():
    """Trả về (embeddings: np.ndarray | None, chunks: list | None)."""
    if not (os.path.exists(config.EMBEDDINGS_FILE) and os.path.exists(config.CHUNKS_FILE)):
        return None, None
    embeddings = np.load(config.EMBEDDINGS_FILE)
    with open(config.CHUNKS_FILE, "r", encoding="utf-8") as f:
        chunks = json.load(f)
    return embeddings, chunks


# ---------- 4b. LƯU / TẢI LỊCH SỬ TRÒ CHUYỆN ----------

def load_chat_history(path: str = None) -> list:
    """Đọc lịch sử chat đã lưu từ lần trước (nếu có). Trả về [] nếu chưa có gì."""
    path = path or config.CHAT_HISTORY_FILE
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def save_chat_history(messages: list, path: str = None) -> None:
    """Lưu toàn bộ lịch sử chat hiện tại xuống file, để mở lại app vẫn còn."""
    path = path or config.CHAT_HISTORY_FILE
    os.makedirs(config.VECTORSTORE_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)


def clear_chat_history(path: str = None) -> None:
    """Xoá file lịch sử chat đã lưu."""
    path = path or config.CHAT_HISTORY_FILE
    if os.path.exists(path):
        os.remove(path)


def load_tutor_state(path: str = None) -> dict:
    """Đọc 1 trạng thái nhỏ dạng dict đã lưu (mặc định: chủ đề bài học hiện tại của Gia sư AI)."""
    path = path or config.TUTOR_STATE_FILE
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_tutor_state(state: dict, path: str = None) -> None:
    """Lưu 1 trạng thái nhỏ dạng dict, để tắt/mở lại app vẫn giữ đúng."""
    path = path or config.TUTOR_STATE_FILE
    os.makedirs(config.VECTORSTORE_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ---------- 5. TÌM KIẾM ĐOẠN LIÊN QUAN (COSINE SIMILARITY) ----------

def retrieve(client, query: str, embeddings: np.ndarray, chunks: list, top_k: int = None,
             allowed_sources: list = None):
    """
    Trả về top_k chunk có nội dung liên quan nhất tới câu hỏi.
    Nếu allowed_sources được truyền vào (danh sách tên file), CHỈ tìm trong các chunk
    thuộc đúng những file đó - dùng để giới hạn Gia sư AI trong đúng phạm vi 1 bài học.
    """
    top_k = top_k or config.TOP_K

    if allowed_sources:
        keep_idx = [i for i, c in enumerate(chunks) if c["source"] in allowed_sources]
        if not keep_idx:
            return []
        search_embeddings = embeddings[keep_idx]
        search_chunks = [chunks[i] for i in keep_idx]
    else:
        search_embeddings = embeddings
        search_chunks = chunks

    query_vec = np.array(embed_text(client, query, task_type="RETRIEVAL_QUERY"), dtype=np.float32)

    norms = np.linalg.norm(search_embeddings, axis=1) * np.linalg.norm(query_vec)
    norms[norms == 0] = 1e-10
    scores = search_embeddings @ query_vec / norms

    top_indices = np.argsort(scores)[::-1][:top_k]
    return [(search_chunks[i], float(scores[i])) for i in top_indices]
