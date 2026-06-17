import os
import sys
import time
import shutil
import socket
import tempfile
import subprocess
import threading
from pathlib import Path

import gradio as gr
import numpy as np

# ─── optional heavy imports (loaded lazily) ─────────────────────────────────
_whisper_model = None

def _get_whisper(model_name="base"):
    global _whisper_model
    if _whisper_model is None:
        import whisper
        _whisper_model = whisper.load_model(model_name)
    return _whisper_model


# ─── helpers ────────────────────────────────────────────────────────────────

TMPDIR = Path(tempfile.gettempdir()) / "vid_editor"
TMPDIR.mkdir(exist_ok=True)


def _tmp(suffix=""):
    return str(TMPDIR / f"ve_{int(time.time()*1000)}{suffix}")


def _ffmpeg(args: list[str], progress_cb=None) -> str:
    cmd = ["ffmpeg", "-y"] + args
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    stderr_lines = []
    for line in proc.stderr:
        stderr_lines.append(line)
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("FFmpeg error:\n" + "".join(stderr_lines[-30:]))
    return "".join(stderr_lines)


def _check_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except FileNotFoundError:
        raise RuntimeError(
            "FFmpeg não encontrado. Instale FFmpeg e adicione ao PATH.\n"
            "Windows: https://ffmpeg.org/download.html\n"
            "Mac:     brew install ffmpeg\n"
            "Linux:   sudo apt install ffmpeg"
        )


# ─── 1. AUDIO ENHANCEMENT ───────────────────────────────────────────────────

def enhance_audio(input_video: str) -> str:
    """Apply podcast-quality audio processing via FFmpeg filters."""
    out = _tmp(".wav")
    audio_filter = (
        "highpass=f=80,"
        "lowpass=f=12000,"
        "equalizer=f=3000:width_type=o:width=2:g=3,"
        "compand=attacks=0.05:decays=0.5:points=-80/-80|-45/-15|-27/-9|0/-7:soft-knee=6,"
        "loudnorm=I=-16:LRA=11:TP=-1.5"
    )
    _ffmpeg(["-i", input_video, "-af", audio_filter, "-ar", "44100", "-ac", "1", out])
    return out


def merge_audio(input_video: str, enhanced_audio: str) -> str:
    """Replace original audio with enhanced version."""
    out = _tmp(".mp4")
    _ffmpeg([
        "-i", input_video,
        "-i", enhanced_audio,
        "-c:v", "copy",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest",
        out,
    ])
    return out


# ─── 2. SUBTITLES ────────────────────────────────────────────────────────────

def transcribe(audio_path: str, whisper_model: str = "base") -> list[dict]:
    """Return list of {start, end, text} segments from Whisper."""
    model = _get_whisper(whisper_model)
    result = model.transcribe(audio_path, word_timestamps=True)
    segments = []
    for seg in result["segments"]:
        if "words" in seg:
            words = seg["words"]
            chunk, chunk_start = [], None
            for i, w in enumerate(words):
                word = w["word"].strip()
                if not word:
                    continue
                if chunk_start is None:
                    chunk_start = w["start"]
                chunk.append(word)
                if len(chunk) == 4 or i == len(words) - 1:
                    segments.append({
                        "start": chunk_start,
                        "end": w["end"],
                        "text": " ".join(chunk),
                    })
                    chunk, chunk_start = [], None
        else:
            segments.append({
                "start": seg["start"],
                "end": seg["end"],
                "text": " ".join(seg["text"].split()[:4]),
            })
    return segments


def _ts_srt(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ts_ass(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def build_srt(segments: list[dict]) -> str:
    lines = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{_ts_srt(seg['start'])} --> {_ts_srt(seg['end'])}")
        lines.append(seg["text"])
        lines.append("")
    return "\n".join(lines)


def build_ass(segments: list[dict]) -> str:
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1280\n"
        "PlayResY: 720\n\n"
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
        "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,"
        "ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
        "Alignment,MarginL,MarginR,MarginV,Encoding\n"
        "Style: Impact,Arial,72,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        "-1,0,0,0,100,100,0,0,1,3,1,2,10,10,30,1\n\n"
        "[Events]\n"
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    )
    events = []
    for seg in segments:
        fade = r"{\fad(80,80)}"
        text = seg["text"].upper()
        events.append(
            f"Dialogue: 0,{_ts_ass(seg['start'])},{_ts_ass(seg['end'])},"
            f"Impact,,0,0,0,,{fade}{text}"
        )
    return header + "\n".join(events)


def burn_subtitles(input_video: str, ass_path: str) -> str:
    out = _tmp(".mp4")
    _ffmpeg([
        "-i", input_video,
        "-vf", f"ass={ass_path}",
        "-c:a", "copy",
        out,
    ])
    return out


# ─── 3. VISUAL ANIMATIONS ────────────────────────────────────────────────────

def detect_pauses(audio_path: str, min_silence_db: float = -40, min_duration: float = 0.8) -> list[float]:
    """Return timestamps (seconds) where pauses > min_duration occur."""
    try:
        import scipy.io.wavfile as wav
        rate, data = wav.read(audio_path)
        if data.ndim > 1:
            data = data.mean(axis=1)
        data = data.astype(np.float32)
        max_val = np.abs(data).max()
        if max_val > 0:
            data /= max_val

        frame_size = int(rate * 0.05)
        rms_db = []
        for i in range(0, len(data) - frame_size, frame_size):
            frame = data[i:i + frame_size]
            rms = np.sqrt(np.mean(frame ** 2))
            db = 20 * np.log10(rms + 1e-9)
            rms_db.append((i / rate, db))

        pauses = []
        silence_start = None
        for t, db in rms_db:
            if db < min_silence_db:
                if silence_start is None:
                    silence_start = t
            else:
                if silence_start is not None and (t - silence_start) >= min_duration:
                    pauses.append(silence_start + (t - silence_start) / 2)
                silence_start = None
        return pauses
    except Exception:
        return []


def _escape_drawtext(text: str) -> str:
    for ch in ["'", ":", "\\"]:
        text = text.replace(ch, "\\" + ch)
    return text


def build_drawtext_filters(
    pauses: list[float],
    custom_title: str = "",
    video_width: int = 1280,
    video_height: int = 720,
) -> list[str]:
    filters = []

    if custom_title.strip():
        title = _escape_drawtext(custom_title.strip())
        filters.append(
            f"drawtext=text='{title}'"
            f":fontsize=72:fontcolor=white:borderw=3:bordercolor=black"
            f":x='if(lt(t\\,0.5)\\,-w+(t/0.5)*({video_width}/2+w/2)\\,({video_width}-tw)/2)'"
            f":y={video_height//4}"
            f":enable='between(t\\,0\\,3)'"
        )

    for i, pause_t in enumerate(pauses, 1):
        label = _escape_drawtext(f"Tópico {i}")
        start = pause_t
        end = pause_t + 3
        x_anim = (
            f"if(lt(t\\,{start+0.4:.2f})\\,"
            f"-tw+((t-{start:.2f})/{0.4:.2f})*({video_width//2}+tw)\\,"
            f"{video_width//2}-tw/2)"
        )
        filters.append(
            f"drawtext=text='{label}'"
            f":fontsize=54:fontcolor=yellow:borderw=3:bordercolor=black"
            f":x='{x_anim}'"
            f":y={int(video_height * 0.8)}"
            f":enable='between(t\\,{start:.2f}\\,{end:.2f})'"
        )

    return filters


def apply_visual_animations(
    input_video: str,
    pauses: list[float],
    custom_title: str = "",
) -> str:
    filters = build_drawtext_filters(pauses, custom_title)
    if not filters:
        return input_video
    out = _tmp(".mp4")
    vf = ",".join(filters)
    _ffmpeg(["-i", input_video, "-vf", vf, "-c:a", "copy", out])
    return out


# ─── MAIN PIPELINE ───────────────────────────────────────────────────────────

def process_video(
    input_path: str,
    do_audio: bool,
    do_subtitles: bool,
    do_animations: bool,
    custom_title: str,
    whisper_model: str,
    progress: gr.Progress = gr.Progress(),
) -> tuple[str, str, str, str]:
    """
    Returns: (output_video_path, srt_path, status_message, preview_audio_path)
    """
    try:
        _check_ffmpeg()
        if not input_path:
            return None, None, "Nenhum vídeo enviado.", None

        progress(0.0, desc="Iniciando processamento...")
        current = input_path
        srt_out = None
        preview_audio = None

        # ── step 1: audio enhancement ──────────────────────────
        if do_audio:
            progress(0.1, desc="Melhorando qualidade de áudio...")
            enhanced_wav = enhance_audio(current)
            preview_audio = enhanced_wav
            progress(0.25, desc="Mesclando áudio melhorado...")
            current = merge_audio(current, enhanced_wav)
        else:
            # extract audio for whisper / pause detection anyway
            tmp_wav = _tmp(".wav")
            _ffmpeg(["-i", current, "-ac", "1", "-ar", "16000", tmp_wav])
            preview_audio = tmp_wav

        # ── step 2: subtitles ──────────────────────────────────
        segments = []
        if do_subtitles:
            progress(0.35, desc="Transcrevendo com Whisper (pode demorar)...")
            segments = transcribe(preview_audio, whisper_model)
            progress(0.60, desc="Gerando legendas...")
            srt_content = build_srt(segments)
            srt_out = _tmp(".srt")
            Path(srt_out).write_text(srt_content, encoding="utf-8")
            ass_path = _tmp(".ass")
            Path(ass_path).write_text(build_ass(segments), encoding="utf-8")
            progress(0.70, desc="Gravando legendas no vídeo...")
            current = burn_subtitles(current, ass_path)

        # ── step 3: animations ─────────────────────────────────
        if do_animations:
            progress(0.80, desc="Detectando pausas e adicionando animações...")
            pauses = detect_pauses(preview_audio)
            current = apply_visual_animations(current, pauses, custom_title)

        # ── finalize ───────────────────────────────────────────
        progress(0.95, desc="Finalizando...")
        final_out = _tmp("_final.mp4")
        if current.endswith("_final.mp4"):
            final_out = current
        else:
            shutil.copy(current, final_out)

        progress(1.0, desc="Concluído!")
        msg = "Processamento concluído com sucesso!"
        if do_subtitles and not segments:
            msg += " (Nenhuma fala detectada — verifique se o vídeo tem áudio.)"
        return final_out, srt_out, msg, preview_audio

    except Exception as exc:
        return None, None, f"Erro: {exc}", None


# ─── GRADIO UI ───────────────────────────────────────────────────────────────

CSS = """
#title { text-align: center; font-size: 1.6em; font-weight: bold; margin-bottom: 0.2em; }
#subtitle { text-align: center; color: #888; margin-bottom: 1em; }
.gr-button-primary { background: #6366f1 !important; }
"""

with gr.Blocks(title="Video Editor Pro", css=CSS) as demo:
    gr.Markdown("# Video Editor Pro", elem_id="title")
    gr.Markdown(
        "Edição automatizada de vídeo com melhoria de áudio, legendas de impacto e animações visuais.",
        elem_id="subtitle",
    )

    with gr.Row():
        with gr.Column(scale=1):
            video_input = gr.Video(label="Upload de Vídeo (MP4 / MOV / AVI)")

            gr.Markdown("### Funcionalidades")
            do_audio = gr.Checkbox(label="Melhoria de Áudio (qualidade podcast)", value=True)
            do_subtitles = gr.Checkbox(label="Legendas de Impacto (estilo Reels)", value=True)
            do_animations = gr.Checkbox(label="Animações e Elementos Visuais", value=True)

            with gr.Accordion("Configurações avançadas", open=False):
                whisper_model = gr.Dropdown(
                    choices=["tiny", "base", "small", "medium", "large"],
                    value="base",
                    label="Modelo Whisper",
                    info="Modelos maiores = mais preciso, porém mais lento.",
                )
                custom_title = gr.Textbox(
                    label="Título customizado no início (opcional)",
                    placeholder="Ex: Como fazer X em 5 passos",
                )

            process_btn = gr.Button("Processar Vídeo", variant="primary")

        with gr.Column(scale=1):
            status_box = gr.Textbox(label="Status", interactive=False, lines=2)

            gr.Markdown("### Preview do Áudio Processado")
            audio_preview = gr.Audio(label="Áudio melhorado", type="filepath")

            gr.Markdown("### Downloads")
            video_output = gr.Video(label="Vídeo Final")
            srt_output = gr.File(label="Arquivo .SRT de Legendas")

    process_btn.click(
        fn=process_video,
        inputs=[
            video_input,
            do_audio,
            do_subtitles,
            do_animations,
            custom_title,
            whisper_model,
        ],
        outputs=[video_output, srt_output, status_box, audio_preview],
        show_progress=True,
    )

    gr.Markdown(
        "---\n"
        "**Dica:** Para melhores resultados com as legendas, use o modelo `small` ou `medium` do Whisper. "
        "O modelo `tiny` é mais rápido mas menos preciso.",
        elem_id="footer",
    )


def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _print_qr(url: str):
    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        print("\n" + "═" * 52)
        print("  Escaneie o QR Code abaixo com o celular:")
        print("═" * 52)
        qr.print_ascii(invert=True)
        print(f"  URL: {url}")
        print("═" * 52 + "\n")
    except Exception:
        print(f"\n  Acesse: {url}\n")


def _show_access_info(local_url: str, share_url: str | None):
    local_ip = _local_ip()
    wifi_url = f"http://{local_ip}:7860"

    print("\n" + "═" * 52)
    print("  VIDEO EDITOR PRO — Acesso")
    print("═" * 52)
    print(f"  Mesmo computador : {local_url}")
    print(f"  Rede WiFi local  : {wifi_url}")
    if share_url:
        print(f"  Link público     : {share_url}")
    print("═" * 52)

    # QR do link público tem prioridade (funciona fora do WiFi)
    qr_url = share_url if share_url else wifi_url
    _print_qr(qr_url)


if __name__ == "__main__":
    result = demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=True,
        inbrowser=False,
        prevent_thread_lock=True,
        quiet=True,
    )
    local_url = f"http://127.0.0.1:7860"
    share_url = getattr(result, "share_url", None) or (
        result[2] if isinstance(result, tuple) and len(result) > 2 else None
    )
    _show_access_info(local_url, share_url)

    # mantém o processo vivo
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\nAplicação encerrada.")
