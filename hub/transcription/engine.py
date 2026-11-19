"""Enregistrement micro (sounddevice) et transcription locale (faster-whisper)."""
from __future__ import annotations

import threading
import wave
from pathlib import Path

import numpy as np

from hub.storage import data_dir

SAMPLE_RATE = 16000
MODEL_SIZE = "small"  # bon compromis qualité/vitesse sur CPU, ~460 Mo, téléchargé au 1er usage


class Recorder:
    def __init__(self):
        self._frames: list[np.ndarray] = []
        self._stream = None
        self._lock = threading.Lock()
        self.level = 0.0

    def _cb(self, indata, frames, time_info, status):
        with self._lock:
            self._frames.append(indata.copy())
        self.level = float(np.abs(indata).max()) if len(indata) else 0.0

    def start(self):
        import sounddevice as sd
        self._frames = []
        self._stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                                      callback=self._cb)
        self._stream.start()

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def elapsed(self) -> float:
        with self._lock:
            return sum(len(f) for f in self._frames) / SAMPLE_RATE

    def stop(self, path: Path) -> float:
        """Arrête et écrit un WAV 16 kHz mono 16 bits. Retourne la durée (s)."""
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        with self._lock:
            audio = np.concatenate(self._frames) if self._frames else np.zeros((0, 1), np.float32)
            self._frames = []
        write_wav(path, audio)
        return len(audio) / SAMPLE_RATE


def write_wav(path: Path, audio: np.ndarray) -> None:
    pcm = (np.clip(audio.reshape(-1), -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, "<i2").astype(np.float32) / 32768.0


def audio_dir() -> Path:
    p = data_dir() / "audio"
    p.mkdir(exist_ok=True)
    return p


_model = None
_model_lock = threading.Lock()


def get_model():
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            _model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8",
                                  download_root=str(data_dir() / "models"))
        return _model


def transcribe(path: Path, language: str | None = None, progress=None) -> tuple[str, str]:
    """Retourne (texte, langue détectée). `progress(fraction)` optionnel."""
    audio = read_wav(path)
    duration = max(len(audio) / SAMPLE_RATE, 0.01)
    segments, info = get_model().transcribe(audio, language=language or None, vad_filter=True,
                                            beam_size=5)
    parts = []
    for seg in segments:
        parts.append(seg.text.strip())
        if progress:
            progress(min(seg.end / duration, 1.0))
    return "\n".join(p for p in parts if p), info.language
