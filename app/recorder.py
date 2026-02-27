"""Audio recording module using parec (PulseAudio) and soundfile."""

import logging
import subprocess
import threading
from datetime import datetime
from typing import Optional
import soundfile as sf
import numpy as np

from app.config import settings, DEFAULT_SAMPLE_RATE, DEFAULT_CHANNELS, PULSEAUDIO_MONITOR_NAME, PULSEAUDIO_SINK_NAME

logger = logging.getLogger(__name__)

class AudioRecorder:
    """Records audio from a PulseAudio virtual sink monitor."""

    def __init__(self, output_file: str, monitor_name: Optional[str] = None):
        """
        Initialize the audio recorder.

        Args:
            output_file: Path to save the recording
            monitor_name: Specific PulseAudio monitor to record from (optional)
        """
        self.output_file = output_file
        self.monitor_name = monitor_name
        self.sample_rate = DEFAULT_SAMPLE_RATE
        self.channels = DEFAULT_CHANNELS

        self.is_recording = False
        self.recording_thread: Optional[threading.Thread] = None
        self.start_time: Optional[datetime] = None
        self._parec_process: Optional[subprocess.Popen] = None

        logger.info(f"Audio recorder initialized: {output_file}")

    def _log_available_sources(self):
        """Log available PulseAudio sources for debugging."""
        try:
            result = subprocess.run(
                ['pactl', 'list', 'short', 'sources'],
                capture_output=True, text=True
            )
            logger.info(f"Available PulseAudio sources:\n{result.stdout.strip()}")
            logger.info(f"Recording from: {self.monitor_name}")
        except Exception as e:
            logger.error(f"Error querying PulseAudio sources: {e}")

    def _record_audio(self):
        """Internal method to record audio in a separate thread."""
        if not self.monitor_name:
            raise ValueError("monitor_name is required for recording")

        logger.info(f"Recording from PulseAudio monitor: {self.monitor_name}")
        self._log_available_sources()
        logger.info(f"Starting audio recording: {self.sample_rate}Hz, {self.channels} channels")

        # parec reads directly from the named PulseAudio source — no shared env vars,
        # so multiple concurrent sessions each get their own isolated subprocess.
        cmd = [
            'parec',
            f'--device={self.monitor_name}',
            '--format=s16le',
            f'--rate={self.sample_rate}',
            f'--channels={self.channels}',
        ]

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        self._parec_process = process

        logger.info("Audio stream started successfully")

        bytes_per_sample = 2  # s16le = 2 bytes
        chunk_frames = 4096
        chunk_bytes = chunk_frames * self.channels * bytes_per_sample

        try:
            with sf.SoundFile(
                self.output_file,
                mode='w',
                samplerate=self.sample_rate,
                channels=self.channels,
                subtype='PCM_16'
            ) as wav_file:
                while self.is_recording:
                    data = process.stdout.read(chunk_bytes)
                    if not data:
                        break
                    samples = np.frombuffer(data, dtype='int16').reshape(-1, self.channels)
                    wav_file.write(samples)
        finally:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
            self._parec_process = None

        logger.info(f"Recording saved to: {self.output_file}")

    def start(self):
        """Start recording audio in a background thread."""
        if self.is_recording:
            logger.warning("Recording already in progress")
            return

        self.is_recording = True
        self.start_time = datetime.utcnow()

        self.recording_thread = threading.Thread(target=self._record_audio, daemon=True)
        self.recording_thread.start()

        logger.info("Audio recording started")

    def stop(self):
        """Stop the audio recording."""
        if not self.is_recording:
            logger.warning("No recording in progress")
            return

        logger.info("Stopping audio recording")
        self.is_recording = False

        # Terminate parec so the recording thread's stdout.read() unblocks immediately.
        if self._parec_process:
            self._parec_process.terminate()

        if self.recording_thread:
            self.recording_thread.join(timeout=5)

        logger.info("Audio recording stopped")

    def get_duration(self) -> Optional[float]:
        """
        Get the current recording duration in seconds.

        Returns:
            Duration in seconds or None if not recording
        """
        if not self.start_time:
            return None

        if self.is_recording:
            return (datetime.utcnow() - self.start_time).total_seconds()
        else:
            try:
                info = sf.info(self.output_file)
                return info.duration
            except Exception:
                return None

    def is_active(self) -> bool:
        """Check if recording is currently active."""
        return self.is_recording


# Utility function to setup PulseAudio virtual sink
def setup_virtual_audio_sink():
    """
    Setup a PulseAudio virtual sink for capturing browser audio.

    This should be called during container initialization.
    """
    try:
        logger.info("Setting up PulseAudio virtual sink")

        cmd = [
            "pactl", "load-module", "module-null-sink",
            f"sink_name={PULSEAUDIO_SINK_NAME}",
            f"sink_properties=device.description='Teams_Virtual_Audio_Sink'"
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            logger.info(f"Virtual sink created: {PULSEAUDIO_SINK_NAME}")
            logger.info(f"Monitor available at: {PULSEAUDIO_MONITOR_NAME}")
            return True
        else:
            logger.error(f"Error creating virtual sink: {result.stderr}")
            return False

    except Exception as e:
        logger.error(f"Exception setting up virtual sink: {e}")
        return False


def list_audio_devices():
    """List all available PulseAudio sources (for debugging)."""
    try:
        print("\n=== Available PulseAudio Sources ===")
        result = subprocess.run(
            ['pactl', 'list', 'short', 'sources'],
            capture_output=True, text=True
        )
        print(result.stdout)
    except Exception as e:
        print(f"Error listing sources: {e}")
