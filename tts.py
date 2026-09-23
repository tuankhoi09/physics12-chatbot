"""
Đọc to (Text-to-Speech) văn bản Gia sư AI vừa nói, ngay trong trình duyệt -
KHÔNG cần gọi thêm API nào (dùng Web Speech API có sẵn trong Chrome/Edge),
nên hoàn toàn miễn phí và không giới hạn.

Có nút Nghe / Tạm dừng / Tiếp tục, để học sinh chủ động điều khiển.

Lưu ý: giọng đọc phụ thuộc vào trình duyệt/hệ điều hành của người dùng.
Trên Windows + Chrome/Edge thường có sẵn giọng tiếng Việt; nếu máy không có
giọng tiếng Việt, trình duyệt sẽ tự dùng giọng mặc định (có thể đọc hơi ngang).
"""

import streamlit.components.v1 as components


def speak_button(text: str, key: str, height: int = 46) -> None:
    """
    Hiện 2 nút ngay dưới đoạn text được truyền vào:
      - "🔊 Nghe": bắt đầu đọc to đoạn text bằng giọng tiếng Việt của trình duyệt.
      - "⏸️ Tạm dừng" / "▶️ Tiếp tục": tạm dừng và tiếp tục lại đúng chỗ đang đọc dở.
    `key` phải là duy nhất cho mỗi nút trên cùng 1 trang (ví dụ số thứ tự tin nhắn).
    """
    # Escape để nhét an toàn vào chuỗi JS (backtick template string)
    safe_text = (
        text.replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("</", "<\\/")
    )

    html = f"""
    <div style="display:flex; align-items:center; gap:8px;">
        <button id="play_{key}" style="
            font-size:12px; padding:4px 10px; border-radius:6px;
            border:1px solid rgba(150,150,150,0.5); background:transparent;
            cursor:pointer; color:inherit;">
            🔊 Nghe
        </button>
        <button id="pause_{key}" disabled style="
            font-size:12px; padding:4px 10px; border-radius:6px;
            border:1px solid rgba(150,150,150,0.5); background:transparent;
            cursor:pointer; color:inherit; opacity:0.5;">
            ⏸️ Tạm dừng
        </button>
        <span id="status_{key}" style="font-size:11px; opacity:0.7;"></span>
    </div>
    <script>
    (function () {{
        const playBtn = document.getElementById("play_{key}");
        const pauseBtn = document.getElementById("pause_{key}");
        const status = document.getElementById("status_{key}");
        const text = `{safe_text}`;
        let currentUtter = null;

        function setPauseEnabled(enabled) {{
            pauseBtn.disabled = !enabled;
            pauseBtn.style.opacity = enabled ? "1" : "0.5";
        }}

        playBtn.addEventListener("click", function () {{
            if (!("speechSynthesis" in window)) {{
                status.textContent = "Trình duyệt không hỗ trợ đọc giọng nói";
                return;
            }}
            window.speechSynthesis.cancel();  // dừng câu đang đọc dở ở nút khác (nếu có)

            currentUtter = new SpeechSynthesisUtterance(text);
            currentUtter.lang = "vi-VN";
            currentUtter.rate = 0.95;

            const voices = window.speechSynthesis.getVoices();
            const viVoice = voices.find(v => v.lang && v.lang.toLowerCase().startsWith("vi"));
            if (viVoice) currentUtter.voice = viVoice;

            currentUtter.onstart = () => {{
                status.textContent = "Đang đọc...";
                setPauseEnabled(true);
                pauseBtn.textContent = "⏸️ Tạm dừng";
            }};
            currentUtter.onend = () => {{
                status.textContent = "";
                setPauseEnabled(false);
                pauseBtn.textContent = "⏸️ Tạm dừng";
            }};
            currentUtter.onerror = () => {{
                status.textContent = "Không đọc được";
                setPauseEnabled(false);
            }};

            window.speechSynthesis.speak(currentUtter);
        }});

        pauseBtn.addEventListener("click", function () {{
            if (window.speechSynthesis.speaking && !window.speechSynthesis.paused) {{
                window.speechSynthesis.pause();
                pauseBtn.textContent = "▶️ Tiếp tục";
                status.textContent = "Đã tạm dừng";
            }} else if (window.speechSynthesis.paused) {{
                window.speechSynthesis.resume();
                pauseBtn.textContent = "⏸️ Tạm dừng";
                status.textContent = "Đang đọc...";
            }}
        }});
    }})();
    </script>
    """
    components.html(html, height=height)
