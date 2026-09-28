"""
Vẽ mindmap (sơ đồ tư duy) tương tác từ 1 đoạn markdown outline (dạng #, ##, -...),
dùng thư viện mã nguồn mở "markmap" (tải qua CDN, không cần cài thêm gì ở máy).
Mindmap có thể zoom, kéo, thu/phóng từng nhánh ngay trong trình duyệt.
"""

import streamlit.components.v1 as components


def render_mindmap(markdown_outline: str, height: int = 600) -> None:
    """Vẽ mindmap tương tác từ markdown_outline (dạng # tiêu đề, ## nhánh, - ý con)."""
    # Tránh chuỗi "</script>" xuất hiện trong nội dung làm hỏng thẻ <script> chứa nó
    safe_md = markdown_outline.replace("</script>", "<\u200b/script>")

    html = f"""
    <style>
      html, body {{
        margin: 0;
        padding: 0;
        width: 100%;
        height: 100%;
      }}
      .markmap-wrap {{
        width: 100%;
        height: {height - 12}px;
      }}
      .markmap-wrap svg.markmap {{
        width: 100% !important;
        height: 100% !important;
        display: block;
      }}
    </style>
    <div class="markmap-wrap">
      <div class="markmap" style="width:100%; height:100%;">
        <script type="text/template">
{safe_md}
        </script>
      </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/markmap-autoloader@0.18"></script>
    <script>
      // markmap-autoloader tính kích thước ngay lúc trang vừa nạp, đôi khi
      // trước khi CSS kịp áp dụng xong -> ép nó tính lại sau khi mọi thứ ổn định.
      setTimeout(function () {{
        window.dispatchEvent(new Event("resize"));
      }}, 400);
      setTimeout(function () {{
        window.dispatchEvent(new Event("resize"));
      }}, 1200);
    </script>
    """
    components.html(html, height=height, scrolling=True)
