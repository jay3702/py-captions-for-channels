"""
HLS subtitle proxy — injects Whisper-generated SRT captions into a
Channels DVR HLS stream.

Endpoints registered as a FastAPI APIRouter (included in web_app.py):

  GET /player/{fileId}
      Minimal hls.js player page.  Loads the proxied master manifest so the
      subtitle track declared inside is picked up automatically.

  GET /proxy/hls/{fileId}/master.m3u8
      Fetches the Channels DVR master manifest, injects an EXT-X-MEDIA
      subtitle group, and rewrites variant playlist URLs so they also go
      through this proxy (ensuring all segment fetches are pass-through).

  GET /proxy/hls/{fileId}/subs.m3u8
      Returns a minimal single-segment WebVTT subtitle playlist covering the
      full recording duration.  Duration is fetched from the DVR metadata API.

  GET /proxy/hls/{fileId}/subs.vtt
      Reads the .srt sidecar file for this recording (via translate_dvr_path),
      converts it to WebVTT, and returns it.

  GET /proxy/hls/{fileId}/{rest_of_path:path}
      Pass-through proxy for all other HLS requests (variant playlists, TS
      segments) forwarded to the Channels DVR server.
"""

import logging
import re
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse

from .config import (
    CHANNELS_DVR_URL,
    DVR_PATH_PREFIX,
    DVR_RECORDINGS_PATH,
    LOCAL_PATH_PREFIX,
    translate_dvr_path,
)

LOG = logging.getLogger(__name__)

router = APIRouter()

_DVR_BASE = CHANNELS_DVR_URL.rstrip("/")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _srt_to_vtt(srt: str) -> str:
    """Convert SRT subtitle text to WebVTT.

    Only the timestamp separator (comma → dot) needs changing; everything else
    (cue numbers, cue text, blank lines) is compatible with WebVTT as-is.
    """
    vtt = re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", srt.strip())
    return "WEBVTT\n\n" + vtt


def _local_srt_for_file_id(file_id: str) -> Path | None:
    """Resolve the local .srt path for a DVR file ID.

    Calls the DVR metadata API to get the recording's API path, then runs it
    through translate_dvr_path() to get the local filesystem path, and swaps
    the extension to .srt.

    Returns None if the metadata call fails or the .srt file doesn't exist.
    """
    try:
        resp = httpx.get(f"{_DVR_BASE}/dvr/files/{file_id}", timeout=10)
        resp.raise_for_status()
        meta = resp.json()
    except Exception as exc:
        LOG.warning("hls_proxy: DVR metadata fetch failed for %s: %s", file_id, exc)
        return None

    # The DVR returns the path under the 'path' key.
    api_path = meta.get("path") or meta.get("Path") or ""
    if not api_path:
        LOG.warning("hls_proxy: no 'path' field in DVR metadata for %s", file_id)
        return None

    local_path = _dvr_api_path_to_container_path(api_path)
    if local_path is None:
        LOG.warning(
            "hls_proxy: cannot resolve container path for %s (no prefix configured)",
            file_id,
        )
        return None
    srt_path = local_path.with_suffix(".srt")
    if not srt_path.exists():
        LOG.debug("hls_proxy: no .srt file at %s", srt_path)
        return None

    return srt_path


def _dvr_api_path_to_container_path(api_path: str) -> Path | None:
    """Translate a Channels DVR API file path to a path accessible inside the container.

    Handles all deployment topologies:

    * **Single-host** (DVR + captions on same machine): DVR typically returns
      a path relative to its media root, e.g. ``TV/Show/file.mpg``.  That
      relative path is anchored under the container media mount.

    * **Separate DVR server (Linux)**: DVR returns an absolute path including
      its own storage root prefix, e.g. ``/tank/AllMedia/Channels/TV/...``.
      ``translate_dvr_path()`` swaps ``DVR_PATH_PREFIX`` for
      ``LOCAL_PATH_PREFIX`` (= ``DVR_MEDIA_MOUNT``) to produce the
      container-side absolute path.

    * **Three-server (NAS + separate GPU host)**: same as above; the captions
      container mounts the NAS share at ``DVR_MEDIA_MOUNT`` and declares
      that as ``LOCAL_PATH_PREFIX``.

    Anchor precedence for relative paths:
      1. ``LOCAL_PATH_PREFIX`` (= ``DVR_MEDIA_MOUNT``, the container mount
         point for DVR media — managed by the Settings UI)
      2. ``DVR_RECORDINGS_PATH`` (legacy fallback)

    Returns ``None`` only when the path is still relative after translation
    and no anchor prefix is configured at all.
    """
    # translate_dvr_path() handles the DVR_PATH_PREFIX → LOCAL_PATH_PREFIX
    # swap for absolute DVR paths.  Normalise backslashes (Windows DVR).
    translated = translate_dvr_path(api_path).replace("\\", "/")
    local_path = Path(translated)

    if local_path.is_absolute():
        # translate_dvr_path produced a container-accessible absolute path.
        return local_path

    # Path is still relative — the DVR returned a bare relative path (common
    # with Windows/Mac DVR servers that omit the media-root prefix).
    # Anchor it under the container-side mount point for the DVR media root.
    #   LOCAL_PATH_PREFIX = DVR_MEDIA_MOUNT (managed by Settings UI)
    #   DVR_RECORDINGS_PATH = older fallback variable
    anchor = LOCAL_PATH_PREFIX or DVR_RECORDINGS_PATH
    if not anchor:
        return None
    return Path(anchor) / local_path


@router.get("/proxy/hls/{file_id}/debug")
async def proxy_debug(file_id: str):
    """Diagnostic endpoint — shows path resolution for a recording."""
    result: dict = {"file_id": file_id, "dvr_base": _DVR_BASE}
    try:
        resp = httpx.get(f"{_DVR_BASE}/dvr/files/{file_id}", timeout=10)
        resp.raise_for_status()
        meta = resp.json()
        result["dvr_meta_keys"] = list(meta.keys())
        api_path = meta.get("path") or meta.get("Path") or ""
        result["api_path"] = api_path
        # Show all prefix config so any setup can be diagnosed
        result["config"] = {
            "DVR_PATH_PREFIX": str(DVR_PATH_PREFIX),
            "LOCAL_PATH_PREFIX": str(LOCAL_PATH_PREFIX),
            "DVR_RECORDINGS_PATH": str(DVR_RECORDINGS_PATH),
        }
        if api_path:
            translated = translate_dvr_path(api_path)
            result["translated_path"] = translated
            local_path = _dvr_api_path_to_container_path(api_path)
            result["anchored_path"] = str(local_path) if local_path else None
            if local_path:
                srt_path = local_path.with_suffix(".srt")
                result["srt_path"] = str(srt_path)
                result["srt_exists"] = srt_path.exists()
                result["mpg_exists"] = local_path.exists()
                parent = srt_path.parent
                result["parent_dir"] = str(parent)
                result["parent_exists"] = parent.exists()
                if parent.exists():
                    result["parent_contents"] = sorted(p.name for p in parent.iterdir())
    except Exception as exc:
        result["error"] = str(exc)
    return result


async def _dvr_duration(file_id: str) -> float:
    """Return the recording duration in seconds from DVR metadata (default 7200)."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{_DVR_BASE}/dvr/files/{file_id}")
            resp.raise_for_status()
            meta = resp.json()
            raw = meta.get("duration") or meta.get("Duration") or 0
            return float(raw)
    except Exception:
        return 7200.0


# ---------------------------------------------------------------------------
# Player page
# ---------------------------------------------------------------------------

_PLAYER_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: #000; color: #fff; font-family: sans-serif;
            display: flex; flex-direction: column; height: 100dvh; }}
    #header {{ padding: 8px 16px; background: #111; display: flex;
               align-items: center; gap: 16px; flex-shrink: 0; }}
    #header a {{ color: #aaa; text-decoration: none; font-size: .9rem; }}
    #header a:hover {{ color: #fff; }}
    #title {{ font-size: 1rem; flex: 1; white-space: nowrap;
              overflow: hidden; text-overflow: ellipsis; }}
    #cc-btn {{ padding: 4px 10px; border: 1px solid #555; border-radius: 4px;
               background: #222; color: #aaa; cursor: pointer;
               font-size: .85rem; white-space: nowrap; flex-shrink: 0; }}
    #cc-btn.on {{ background: #1a6b1a; border-color: #2a9b2a; color: #fff; }}
    #cc-btn.unavailable {{ opacity: .35; cursor: default; }}
    #video {{ flex: 1; width: 100%; background: #000; position: relative; }}
    video {{ width: 100%; height: 100%; display: block; }}
    ::cue {{ background: rgba(0,0,0,.8); color: #fff;
             font-size: 1.15em; font-family: sans-serif; }}
  </style>
</head>
<body>
  <div id="header">
    <a href="/">&larr; Dashboard</a>
    <span id="title">{title}</span>
    <button id="cc-btn" class="unavailable" title="Toggle subtitles">
      CC
    </button>
  </div>
  <div id="video">
    <video id="v" controls></video>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/hls.js@1.6.15/dist/hls.min.js"></script>
  <script>
    const src = {src_json};
    const video = document.getElementById('v');
    const ccBtn = document.getElementById('cc-btn');
    let hlsInstance = null;
    let subsOn = true;

    function setCCState(on) {{
      subsOn = on;
      if (hlsInstance) {{
        hlsInstance.subtitleTrack = on ? 0 : -1;
      }}
      ccBtn.textContent = on ? 'CC \u25cf' : 'CC';
      ccBtn.className = on ? 'on' : '';
    }}

    ccBtn.addEventListener('click', function () {{
      if (ccBtn.classList.contains('unavailable')) return;
      setCCState(!subsOn);
    }});

    if (Hls.isSupported()) {{
      const hls = new Hls({{
        enableCEA708Captions: false,
      }});
      hlsInstance = hls;
      hls.loadSource(src);
      hls.attachMedia(video);
      hls.on(Hls.Events.MANIFEST_PARSED, function (_evt, _data) {{
        video.play().catch(() => {{}});
      }});
      // SUBTITLE_TRACKS_UPDATED fires when hls.js has resolved the subtitle
      // group from EXT-X-MEDIA — may be after MANIFEST_PARSED in hls.js 1.x.
      hls.on(Hls.Events.SUBTITLE_TRACKS_UPDATED, function (_evt, data) {{
        if (data && data.subtitleTracks && data.subtitleTracks.length > 0) {{
          hls.subtitleTrack = 0;
          ccBtn.className = 'on';
          ccBtn.textContent = 'CC \u25cf';
          ccBtn.title = 'Toggle subtitles';
        }}
      }});
    }} else if (video.canPlayType('application/vnd.apple.mpegurl')) {{
      video.src = src;
      video.play().catch(() => {{}});
    }} else {{
      document.getElementById('video').textContent =
        'HLS playback is not supported in this browser.';
    }}
  </script>
</body>
</html>
"""


@router.get("/player/{file_id}", response_class=HTMLResponse)
async def player_page(file_id: str):
    """Serve a standalone hls.js player for a DVR recording with subtitles."""
    # Fetch the recording title for the page heading.
    title = file_id
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{_DVR_BASE}/dvr/files/{file_id}")
            if resp.is_success:
                meta = resp.json()
                t = meta.get("title") or meta.get("Title") or ""
                ep = meta.get("episode_title") or meta.get("EpisodeTitle") or ""
                title = f"{t} — {ep}" if ep else t or file_id
    except Exception:
        pass

    import json

    src = f"/proxy/hls/{file_id}/master.m3u8"
    html = _PLAYER_HTML.format(
        title=title,
        src_json=json.dumps(src),
    )
    return HTMLResponse(html)


# ---------------------------------------------------------------------------
# Master manifest — injects subtitle group
# ---------------------------------------------------------------------------


@router.get("/proxy/hls/{file_id}/master.m3u8")
async def proxy_master(file_id: str):
    """Fetch DVR master manifest and inject an EXT-X-MEDIA subtitle group."""
    dvr_url = f"{_DVR_BASE}/dvr/files/{file_id}/hls/master.m3u8"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(dvr_url)
            r.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=f"DVR manifest error: {exc}"
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Could not reach DVR: {exc}"
        ) from exc

    original = r.text

    # Check whether an .srt exists for this file; if not, pass through unchanged.
    has_srt = _local_srt_for_file_id(file_id) is not None

    if has_srt:
        sub_playlist_url = f"/proxy/hls/{file_id}/subs.m3u8"

        # Build the EXT-X-MEDIA line for the subtitle group.
        media_tag = (
            f'#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",'
            f'NAME="English",DEFAULT=YES,AUTOSELECT=YES,'
            f'FORCED=NO,LANGUAGE="en",URI="{sub_playlist_url}"'
        )

        lines = original.splitlines(keepends=True)
        out_lines = []
        inserted_media = False

        for line in lines:
            stripped = line.rstrip()

            # Insert the EXT-X-MEDIA tag before the first EXT-X-STREAM-INF
            if not inserted_media and stripped.startswith("#EXT-X-STREAM-INF"):
                out_lines.append(media_tag + "\n")
                inserted_media = True

            # Rewrite variant playlist URLs so they pass through this proxy.
            # Variant playlist lines directly follow EXT-X-STREAM-INF.
            if (
                not stripped.startswith("#")
                and stripped  # non-empty, non-comment → it's a URL or path
                and not stripped.startswith("http")
            ):
                # Relative variant URL → make it a proxy pass-through URL
                out_lines.append(f"/proxy/hls/{file_id}/{stripped}\n")
                continue

            # Rewrite absolute variant URLs pointing at the DVR server.
            if stripped.startswith(_DVR_BASE + "/dvr/files/"):
                # Keep the path portion after /dvr/files/{id}/
                suffix = stripped[len(f"{_DVR_BASE}/dvr/files/{file_id}/") :]
                out_lines.append(f"/proxy/hls/{file_id}/{suffix}\n")
                continue

            # Add SUBTITLES attribute to EXT-X-STREAM-INF lines (required for
            # hls.js to associate the media group with each variant).
            if stripped.startswith("#EXT-X-STREAM-INF"):
                if "SUBTITLES=" not in stripped:
                    out_lines.append(stripped.rstrip() + ',SUBTITLES="subs"\n')
                    continue

            out_lines.append(line)

        manifest_text = "".join(out_lines)
    else:
        # No SRT — still rewrite variant URLs so segments proxy correctly,
        # but don't add a subtitle group.
        lines = original.splitlines(keepends=True)
        out_lines = []
        for line in lines:
            stripped = line.rstrip()
            if (
                not stripped.startswith("#")
                and stripped
                and not stripped.startswith("http")
            ):
                out_lines.append(f"/proxy/hls/{file_id}/{stripped}\n")
                continue
            if stripped.startswith(_DVR_BASE + "/dvr/files/"):
                suffix = stripped[len(f"{_DVR_BASE}/dvr/files/{file_id}/") :]
                out_lines.append(f"/proxy/hls/{file_id}/{suffix}\n")
                continue
            out_lines.append(line)
        manifest_text = "".join(out_lines)

    return PlainTextResponse(
        manifest_text,
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "no-store"},
    )


# ---------------------------------------------------------------------------
# Subtitle playlist
# ---------------------------------------------------------------------------


@router.get("/proxy/hls/{file_id}/subs.m3u8")
async def proxy_subs_playlist(file_id: str):
    """Return a simple VOD WebVTT subtitle playlist for this recording."""
    duration = await _dvr_duration(file_id)
    vtt_url = f"/proxy/hls/{file_id}/subs.vtt"

    playlist = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:3\n"
        "#EXT-X-TARGETDURATION:{dur_int}\n"
        "#EXT-X-PLAYLIST-TYPE:VOD\n"
        "#EXTINF:{dur_float:.3f},\n"
        "{vtt_url}\n"
        "#EXT-X-ENDLIST\n"
    ).format(
        dur_int=int(duration) + 1,
        dur_float=duration,
        vtt_url=vtt_url,
    )

    return PlainTextResponse(
        playlist,
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "no-store"},
    )


# ---------------------------------------------------------------------------
# WebVTT subtitle file
# ---------------------------------------------------------------------------


@router.get("/proxy/hls/{file_id}/subs.vtt")
async def proxy_subs_vtt(file_id: str):
    """Convert and return the .srt sidecar as WebVTT."""
    srt_path = _local_srt_for_file_id(file_id)
    if srt_path is None:
        raise HTTPException(
            status_code=404,
            detail=f"No .srt subtitle file found for recording {file_id}",
        )

    try:
        srt_text = srt_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        LOG.error("hls_proxy: could not read %s: %s", srt_path, exc)
        raise HTTPException(
            status_code=500, detail="Failed to read subtitle file"
        ) from exc

    vtt_text = _srt_to_vtt(srt_text)
    return PlainTextResponse(
        vtt_text,
        media_type="text/vtt",
        headers={"Cache-Control": "no-store"},
    )


# ---------------------------------------------------------------------------
# Pass-through proxy for variant playlists + TS segments
# ---------------------------------------------------------------------------


@router.get("/proxy/hls/{file_id}/{rest:path}")
async def proxy_pass_through(file_id: str, rest: str, request: Request):
    """Forward any other HLS request (variant playlists, TS segments) to the DVR."""
    dvr_url = f"{_DVR_BASE}/dvr/files/{file_id}/{rest}"

    # Forward any query parameters from the original request.
    if request.query_params:
        dvr_url += "?" + str(request.query_params)

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            dvr_resp = await client.get(dvr_url)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"DVR proxy error: {exc}") from exc

    content_type = dvr_resp.headers.get("content-type", "application/octet-stream")

    # For TS segments stream the bytes through without buffering.
    return StreamingResponse(
        dvr_resp.aiter_bytes(chunk_size=65536),
        status_code=dvr_resp.status_code,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )
