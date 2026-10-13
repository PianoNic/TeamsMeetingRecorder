"""What ends up in the recording file: format and sample rate.

parec is faked with a pipe of known samples, so the tests can read the file
back and compare it sample by sample. The sink test only looks at the pactl
command line.

Run: python -m pytest tests/
"""

import io
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pytest
import soundfile as sf
from pydantic import ValidationError

from app import bot as bot_module
from app import recorder as recorder_module
from app.bot import TeamsBot
from app.config import Settings
from app.recorder import AudioRecorder

RATE = 48000


def _speech_like(channels: int, seconds: float = 2.0) -> np.ndarray:
    """A few tones with a slow envelope: compressible like real speech, not like noise."""
    t = np.arange(int(RATE * seconds)) / RATE
    signal = (np.sin(2 * np.pi * 220 * t) + 0.5 * np.sin(2 * np.pi * 660 * t)) * (0.5 + 0.5 * np.sin(2 * np.pi * 2 * t))
    mono = (signal * 8000).astype(np.int16)
    return np.repeat(mono[:, None], channels, axis=1)


class FakeParec:
    """Stands in for `parec`: hands out the given samples, then EOF."""

    def __init__(self, samples: np.ndarray):
        self.stdout = io.BytesIO(samples.tobytes())
        self.cmd = None

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


def _record(tmp_path, monkeypatch, file_format):
    samples = _speech_like(2)
    fake = FakeParec(samples)

    def popen(cmd, **kwargs):
        fake.cmd = cmd
        return fake

    monkeypatch.setattr(recorder_module.subprocess, "Popen", popen)
    monkeypatch.setattr(AudioRecorder, "_log_available_sources", lambda self: None)

    out = tmp_path / f"rec.{file_format}"
    rec = AudioRecorder(str(out), monitor_name="sink.monitor", file_format=file_format)
    rec.start()
    rec.recording_thread.join(timeout=10)
    rec.is_recording = False
    return out, samples, fake.cmd


@pytest.mark.parametrize("file_format", ["wav", "flac"])
def test_recording_holds_exactly_the_samples_parec_delivered(tmp_path, monkeypatch, file_format):
    out, samples, cmd = _record(tmp_path, monkeypatch, file_format)

    read, rate = sf.read(str(out), dtype="int16", always_2d=True)

    assert sf.info(str(out)).format == file_format.upper()
    assert rate == RATE
    assert read.shape == samples.shape
    assert np.array_equal(read, samples)  # lossless, bit for bit
    assert "--channels=2" in cmd
    assert f"--rate={RATE}" in cmd


def test_flac_is_far_smaller_than_wav_for_the_same_audio(tmp_path, monkeypatch):
    wav, _, _ = _record(tmp_path, monkeypatch, "wav")
    flac, _, _ = _record(tmp_path, monkeypatch, "flac")

    assert flac.stat().st_size < wav.stat().st_size / 2


def test_default_keeps_the_old_wav_recording():
    assert Settings(_env_file=None).recording_format == "wav"


def test_unknown_format_is_refused():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, recording_format="mp3")


def test_sink_runs_at_the_recording_rate(monkeypatch):
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="42\n", stderr="")

    monkeypatch.setattr(bot_module.subprocess, "run", run)

    TeamsBot("https://teams.microsoft.com/l/meetup-join/x", "Bot")._create_null_sink("rec_sink", "Recorder")

    cmd = calls[0]
    assert "module-null-sink" in cmd
    assert f"rate={RATE}" in cmd
    assert "channels=2" in cmd
