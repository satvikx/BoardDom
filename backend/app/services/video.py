"""Narrated slide videos from a unit's published notes.

script (model) -> slides (Pillow PNGs) -> narration (TTS WAV per slide) -> mp4 (ffmpeg from
imageio-ffmpeg). Without TTS (demo mode, TTS off, or a TTS error) the video is silent and the
narration is burned in as captions, timed by reading speed.
"""

import logging
import re
import subprocess
import tempfile
import wave
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel

from app.ai import AIError
from app.models.entities import Video, Workspace, utcnow
from app.services.course_content import DATA_NOT_INSTRUCTIONS, course_header, notes_block
from app.services.jobs import JobFailed
from app.services.student_tools import published_unit

logger = logging.getLogger(__name__)
W, H = 1280, 720
PAPER, INK, ACCENT, SOFT, MUTED = "#f8f9f4", "#233b32", "#325d46", "#ecf1e7", "#626f65"
MAX_SLIDES = 6
WORDS_PER_SECOND = 2.6
TIMEOUT = 300


class VideoSlide(BaseModel):
    title: str
    bullets: list[str]
    narration: str


class VideoScript(BaseModel):
    slides: list[VideoSlide]


INSTRUCTIONS = (
    "Turn the unit notes into a short narrated slide video for students: 3 to 6 slides. Each "
    "slide has a short title, up to 4 bullets of a few words, and 1 to 3 sentences of "
    "narration in plain spoken language. Use only the notes. Do not include citation labels "
    f"such as [C3] anywhere. {DATA_NOT_INSTRUCTIONS}"
)


def plain(text: str) -> str:
    text = re.sub(r"\s?\[[CW]\d{1,6}\]", "", text)
    return re.sub(r"\s+", " ", text.replace("**", "")).strip()


def videos_dir(settings) -> Path:
    return settings.resolved_upload_dir / "videos"


def video_path(settings, key: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", key or ""):
        raise ValueError("bad video key")
    return videos_dir(settings) / f"{key}.mp4"


def font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except (TypeError, OSError):  # Pillow without FreeType: fixed bitmap font
        return ImageFont.load_default()


def wrap(draw: ImageDraw.ImageDraw, text: str, face, width: int) -> list[str]:
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=face) <= width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    return [*lines, current] if current else lines


def render_slide(slide: VideoSlide, footer: str, caption: str | None, path: Path) -> None:
    image = Image.new("RGB", (W, H), PAPER)
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, W, 14], fill=ACCENT)
    title_font, bullet_font, small = font(54), font(34), font(22)
    y = 70
    for line in wrap(draw, plain(slide.title), title_font, W - 160)[:2]:
        draw.text((80, y), line, font=title_font, fill=INK)
        y += 66
    y += 24
    for bullet in slide.bullets[:4]:
        lines = wrap(draw, plain(bullet), bullet_font, W - 220)[:2]
        draw.ellipse([88, y + 14, 102, y + 28], fill=ACCENT)
        for line in lines:
            draw.text((124, y), line, font=bullet_font, fill=INK)
            y += 44
        y += 14
    draw.text((80, H - (200 if caption else 50)), footer, font=small, fill=MUTED)
    if caption:
        caption_font = font(30)
        draw.rectangle([0, H - 160, W, H], fill=INK)
        for i, line in enumerate(wrap(draw, caption, caption_font, W - 120)[:3]):
            draw.text((60, H - 140 + i * 40), line, font=caption_font, fill=SOFT)
    image.save(path, "PNG")


def caption_chunks(text: str, max_words: int = 22) -> list[str]:
    """Split narration into caption-sized pieces at sentence boundaries where possible."""
    chunks, current = [], []
    for sentence in re.split(r"(?<=[.!?])\s+", plain(text)):
        words = sentence.split()
        if current and len(current) + len(words) > max_words:
            chunks.append(" ".join(current))
            current = []
        while len(words) > max_words:
            chunks.append(" ".join(words[:max_words]))
            words = words[max_words:]
        current += words
    if current:
        chunks.append(" ".join(current))
    return chunks or [""]


def join_wavs(clips: list[bytes], gap: float, target: Path) -> list[float]:
    """Concatenate WAV clips with `gap` seconds of silence after each; return clip lengths."""
    params, durations, frames = None, [], []
    for clip in clips:
        with wave.open(BytesIO(clip)) as source:
            current = (source.getnchannels(), source.getsampwidth(), source.getframerate())
            if params and current != params:
                raise ValueError("narration clips use different audio formats")
            params = current
            data = source.readframes(source.getnframes())
            durations.append(source.getnframes() / source.getframerate())
        channels, width, rate = params
        frames.append(data + b"\0" * int(gap * rate) * channels * width)
    channels, width, rate = params
    with wave.open(str(target), "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(width)
        out.setframerate(rate)
        out.writeframes(b"".join(frames))
    return durations


def assemble(frames: list[tuple[Path, float]], audio: Path | None, out: Path) -> None:
    """Concat-demuxer slideshow (+ optional audio) -> H.264/AAC mp4."""
    listing = frames[0][0].parent / "frames.txt"  # temp work folder, not next to the mp4
    lines = []
    for path, seconds in frames:
        lines += [f"file '{path.as_posix()}'", f"duration {seconds:.3f}"]
    lines.append(f"file '{frames[-1][0].as_posix()}'")  # last frame needs a repeat
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    command = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error"]
    command += ["-f", "concat", "-safe", "0", "-i", str(listing)]
    if audio:
        command += ["-i", str(audio)]
    command += ["-vf", "fps=25,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast"]
    command += ["-tune", "stillimage"]
    if audio:
        command += ["-c:a", "aac", "-b:a", "128k", "-shortest"]
    command += ["-movflags", "+faststart", str(out)]
    result = subprocess.run(command, capture_output=True, timeout=TIMEOUT, check=False)
    if result.returncode != 0 or not out.exists():
        logger.error("ffmpeg failed: %s", result.stderr.decode(errors="replace")[-500:])
        raise JobFailed("Could not assemble the video. Please retry.")


def build_video(slides, footer: str, clips: list[bytes] | None, out: Path) -> tuple[float, bool]:
    """Render and assemble. Returns (duration seconds, has_audio)."""
    with tempfile.TemporaryDirectory(prefix="boardom-video-") as tmp:
        work = Path(tmp)
        frames: list[tuple[Path, float]] = []
        audio = None
        if clips:
            try:
                audio = work / "narration.wav"
                lengths = join_wavs(clips, 0.6, audio)
            except (wave.Error, ValueError, EOFError) as exc:
                logger.warning("Narration unusable (%s); using captions", type(exc).__name__)
                audio = None
        if audio:
            for i, (slide, length) in enumerate(zip(slides, lengths, strict=True)):
                path = work / f"s{i}.png"
                render_slide(slide, footer, None, path)
                frames.append((path, length + 0.6))
        else:
            for i, slide in enumerate(slides):
                for j, caption in enumerate(caption_chunks(slide.narration)):
                    path = work / f"s{i}_{j}.png"
                    render_slide(slide, footer, caption, path)
                    seconds = max(2.5, len(caption.split()) / WORDS_PER_SECOND)
                    frames.append((path, seconds))
        assemble(frames, audio, out)
        return sum(s for _, s in frames), audio is not None


def make_video(provider, settings, video_id):
    def run(db, job, report) -> str:
        video = db.get(Video, video_id)
        video.status = "running"
        db.commit()
        try:
            workspace = db.get(Workspace, video.workspace_id)
            unit, version = published_unit(db, workspace.id, video.unit_id)
            report(0, 3)
            prompt = f"{course_header(workspace)}\n\n{notes_block(unit.title, version.markdown)}"
            draft, _ = provider.structured(INSTRUCTIONS, prompt, VideoScript, purpose="video")
            slides = [s for s in draft.slides if plain(s.title) and plain(s.narration)]
            slides = slides[:MAX_SLIDES]
            if not slides:
                raise JobFailed("The AI returned an empty video script. Please retry.")
            report(1, 3)
            clips = None
            if settings.video_tts:
                try:
                    clips = [provider.speech(plain(s.narration)) for s in slides]
                except AIError as exc:
                    logger.info("TTS unavailable (%s): silent video with captions", exc.code)
            report(2, 3)
            key = uuid4().hex
            out = video_path(settings, key)
            out.parent.mkdir(parents=True, exist_ok=True)
            footer = f"{workspace.title} · {unit.title}"
            duration, has_audio = build_video(slides, footer, clips, out)
            video.status, video.storage_key, video.has_audio = "ready", key, has_audio
            video.duration_seconds, video.slide_count = round(duration, 1), len(slides)
            video.message = None if has_audio else "Narration unavailable: captions shown."
            video.finished_at = utcnow()
            db.commit()
            report(3, 3)
            kind = "narrated" if has_audio else "silent, with captions"
            return f"Video ready ({len(slides)} slides, {duration:.0f} s, {kind})."
        except Exception as exc:
            db.rollback()
            failed = db.get(Video, video_id)
            if failed is not None:
                failed.status, failed.finished_at = "failed", utcnow()
                failed.message = (
                    exc.message
                    if isinstance(exc, AIError)
                    else str(exc)
                    if isinstance(exc, JobFailed)
                    else "Something went wrong. Please retry."
                )
                db.commit()
            raise

    return run


def remove_video_files(settings, keys) -> None:
    """Best effort after the database rows are gone (course or account deletion)."""
    for key in keys:
        try:
            video_path(settings, key).unlink(missing_ok=True)
        except (OSError, ValueError):
            logger.warning("Could not remove a video file")


def video_keys(db, workspace_ids) -> list[str]:
    from sqlalchemy import select

    return [
        key
        for key in db.scalars(
            select(Video.storage_key).where(Video.workspace_id.in_(workspace_ids))
        )
        if key
    ]
