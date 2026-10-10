import logging
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

import requests
import yt_dlp

logger = logging.getLogger(__name__)

YOUTUBEI_PLAYER_URL = "https://www.youtube.com/youtubei/v1/player"
YOUTUBE_API_KEY = "AIzaSyAO90d0o_cHoDL30RlTbaJaILi1ShqJzw"

# Ordered by the client path Echo Music discovered to be best for full-file streaming.
CLIENT_CASCADE = [
    "VISIONOS",
    "ANDROID_VR",
    "TVHTML5",
    "WEB_REMIX",
]

CLIENTS: Dict[str, Dict[str, str]] = {
    "VISIONOS": {
        "clientName": "VISIONOS",
        "clientVersion": "1.0.0",
        "userAgent": "Mozilla/5.0",
    },
    "ANDROID_VR": {
        "clientName": "ANDROID_VR",
        "clientVersion": "1.65.10",
        "userAgent": "com.google.android.apps.youtube.vr.oculus/1.65.10",
    },
    "TVHTML5": {
        "clientName": "TVHTML5",
        "clientVersion": "2.20250101.00.00",
        "userAgent": "Mozilla/5.0 (TVhtml5; Linux; Nexus Player Build/NRD90M)",
    },
    "WEB_REMIX": {
        "clientName": "WEB_REMIX",
        "clientVersion": "2.20250107.10.00",
        "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    },
}


@dataclass
class StreamInfo:
    video_id: str
    url: str
    mime_type: str
    bitrate: int
    client: str
    expires_in_seconds: int


def _request_player_context(video_id: str, client_name: str) -> Optional[Dict[str, Any]]:
    client = CLIENTS.get(client_name)
    if client is None:
        return None

    payload = {
        "context": {
            "client": {
                "clientName": client["clientName"],
                "clientVersion": client["clientVersion"],
                "hl": "en",
                "gl": "US",
                "userAgent": client["userAgent"],
            }
        },
        "videoId": video_id,
    }

    headers = {
        "Content-Type": "application/json",
        "User-Agent": client["userAgent"],
    }

    try:
        response = requests.post(
            f"{YOUTUBEI_PLAYER_URL}?key={YOUTUBE_API_KEY}",
            json=payload,
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        status = data.get("playabilityStatus", {}).get("status")
        if status != "OK":
            logger.debug("playability status for %s via %s: %s", video_id, client_name, status)
            return None
        return data
    except Exception as exc:
        logger.debug("InnerTube request failed for %s using %s: %s", video_id, client_name, exc)
        return None


def _pick_best_audio_format(formats: List[Dict[str, Any]], max_kbps: int = 160) -> Optional[Dict[str, Any]]:
    candidates = []
    for fmt in formats:
        mime = fmt.get("mimeType", "")
        if not mime.startswith("audio/"):
            continue
        bitrate = int(fmt.get("bitrate") or 0)
        candidates.append((bitrate, fmt))

    if not candidates:
        return None

    # Prefer streams below or near the target bitrate, but keep the best available if nothing matches.
    filtered = [fmt for bitrate, fmt in candidates if bitrate <= max_kbps * 1000]
    if filtered:
        return max(filtered, key=lambda fmt: int(fmt.get("bitrate") or 0))

    return max(candidates, key=lambda item: item[0])[1]


def _extract_url_from_format(fmt: Dict[str, Any]) -> Optional[str]:
    if fmt.get("url"):
        return fmt["url"]

    # Fallback for signatureCipher if needed.
    sig_cipher = fmt.get("signatureCipher") or fmt.get("cipher")
    if sig_cipher:
        # This is intentionally a placeholder; the full Echo Music method includes deobfuscation.
        # In a real project, you'd decode it with player JS + config logic.
        logger.warning("signatureCipher encountered for %s; this path needs deobfuscation support", fmt)
        return None

    return None


def _validate_head(url: str) -> bool:
    try:
        response = requests.head(url, headers={"Range": "bytes=0-524287"}, timeout=5, allow_redirects=True)
        if response.status_code in (200, 206, 405):
            return True
        return False
    except Exception:
        return True


def _fast_inner_tube(video_id: str, max_kbps: int = 160) -> Optional[StreamInfo]:
    for client_name in CLIENT_CASCADE:
        data = _request_player_context(video_id, client_name)
        if data is None:
            continue

        adaptive = data.get("streamingData", {}).get("adaptiveFormats", [])
        fmt = _pick_best_audio_format(adaptive, max_kbps=max_kbps)
        if fmt is None:
            continue

        stream_url = _extract_url_from_format(fmt)
        if not stream_url:
            continue

        if not _validate_head(stream_url):
            logger.debug("Rejected by validation for %s using %s", video_id, client_name)
            continue

        return StreamInfo(
            video_id=video_id,
            url=stream_url,
            mime_type=fmt.get("mimeType", "audio/mp4"),
            bitrate=int(fmt.get("bitrate") or 0),
            client=client_name,
            expires_in_seconds=int(data.get("streamingData", {}).get("expiresInSeconds") or 21600),
        )

    return None


def _fallback_yt_dlp(video_id: str) -> Optional[str]:
    try:
        with yt_dlp.YoutubeDL(
            {
                "quiet": True,
                "no_warnings": True,
                "format": "bestaudio[ext=m4a]/bestaudio/best",
                "noplaylist": True,
            }
        ) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            if not isinstance(info, dict):
                return None
            return info.get("url")
    except Exception as exc:
        logger.warning("yt-dlp fallback failed for %s: %s", video_id, exc)
        return None


def extract_stream_info(video_id: str, max_kbps: int = 160) -> Optional[StreamInfo]:
    """
    Fast path: direct InnerTube API using client cascade.
    Fallback: yt-dlp if direct extraction fails.
    """
    start = time.time()
    info = _fast_inner_tube(video_id, max_kbps=max_kbps)
    if info:
        elapsed_ms = (time.time() - start) * 1000
        logger.info("InnerTube stream extraction succeeded for %s in %.0f ms", video_id, elapsed_ms)
        return info

    logger.warning("InnerTube path failed for %s, falling back to yt-dlp", video_id)
    fallback_url = _fallback_yt_dlp(video_id)
    if fallback_url:
        return StreamInfo(
            video_id=video_id,
            url=fallback_url,
            mime_type="audio/mp4",
            bitrate=0,
            client="YTDLP_FALLBACK",
            expires_in_seconds=21600,
        )

    return None


def extract_audio_url(video_id: str, max_kbps: int = 160) -> Optional[str]:
    """Public API: return only the stream URL."""
    stream = extract_stream_info(video_id, max_kbps=max_kbps)
    return stream.url if stream else None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    url = extract_audio_url("dQw4w9WgXcQ")
    print(url)
