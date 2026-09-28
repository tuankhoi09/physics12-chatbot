"""
Tìm video YouTube ngắn (mặc định dưới 3 phút) minh hoạ 1 hiện tượng Vật lý,
dùng YouTube Data API v3 chính thức của Google (cần API key riêng, miễn phí,
xem hướng dẫn tạo key trong README.md).
"""

import re
import requests

_DURATION_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def _parse_iso8601_duration(duration: str) -> int:
    """Đổi chuỗi kiểu 'PT2M45S' (định dạng YouTube trả về) sang tổng số giây."""
    match = _DURATION_RE.match(duration or "")
    if not match:
        return 0
    hours, minutes, seconds = (int(x) if x else 0 for x in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def format_duration(total_seconds: int) -> str:
    m, s = divmod(total_seconds, 60)
    return f"{m}:{s:02d}"


def search_short_videos(api_key: str, query: str, max_results: int = 3,
                         max_duration_seconds: int = 180) -> list:
    """
    Tìm video YouTube liên quan đến `query`, chỉ giữ lại video có thời lượng
    THỰC SỰ <= max_duration_seconds (mặc định 180s = 3 phút).
    Trả về list các dict: {title, channel, url, duration_seconds, thumbnail}.
    """
    search_resp = requests.get(
        "https://www.googleapis.com/youtube/v3/search",
        params={
            "part": "snippet",
            "q": query,
            "type": "video",
            "videoDuration": "short",  # YouTube chỉ lọc thô ở mức <4 phút, sẽ lọc chính xác lại bên dưới
            "maxResults": 10,
            "relevanceLanguage": "vi",
            "safeSearch": "strict",
            "key": api_key,
        },
        timeout=10,
    )
    search_resp.raise_for_status()
    items = search_resp.json().get("items", [])
    video_ids = [it["id"]["videoId"] for it in items if it.get("id", {}).get("videoId")]
    if not video_ids:
        return []

    details_resp = requests.get(
        "https://www.googleapis.com/youtube/v3/videos",
        params={
            "part": "contentDetails,snippet",
            "id": ",".join(video_ids),
            "key": api_key,
        },
        timeout=10,
    )
    details_resp.raise_for_status()

    results = []
    for item in details_resp.json().get("items", []):
        duration = _parse_iso8601_duration(item["contentDetails"]["duration"])
        if 0 < duration <= max_duration_seconds:
            results.append({
                "title": item["snippet"]["title"],
                "channel": item["snippet"]["channelTitle"],
                "url": f"https://www.youtube.com/watch?v={item['id']}",
                "duration_seconds": duration,
                "thumbnail": f"https://img.youtube.com/vi/{item['id']}/mqdefault.jpg",
            })
        if len(results) >= max_results:
            break
    return results
