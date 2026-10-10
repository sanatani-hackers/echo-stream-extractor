# echo-stream-extractor

Fast YouTube audio stream URL extraction in Python.

This project focuses only on the stream URL part of the Echo Music approach:
- direct InnerTube API calls
- client cascade (fast path)
- fallback to yt-dlp if needed
- minimal API for `extract_audio_url(video_id)`

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Quick usage

```python
from echo_stream_extractor import extract_audio_url

url = extract_audio_url("dQw4w9WgXcQ")
print(url)
```

## What this does

This is intentionally scoped to stream URL extraction only:
- not a full app
- not a music client
- not WebSocket sync logic
- only the part that gets a direct YouTube audio stream URL

## Why this exists

The slow part in yt-dlp is often the full metadata/player extraction cycle.
This package tries a faster path by:

1. Calling YouTube InnerTube directly
2. Trying a client cascade
3. Taking the best audio format
4. Falling back to yt-dlp if needed

## License

MIT
