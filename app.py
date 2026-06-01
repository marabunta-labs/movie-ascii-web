import streamlit as st
import streamlit.components.v1 as components
import tempfile
import os
import subprocess
import base64
from pathlib import Path

import cv2
import numpy as np

from movie_ascii.main import (
    resize_image,
    pixels_to_html,
    CHARSETS,
    get_youtube_id,
)

try:
    from movie_ascii.main import _FFMPEG_EXE
except ImportError:
    _FFMPEG_EXE = "ffmpeg"

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="movie-ascii — Live Demo",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .stApp { background-color: #0a0a0a; }
    .ascii-output {
        background-color: #000;
        padding: 16px;
        border-radius: 10px;
        border: 1px solid #2a2a2a;
        overflow: auto;
        max-height: 600px;
        font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
        font-size: 7px;
        line-height: 8px;
        letter-spacing: 0px;
        white-space: nowrap;
    }
    .option-card {
        background: #161616;
        border: 1px solid #2a2a2a;
        border-radius: 8px;
        padding: 12px;
        margin-bottom: 8px;
    }
    .option-card h4 { margin: 0 0 4px 0; color: #4ade80; font-size: 13px; }
    .option-card p { margin: 0; color: #888; font-size: 11px; line-height: 1.4; }
    section[data-testid="stSidebar"] { background-color: #0f0f0f; }
    video { width: 100% !important; }
    iframe { border: none !important; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("# 🎬 movie-ascii")
    st.caption("*Turn any video into ASCII art*")
    st.divider()

    input_mode = st.radio("**📁 Input**", ["📷 Image", "🎥 Video", "📺 YouTube"], horizontal=True)
    st.divider()

    st.markdown("### 🎨 Mode")
    mode = st.selectbox("Mode", ["truecolor", "ascii-color", "bw"], index=0, label_visibility="collapsed")
    if mode == "truecolor":
        st.markdown('<div class="option-card"><h4>🌈 Truecolor</h4><p>Full RGB per character.</p></div>', unsafe_allow_html=True)
    elif mode == "ascii-color":
        st.markdown('<div class="option-card"><h4>🎨 8 ANSI Colors</h4><p>Classic retro terminal.</p></div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="option-card"><h4>⚪ B&W</h4><p>Luminance only. Fastest.</p></div>', unsafe_allow_html=True)

    st.divider()
    st.markdown("### 🔤 Charset")
    charset_options = list(CHARSETS.keys()) + ["✏️ Custom"]
    charset_choice = st.selectbox("Charset", charset_options, index=0, label_visibility="collapsed")
    if charset_choice == "✏️ Custom":
        custom_charset = st.text_input("Chars (dark→light, min 2)", value=" .:░▒▓█")
        if len(custom_charset) >= 2:
            charset_name = "_web_custom"
            CHARSETS[charset_name] = custom_charset
        else:
            charset_name = "standard"
    else:
        charset_name = charset_choice

    st.divider()
    st.markdown("### 📐 Width")
    width = st.slider("Columns", 40, 200, 100, step=5, label_visibility="collapsed")

    st.divider()
    st.code("pip install movie-ascii", language="bash")
    st.markdown("[GitHub ↗](https://github.com/marabunta-labs/movie-ascii)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def show_ascii_html(html_content):
    st.markdown(f'<div class="ascii-output">{html_content}</div>', unsafe_allow_html=True)


def show_cli_cmd(source):
    cs = f'"{CHARSETS[charset_name]}"' if charset_name == "_web_custom" else charset_name
    st.code(f"$ movie-ascii {source} -m {mode} -c {cs} -w {width}", language="bash")


def get_video_b64(path):
    """Read video file and return base64 encoded data URL."""
    with open(path, "rb") as f:
        data = f.read()
    b64 = base64.b64encode(data).decode()
    # Detect mime
    ext = Path(path).suffix.lower()
    mime = {"mp4": "video/mp4", "webm": "video/webm", "mov": "video/mp4",
            "avi": "video/x-msvideo", "mkv": "video/x-matroska"}.get(ext.lstrip("."), "video/mp4")
    return f"data:{mime};base64,{b64}"


def convert_to_mp4(input_path):
    """Convert video to MP4 H.264 for browser compatibility. Returns new path."""
    output_path = input_path + ".browser.mp4"
    try:
        subprocess.run([
            _FFMPEG_EXE, "-y", "-i", input_path,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            "-pix_fmt", "yuv420p",
            output_path
        ], check=True, capture_output=True, timeout=300)
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return output_path
    except Exception:
        pass
    return input_path  # fallback to original


def download_youtube(url, output_dir, video_id):
    """Download YouTube video with yt-dlp as mp4."""
    out_path = os.path.join(output_dir, f"{video_id}.mp4")
    try:
        subprocess.run(
            ["yt-dlp", "-f", "best[height<=720][ext=mp4]/best[ext=mp4]/best",
             "--no-playlist", "--merge-output-format", "mp4",
             "-o", out_path, url],
            check=True, capture_output=True, timeout=300,
        )
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            return out_path
    except Exception:
        pass
    return None


def build_ascii_player(video_data_url, cols, mode_name, charset_str):
    """Build the real-time ASCII video player.
    
    The video plays in a hidden <video> element. JavaScript reads each frame
    from a canvas, converts pixels to ASCII characters with colors, and displays
    them. This is REAL-TIME — no pre-processing. Exactly like the CLI tool.
    
    Controls: play/pause (space), seek (arrows/bar), speed, fullscreen-like.
    Audio comes from the video element itself.
    """
    # Escape charset for JS
    charset_js = charset_str.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "")
    
    # ANSI 8-color palette for ascii-color mode
    ansi_colors_js = "['#555555','#FF5555','#55FF55','#FFFF55','#5555FF','#FF55FF','#55FFFF','#FFFFFF']"

    return f'''<!DOCTYPE html>
<html>
<head><meta charset="UTF-8">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#000; overflow:hidden; display:flex; flex-direction:column; height:100vh; width:100vw; }}
#ascii {{
    flex: 1;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
}}
#out {{
    font-family: 'JetBrains Mono','Fira Code','Courier New',monospace;
    letter-spacing: 0;
    white-space: pre;
    /* font-size set dynamically by JS to fill width */
}}
#bar {{
    background: #111;
    padding: 6px 12px;
    display: flex;
    align-items: center;
    gap: 8px;
    border-top: 1px solid #333;
    flex-shrink: 0;
    height: 38px;
}}
#bar button {{
    background: #4ade80;
    color: #000;
    border: none;
    border-radius: 4px;
    padding: 4px 10px;
    cursor: pointer;
    font-weight: bold;
    font-size: 13px;
    min-width: 32px;
}}
#bar button:hover {{ background: #22c55e; }}
#seek {{ flex:1; accent-color:#4ade80; cursor:pointer; height:5px; }}
.lbl {{ color:#888; font-size:11px; font-family:monospace; white-space:nowrap; }}
#spd-range {{ width:50px; accent-color:#4ade80; }}
video, canvas {{ display:none; }}
</style>
</head>
<body>
<video id="vid" crossorigin="anonymous" preload="auto">
    <source src="{video_data_url}" type="video/mp4">
</video>
<canvas id="cvs"></canvas>
<div id="ascii"><div id="out"></div></div>
<div id="bar">
    <button id="pb" onclick="toggle()">▶</button>
    <button onclick="skip(-5)">-5s</button>
    <button onclick="skip(5)">+5s</button>
    <input id="seek" type="range" min="0" max="100" value="0" step="0.1" oninput="seekTo(+this.value)">
    <span class="lbl" id="time">0:00 / 0:00</span>
    <input id="spd-range" type="range" min="25" max="300" step="25" value="100" oninput="setSpd(+this.value)" title="Speed">
    <span class="lbl" id="spd">1x</span>
</div>
<script>
const COLS = {cols};
const MODE = '{mode_name}';
const CHARS = '{charset_js}';
const ANSI = {ansi_colors_js};

const vid = document.getElementById('vid');
const cvs = document.getElementById('cvs');
const ctx = cvs.getContext('2d', {{willReadFrequently: true}});
const out = document.getElementById('out');
const seekBar = document.getElementById('seek');
const timeEl = document.getElementById('time');
const pbBtn = document.getElementById('pb');
const spdEl = document.getElementById('spd');

let playing = false;
let rafId = null;

// Calculate rows maintaining aspect ratio (height/width * 0.5 for char aspect)
function calcRows() {{
    if (vid.videoWidth === 0) return 30;
    return Math.max(1, Math.round(COLS * (vid.videoHeight / vid.videoWidth) * 0.5));
}}

// Set font size to fill container width
function setFontSize() {{
    const containerW = document.getElementById('ascii').clientWidth;
    // Each monospace char is roughly 0.6em wide
    const fs = containerW / (COLS * 0.602);
    out.style.fontSize = fs + 'px';
    out.style.lineHeight = (fs * 1.15) + 'px';
}}

function fmt(s) {{
    if (isNaN(s)) return '0:00';
    const m = Math.floor(s/60), sec = Math.floor(s%60);
    return m + ':' + (sec<10?'0':'') + sec;
}}

function renderFrame() {{
    const rows = calcRows();
    cvs.width = COLS;
    cvs.height = rows;
    ctx.drawImage(vid, 0, 0, COLS, rows);
    const data = ctx.getImageData(0, 0, COLS, rows).data;
    const nChars = CHARS.length;
    let html = '';

    for (let y = 0; y < rows; y++) {{
        for (let x = 0; x < COLS; x++) {{
            const i = (y * COLS + x) * 4;
            const r = data[i], g = data[i+1], b = data[i+2];
            const lum = 0.299*r + 0.587*g + 0.114*b;
            const ci = Math.min(Math.floor(lum / 255 * (nChars-1)), nChars-1);
            let ch = CHARS[ci];
            // HTML escape
            if (ch === '&') ch = '&amp;';
            else if (ch === '<') ch = '&lt;';
            else if (ch === '>') ch = '&gt;';
            else if (ch === ' ') ch = '&nbsp;';

            if (MODE === 'bw') {{
                html += '<span style="color:#ddd">' + ch + '</span>';
            }} else if (MODE === 'ascii-color') {{
                const ai = (r>127?1:0) + (g>127?2:0) + (b>127?4:0);
                html += '<span style="color:' + ANSI[ai] + '">' + ch + '</span>';
            }} else {{
                html += '<span style="color:rgb('+r+','+g+','+b+')">' + ch + '</span>';
            }}
        }}
        html += '\\n';
    }}
    out.innerHTML = html;
}}

function updateUI() {{
    const cur = vid.currentTime, dur = vid.duration || 0;
    seekBar.value = dur > 0 ? (cur / dur * 100) : 0;
    timeEl.textContent = fmt(cur) + ' / ' + fmt(dur);
}}

function loop() {{
    if (!vid.paused && !vid.ended) {{
        renderFrame();
        updateUI();
    }}
    rafId = requestAnimationFrame(loop);
}}

function toggle() {{
    if (vid.paused) {{
        vid.play();
        playing = true;
        pbBtn.textContent = '⏸';
    }} else {{
        vid.pause();
        playing = false;
        pbBtn.textContent = '▶';
    }}
}}

function seekTo(pct) {{
    const t = (pct / 100) * (vid.duration || 0);
    vid.currentTime = t;
    renderFrame();
    updateUI();
}}

function skip(s) {{
    vid.currentTime = Math.max(0, Math.min(vid.duration || 0, vid.currentTime + s));
    renderFrame();
    updateUI();
}}

function setSpd(v) {{
    const s = v / 100;
    vid.playbackRate = s;
    spdEl.textContent = s.toFixed(s < 1 ? 2 : 1) + 'x';
}}

// Keyboard
document.addEventListener('keydown', function(e) {{
    if (e.code === 'Space') {{ e.preventDefault(); toggle(); }}
    else if (e.code === 'ArrowRight') {{ e.preventDefault(); skip(5); }}
    else if (e.code === 'ArrowLeft') {{ e.preventDefault(); skip(-5); }}
    else if (e.code === 'ArrowUp') {{ e.preventDefault(); vid.volume = Math.min(1, vid.volume + 0.1); }}
    else if (e.code === 'ArrowDown') {{ e.preventDefault(); vid.volume = Math.max(0, vid.volume - 0.1); }}
}});

// Init
vid.addEventListener('loadedmetadata', function() {{
    setFontSize();
    renderFrame();
    updateUI();
}});

vid.addEventListener('ended', function() {{
    playing = false;
    pbBtn.textContent = '▶';
}});

window.addEventListener('resize', setFontSize);

// Start render loop
rafId = requestAnimationFrame(loop);

// Autoplay
vid.play().then(() => {{
    playing = true;
    pbBtn.textContent = '⏸';
}}).catch(() => {{
    // Autoplay blocked, user needs to click play
    pbBtn.textContent = '▶';
}});
</script>
</body>
</html>'''


# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------
st.markdown("# 🎬 movie-ascii — Live Demo")
st.caption("Real-time ASCII rendering in the browser. Play, pause, seek — instant, no processing wait.")

# ===========================================================================
# IMAGE
# ===========================================================================
if input_mode == "📷 Image":
    uploaded = st.file_uploader("Drop an image or GIF", type=["png", "jpg", "jpeg", "webp", "bmp", "gif"], key="img")
    if uploaded:
        raw_bytes = uploaded.read()
        is_gif = uploaded.name.lower().endswith(".gif")

        # GIFs → treat as video (real-time player looping, no controls)
        if is_gif:
            show_cli_cmd(uploaded.name)
            col1, col2 = st.columns([1, 1])
            with col1:
                st.markdown("**Original GIF**")
                st.image(raw_bytes, use_container_width=True)
            with col2:
                st.markdown("**ASCII (real-time)**")
                # Save GIF, convert to mp4 for the player
                tmp_dir = tempfile.mkdtemp(prefix="mascii_gif_")
                gif_path = os.path.join(tmp_dir, "input.gif")
                mp4_path = os.path.join(tmp_dir, "input.mp4")
                with open(gif_path, "wb") as f:
                    f.write(raw_bytes)
                # Convert GIF to MP4
                subprocess.run([
                    _FFMPEG_EXE, "-y", "-i", gif_path,
                    "-movflags", "faststart", "-pix_fmt", "yuv420p",
                    "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                    mp4_path
                ], capture_output=True, timeout=30)

                if os.path.exists(mp4_path) and os.path.getsize(mp4_path) > 0:
                    video_url = get_video_b64(mp4_path)
                    charset_str = CHARSETS.get(charset_name, CHARSETS["standard"])
                    charset_js = charset_str.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "")
                    ansi_colors_js = "['#555555','#FF5555','#55FF55','#FFFF55','#5555FF','#FF55FF','#55FFFF','#FFFFFF']"
                    # Minimal looping player, no controls
                    gif_player = f'''<!DOCTYPE html>
<html><head><meta charset="UTF-8"><style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:#000;overflow:hidden;width:100vw;height:100vh;display:flex;align-items:center;justify-content:center;}}
#out{{font-family:'JetBrains Mono','Fira Code','Courier New',monospace;letter-spacing:0;white-space:pre;}}
video,canvas{{display:none;}}
</style></head><body>
<video id="vid" loop muted autoplay playsinline><source src="{video_url}" type="video/mp4"></video>
<canvas id="cvs"></canvas>
<div id="out"></div>
<script>
const COLS={width},MODE='{mode}',CHARS='{charset_js}',ANSI={ansi_colors_js};
const vid=document.getElementById('vid'),cvs=document.getElementById('cvs'),ctx=cvs.getContext('2d',{{willReadFrequently:true}}),out=document.getElementById('out');
function setFS(){{const fs=document.body.clientWidth/(COLS*0.602);out.style.fontSize=fs+'px';out.style.lineHeight=(fs*1.15)+'px';}}
function render(){{
const rows=Math.max(1,Math.round(COLS*(vid.videoHeight/vid.videoWidth)*0.5));
cvs.width=COLS;cvs.height=rows;ctx.drawImage(vid,0,0,COLS,rows);
const d=ctx.getImageData(0,0,COLS,rows).data,n=CHARS.length;let h='';
for(let y=0;y<rows;y++){{for(let x=0;x<COLS;x++){{const i=(y*COLS+x)*4,r=d[i],g=d[i+1],b=d[i+2];
const lum=0.299*r+0.587*g+0.114*b,ci=Math.min(Math.floor(lum/255*(n-1)),n-1);
let ch=CHARS[ci];if(ch==='&')ch='&amp;';else if(ch==='<')ch='&lt;';else if(ch==='>')ch='&gt;';else if(ch===' ')ch='&nbsp;';
if(MODE==='bw')h+='<span style="color:#ddd">'+ch+'</span>';
else if(MODE==='ascii-color'){{const ai=(r>127?1:0)+(g>127?2:0)+(b>127?4:0);h+='<span style="color:'+ANSI[ai]+'">'+ch+'</span>';}}
else h+='<span style="color:rgb('+r+','+g+','+b+')">'+ch+'</span>';}}h+='\\n';}}
out.innerHTML=h;requestAnimationFrame(render);}}
vid.addEventListener('loadedmetadata',function(){{setFS();render();}});
window.addEventListener('resize',setFS);
vid.play();
</script></body></html>'''
                    cap = cv2.VideoCapture(mp4_path)
                    vw_px = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 320
                    vh_px = cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 240
                    cap.release()
                    aspect = vh_px / vw_px
                    rows = int(width * aspect * 0.5)
                    est_fs = 500.0 / (width * 0.602)
                    est_lh = est_fs * 1.15
                    player_h = int(rows * est_lh + 20)
                    player_h = max(200, min(player_h, 600))
                    components.html(gif_player, height=player_h, scrolling=False)
                else:
                    file_bytes = np.frombuffer(raw_bytes, np.uint8)
                    img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
                    if img is not None:
                        resized = resize_image(img, width)
                        html = pixels_to_html(resized, mode, charset_name)
                        show_ascii_html(html)
        else:
            # Static image
            file_bytes = np.frombuffer(raw_bytes, np.uint8)
            img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
            if img is None:
                st.error("Could not decode image")
            else:
                show_cli_cmd(uploaded.name)
                col1, col2 = st.columns([1, 2])
                with col1:
                    st.markdown("**Original**")
                    st.image(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), use_container_width=True)
                with col2:
                    st.markdown("**ASCII**")
                    resized = resize_image(img, width)
                    html = pixels_to_html(resized, mode, charset_name)
                    show_ascii_html(html)

# ===========================================================================
# VIDEO — Real-time client-side ASCII rendering
# ===========================================================================
elif input_mode == "🎥 Video":
    uploaded = st.file_uploader("Drop a video (MP4, max 200MB)",
                                type=["mp4", "webm", "mov", "avi", "mkv"], key="vid")
    if uploaded:
        show_cli_cmd(uploaded.name)

        # Save file
        if "vid_path" not in st.session_state or st.session_state.get("vid_name") != uploaded.name:
            tmp_dir = tempfile.mkdtemp(prefix="mascii_")
            tmp_path = os.path.join(tmp_dir, f"input{Path(uploaded.name).suffix}")
            with open(tmp_path, "wb") as f:
                f.write(uploaded.read())
            # Convert to browser-compatible MP4 if needed
            ext = Path(uploaded.name).suffix.lower()
            if ext not in [".mp4", ".webm"]:
                with st.spinner("Converting to browser format..."):
                    tmp_path = convert_to_mp4(tmp_path)
            st.session_state["vid_path"] = tmp_path
            st.session_state["vid_name"] = uploaded.name
        else:
            tmp_path = st.session_state["vid_path"]

        # Show original
        st.markdown("#### 📹 Original")
        st.video(tmp_path)

        st.divider()
        st.markdown("#### 🎬 ASCII (real-time)")
        st.caption("Space = play/pause • ← → = ±5s • ↑↓ = volume • Speed slider")

        # Build player with video embedded as base64
        with st.spinner("Loading video into player..."):
            video_url = get_video_b64(tmp_path)
            charset_str = CHARSETS.get(charset_name, CHARSETS["standard"])
            player_html = build_ascii_player(video_url, width, mode, charset_str)

        # Calculate height
        cap = cv2.VideoCapture(tmp_path)
        vw = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920
        vh = cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080
        cap.release()
        aspect = vh / vw
        rows = int(width * aspect * 0.5)
        # Estimate: font-size ≈ containerWidth/(cols*0.602), lineHeight = fs*1.15
        # container ≈ 1000px → fs ≈ 16.6px, lh ≈ 19px for width=100
        est_fs = 1000.0 / (width * 0.602)
        est_lh = est_fs * 1.15
        player_h = int(rows * est_lh + 50)
        player_h = max(300, min(player_h, 850))

        components.html(player_html, height=player_h, scrolling=False)

# ===========================================================================
# YOUTUBE — Download then real-time play
# ===========================================================================
elif input_mode == "📺 YouTube":
    url = st.text_input("🔗 YouTube URL", placeholder="https://youtu.be/dQw4w9WgXcQ")

    if url:
        video_id = get_youtube_id(url)
        if not video_id:
            st.error("Invalid YouTube URL.")
        else:
            show_cli_cmd(url)

            # Embedded original
            st.markdown("#### 📹 Original")
            st.markdown(
                f'<iframe width="100%" height="400" '
                f'src="https://www.youtube.com/embed/{video_id}" '
                f'allow="accelerometer; autoplay; encrypted-media; gyroscope" '
                f'allowfullscreen></iframe>',
                unsafe_allow_html=True,
            )
            st.divider()

            if st.button("▶️ Play ASCII", type="primary", use_container_width=True):
                with st.spinner("⬇️ Downloading from YouTube..."):
                    tmp_dir = tempfile.mkdtemp(prefix="mascii_yt_")
                    dl_path = download_youtube(url, tmp_dir, video_id)

                if not dl_path:
                    st.error("Could not download. Video might be restricted.")
                else:
                    st.markdown("#### 🎬 ASCII (real-time)")
                    st.caption("Space = play/pause • ← → = ±5s • ↑↓ = volume")

                    with st.spinner("Loading video..."):
                        video_url = get_video_b64(dl_path)
                        charset_str = CHARSETS.get(charset_name, CHARSETS["standard"])
                        player_html = build_ascii_player(video_url, width, mode, charset_str)

                    cap = cv2.VideoCapture(dl_path)
                    vw = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920
                    vh = cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080
                    cap.release()
                    aspect = vh / vw
                    rows = int(width * aspect * 0.5)
                    est_fs = 1000.0 / (width * 0.602)
                    est_lh = est_fs * 1.15
                    player_h = int(rows * est_lh + 50)
                    player_h = max(300, min(player_h, 850))

                    components.html(player_html, height=player_h, scrolling=False)
