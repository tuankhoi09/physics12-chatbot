"""
Đọc to (Text-to-Speech) văn bản Gia sư AI vừa nói, ngay trong trình duyệt -
KHÔNG cần gọi thêm API nào (dùng Web Speech API có sẵn trong Chrome/Edge),
nên hoàn toàn miễn phí và không giới hạn.

Chỉ dùng 1 giọng tiếng Việt duy nhất (giọng đầu tiên máy có). Có nút Nghe /
Tạm dừng / Tiếp tục. Trước khi đọc, văn bản được "phiên âm" lại (đổi ký hiệu
toán/lý và tên chữ cái La-tinh sang cách đọc tiếng Việt) để nghe tự nhiên hơn.

Lưu ý kỹ thuật: cố tình dùng regex ĐƠN GIẢN (không lookbehind/lookahead,
không ký tự điều khiển ẩn) để chạy ổn định trên mọi trình duyệt.
"""

import streamlit.components.v1 as components


def speak_button(text: str, key: str, height: int = 46) -> None:
    """
    Hiện 2 nút ngay dưới đoạn text được truyền vào:
      - "🔊 Nghe": đọc to đoạn text (đã phiên âm) bằng giọng tiếng Việt.
      - "⏸️ Tạm dừng" / "▶️ Tiếp tục": tạm dừng và tiếp tục lại đúng chỗ đang đọc dở.
    `key` phải là duy nhất cho mỗi nút trên cùng 1 trang (ví dụ số thứ tự tin nhắn).
    """
    safe_text = (
        text.replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("</", "<\\/")
    )

    html = f"""
    <style>
        html, body {{ margin: 0; padding: 0; background: transparent; }}
        .tts-btn {{
            font-size: 12px; padding: 4px 10px; border-radius: 6px;
            border: 1px solid rgba(90,90,90,0.5);
            background: rgba(140,140,140,0.55);  /* nền xám vừa đủ đậm - luôn tương phản tốt dù trang sáng hay tối */
            cursor: pointer; color: #111111; font-weight: 500;
        }}
        .tts-status {{ font-size: 11px; opacity: 0.9; color: #888888; }}
    </style>
    <div style="display:flex; align-items:center; gap:8px;">
        <button id="play_{key}" class="tts-btn">
            🔊 Nghe
        </button>
        <button id="pause_{key}" class="tts-btn" disabled style="opacity:0.5;">
            ⏸️ Tạm dừng
        </button>
        <span id="status_{key}" class="tts-status"></span>
    </div>
    <script>
    (function () {{
        const playBtn = document.getElementById("play_{key}");
        const pauseBtn = document.getElementById("pause_{key}");
        const status = document.getElementById("status_{key}");
        const rawText = `{safe_text}`;
        let currentUtter = null;

        function vietnamizeForSpeech(input) {{
            var t = input;
            try {{
                // Tên các chữ cái La-tinh, dùng chung cho cả công thức lẫn văn xuôi
                var letterNames = {{
                    a: "a", b: "bê", c: "xê", d: "dê", e: "e", f: "ép", g: "gờ", h: "hát",
                    i: "i", j: "gi", k: "ca", l: "e-lờ", m: "em-mờ", n: "en-nờ", o: "o",
                    p: "bê", q: "quy", r: "e-rờ", s: "ét", t: "tê", u: "u", v: "vê",
                    w: "vê kép", x: "ích", y: "i dài", z: "dét"
                }};

                function convertLatexCommands(s) {{
                    s = s.split("\\\\Delta").join(" đen-ta ");
                    s = s.split("\\\\times").join(" nhân ");
                    s = s.split("\\\\cdot").join(" nhân ");
                    // \\frac{{tử số}}{{mẫu số}} -> "tử số chia mẫu số"
                    // (dùng mã \u007B/\u007D thay ngoặc nhọn thật, tránh rắc rối khi Python xử lý f-string)
                    s = s.replace(/\\\\frac\u007B([^\u007B\u007D]*)\u007D\u007B([^\u007B\u007D]*)\u007D/g,
                        "$1 chia $2");
                    s = s.replace(/\\^2/g, " bình phương");
                    s = s.replace(/\\^3/g, " lập phương");
                    return s;
                }}

                function convertBasicSymbols(s) {{
                    s = s.split("=").join(" bằng ");
                    s = s.split("+").join(" cộng ");
                    s = s.split(" - ").join(" trừ ");  // chỉ đổi trừ có khoảng trắng 2 bên, giữ số âm "-5"
                    s = s.split("×").join(" nhân ");
                    s = s.split("÷").join(" chia ");
                    s = s.split("≈").join(" xấp xỉ bằng ");
                    s = s.split("≠").join(" khác ");
                    s = s.split("≤").join(" nhỏ hơn hoặc bằng ");
                    s = s.split("≥").join(" lớn hơn hoặc bằng ");
                    s = s.split("π").join(" pi ");
                    s = s.split("√").join(" căn ");
                    s = s.split("Ω").join(" ôm ");
                    return s;
                }}

                // Các chữ cái La-tinh đứng LIỀN NHAU (không dấu cách) được hiểu là các đại
                // lượng nhân với nhau, ví dụ "Pt" nghĩa là P nhân t -> tách riêng từng chữ.
                // Bỏ qua các cụm có backslash phía trước (lệnh LaTeX như Delta, frac, times...),
                // để không tách nhầm chúng - những lệnh đó được xử lý riêng ở convertLatexCommands.
                function splitAdjacentLetters(s) {{
                    return s.replace(/\\\\?[a-zA-Z]+/g, function (run) {{
                        if (run.charAt(0) === "\\\\") {{
                            return run;  // lệnh LaTeX -> để nguyên, xử lý ở bước sau
                        }}
                        return run.split("").map(function (ch) {{
                            var nm = letterNames[ch.toLowerCase()];
                            return nm ? nm : ch;
                        }}).join(" nhân ");
                    }});
                }}

                // "độ C" / "độ" / các đơn vị ghép - xử lý sớm, dùng placeholder TOÀN SỐ (không phải
                // chữ cái) để tuyệt đối an toàn với bước tách chữ trong công thức bên dưới - nếu
                // dùng placeholder có chữ cái (kể cả không dấu), nó vẫn có thể bị hiểu nhầm thành
                // ký hiệu cần tách khi lọt vào trong vùng $...$ (y hệt lỗi đã gặp với chữ "bằng").
                // Bỏ dấu in đậm/nghiêng của markdown (**chữ**) để không bị đọc thành "sao sao"
                t = t.split("**").join("");
                t = t.split("__").join("");
                t = t.split("°C").join(" 900001 ");
                t = t.split("°").join(" 900002 ");
                // Đơn vị ghép hay gặp. Thứ tự quan trọng: cụm dài (km/h) trước cụm ngắn (km).
                t = t.split("km/h").join(" 900003 ");
                t = t.split("m/s").join(" 900004 ");
                t = t.split("kg").join(" 900005 ");
                t = t.split("km").join(" 900006 ");
                t = t.split("cm").join(" 900007 ");
                t = t.split("mm").join(" 900008 ");

                // Chữ "J" đứng một mình luôn là đơn vị Jun (không phải biến số)
                t = t.replace(/(^|[^a-zA-ZÀ-ỹĐđ])J($|[^a-zA-ZÀ-ỹĐđ])/g, "$1 900009 $2");

                // QUAN TRỌNG: xử lý TRỌN VẸN từng vùng công thức $...$ / $$...$$ trong CÙNG 1 bước
                // (LaTeX -> ký hiệu -> tách chữ), để không bị lẫn với phần văn xuôi bên ngoài.
                // Nếu làm từng bước riêng rẽ trên toàn chuỗi, chữ "bằng" (được sinh ra từ dấu "=")
                // sẽ lọt vào trong công thức và bị hiểu nhầm ngược lại thành ký hiệu cần tách.
                //
                // 2 LỚP BẢO VỆ quan trọng (phòng khi Gemini lỡ viết thiếu 1 dấu $ ở đâu đó, khiến
                // 2 dấu $ không liên quan bị ghép nhầm thành "1 công thức" trải dài cả đoạn văn):
                //  1. Giới hạn độ dài mỗi "công thức" tối đa 60 ký tự (công thức thật luôn ngắn).
                //  2. Chỉ xử lý nếu nội dung thực sự GIỐNG công thức (có =, số, hoặc dấu ^ / \\).
                //     Nếu không, giữ nguyên - an toàn hơn là xử lý nhầm.
                t = t.replace(/\\${{1,2}}([^$]{{1,50}})\\${{1,2}}/g, function (whole, inner) {{
                    // Chỉ tin là công thức thật khi có dấu "=" hoặc lệnh LaTeX (backslash) - đáng
                    // tin cậy hơn nhiều so với "có chữ số" (vì "$5" tiền tệ cũng có chữ số).
                    var looksLikeFormula = inner.indexOf("=") !== -1 || inner.indexOf("\\\\") !== -1;
                    if (!looksLikeFormula) {{
                        return whole;
                    }}
                    var processed = splitAdjacentLetters(inner);
                    processed = convertLatexCommands(processed);
                    processed = convertBasicSymbols(processed);
                    return " " + processed + " ";
                }});
                t = t.split("$").join(" ");  // phòng khi còn sót dấu $ không theo cặp

                // Phần còn lại NGOÀI công thức: vẫn áp dụng ký hiệu/LaTeX phòng khi model lỡ
                // không bọc trong dấu $ (không ảnh hưởng phần đã xử lý ở trên vì đã thành chữ
                // tiếng Việt có dấu, không còn chứa các ký hiệu thô này nữa).
                t = convertLatexCommands(t);
                t = convertBasicSymbols(t);

                // Đơn vị viết tắt đi ngay sau số (5m, 10 s, 3h, 20g, 2l) -> đọc tên đơn vị.
                // Dùng ($|[^a-zA-ZÀ-ỹĐđ]) thay cho \\b - vì \\b không nhận diện chữ có dấu tiếng
                // Việt, nên "20 mỗi" sẽ bị hiểu nhầm "m" là đơn vị mét nếu dùng \\b.
                var unitAfterNumber = {{ m: "mét", s: "giây", g: "gam", h: "giờ", l: "lít" }};
                t = t.replace(/(\\d)\\s?([msghl])($|[^a-zA-ZÀ-ỹĐđ])/g, function (whole, num, letter, after) {{
                    return num + " " + unitAfterNumber[letter] + after;
                }});

                // Dấu "/" còn sót lại (đơn vị ghép dạng tỉ lệ như Jun/ki-lô-gam) -> đọc "trên"
                t = t.split("/").join(" trên ");

                // Chữ cái La-tinh ĐỨNG MỘT MÌNH trong phần văn xuôi còn lại (biến số vật lý
                // nhắc rời: t, Q, F...). QUAN TRỌNG: không dùng \\b vì \\b trong JS không nhận
                // diện chữ có dấu (ví dụ chữ "bằng" sẽ bị hiểu nhầm chữ "b" đứng một mình).
                // Thay vào đó, tự kiểm tra 2 ký tự liền kề: chỉ coi là "đứng một mình" khi CẢ 2
                // bên đều không phải chữ cái (kể cả chữ có dấu tiếng Việt).
                var isLetter = function (ch) {{
                    return !!ch && /[a-zA-ZÀ-ỹĐđ]/.test(ch);
                }};
                t = t.replace(/[a-zA-Z]/g, function (letter, offset, whole) {{
                    var before = whole.charAt(offset - 1);
                    var after = whole.charAt(offset + 1);
                    if (isLetter(before) || isLetter(after)) {{
                        return letter;  // nằm trong 1 từ dài hơn -> giữ nguyên, không phải ký hiệu đơn lẻ
                    }}
                    var name = letterNames[letter.toLowerCase()];
                    return name ? name : letter;
                }});

                t = t.split("900001").join("độ C");
                t = t.split("900002").join("độ");
                t = t.split("900003").join("ki-lô-mét trên giờ");
                t = t.split("900004").join("mét trên giây");
                t = t.split("900005").join("ki-lô-gam");
                t = t.split("900006").join("ki-lô-mét");
                t = t.split("900007").join("xen-ti-mét");
                t = t.split("900008").join("mi-li-mét");
                t = t.split("900009").join("Jun");
            }} catch (err) {{
                return input;  // nếu phiên âm lỗi vì lý do gì đó, vẫn đọc được văn bản gốc
            }}
            return t;
        }}

        function getVietnameseVoice() {{
            const voices = window.speechSynthesis.getVoices();
            return voices.find(function (v) {{
                return v.lang && v.lang.toLowerCase().indexOf("vi") === 0;
            }}) || null;
        }}

        function setPauseEnabled(enabled) {{
            pauseBtn.disabled = !enabled;
            pauseBtn.style.opacity = enabled ? "1" : "0.5";
        }}

        playBtn.addEventListener("click", function () {{
            if (!("speechSynthesis" in window)) {{
                status.textContent = "Trình duyệt không hỗ trợ đọc giọng nói";
                return;
            }}
            window.speechSynthesis.cancel();

            const spokenText = vietnamizeForSpeech(rawText);
            currentUtter = new SpeechSynthesisUtterance(spokenText);
            currentUtter.lang = "vi-VN";
            currentUtter.rate = 0.95;

            const viVoice = getVietnameseVoice();
            if (viVoice) currentUtter.voice = viVoice;

            currentUtter.onstart = function () {{
                status.textContent = "Đang đọc...";
                setPauseEnabled(true);
                pauseBtn.textContent = "⏸️ Tạm dừng";
            }};
            currentUtter.onend = function () {{
                status.textContent = "";
                setPauseEnabled(false);
                pauseBtn.textContent = "⏸️ Tạm dừng";
            }};
            currentUtter.onerror = function () {{
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
