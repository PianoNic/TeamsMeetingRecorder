"""Audio recording module using sounddevice and PulseAudio."""

import logging
import threading
import time
from datetime import datetime
from typing import Optional
import sounddevice as sd
import soundfile as sf
import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)


class AudioRecorder:
    """Records audio from a PulseAudio virtual sink monitor."""

    def __init__(self, output_file: str, duration: Optional[float] = None, monitor_name: Optional[str] = None):
        """
        Initialize the audio recorder.

        Args:
            output_file: Path to save the recording
            duration: Maximum recording duration in seconds (None for unlimited)
            monitor_name: Specific PulseAudio monitor to record from (optional)
        """
        self.output_file = output_file
        self.duration = duration
        self.monitor_name = monitor_name
        self.sample_rate = settings.default_sample_rate
        self.channels = settings.default_channels

        self.is_recording = False
        self.recording_thread: Optional[threading.Thread] = None
        self.start_time: Optional[datetime] = None
        self.audio_data = []

        logger.info(f"Audio recorder initialized: {output_file}")

    def _get_pulseaudio_device(self) -> Optional[int]:
        """
        Find the PulseAudio monitor device for recording.

        Returns:
            Device index or None if not found
        """
        try:
            devices = sd.query_devices()
            logger.info("Available audio devices:")

            for idx, device in enumerate(devices):
                logger.info(f"  [{idx}] {device['name']} - Inputs: {device['max_input_channels']}")

                # If a specific monitor name was provided, look for it
                if self.monitor_name and self.monitor_name in device['name']:
                    logger.info(f"Found specified monitor device '{self.monitor_name}' at index {idx}")
                    return idx

                # Fallback: look for the default virtual sink monitor
                if not self.monitor_name and settings.pulseaudio_monitor_name in device['name']:
                    logger.info(f"Found PulseAudio monitor device at index {idx}")
                    return idx

                # Also check for alternative monitor naming
                if not self.monitor_name and 'monitor' in device['name'].lower() and device['max_input_channels'] > 0:
                    logger.info(f"Found alternative monitor device at index {idx}: {device['name']}")
                    return idx

            logger.warning("Could not find PulseAudio monitor device, using default")
            return None

        except Exception as e:
            logger.error(f"Error querying audio devices: {e}")
            return None

    def _record_audio(self):
        """Internal method to record audio in a separate thread."""
        try:
            device_index = self._get_pulseaudio_device()

            logger.info(f"Starting audio recording: {self.sample_rate}Hz, {self.channels} channels")
            logger.info(f"Using device index: {device_index}")

            # Calculate duration in frames
            duration_frames = int(self.duration * self.sample_rate) if self.duration else None

            # Record audio
            with sf.SoundFile(
                self.output_file,
                mode='w',
                samplerate=self.sample_rate,
                channels=self.channels,
                subtype='PCM_24'
            ) as file:

                # Use a callback to continuously record
                def callback(indata, frames, time_info, status):
                    if status:
                        logger.warning(f"Audio callback status: {status}")
                    if self.is_recording:
                        file.write(indata)

                # Start recording stream
                with sd.InputStream(
                    device=device_index,
                    channels=self.channels,
                    samplerate=self.sample_rate,
                    callback=callback
                ):
                    logger.info("Audio stream started")

                    if self.duration:
                        # Record for specified duration
                        time.sleep(self.duration)
                    else:
                        # Record until stopped
                        while self.is_recording:
                            time.sleep(0.1)

            logger.info(f"Recording saved to: {self.output_file}")

        except Exception as e:
            logger.error(f"Error recording audio: {e}", exc_info=True)
            self.is_recording = False

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

        # Wait for recording thread to finish
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
            # Return total duration from the file
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
    import subprocess

    try:
        logger.info("Setting up PulseAudio virtual sink")

        # Load null sink module
        cmd = [
            "pactl", "load-module", "module-null-sink",
            f"sink_name={settings.pulseaudio_sink_name}",
            f"sink_properties=device.description='Teams_Virtual_Audio_Sink'"
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            logger.info(f"Virtual sink created: {settings.pulseaudio_sink_name}")
            logger.info(f"Monitor available at: {settings.pulseaudio_monitor_name}")
            return True
        else:
            logger.error(f"Error creating virtual sink: {result.stderr}")
            return False

    except Exception as e:
        logger.error(f"Exception setting up virtual sink: {e}")
        return False


def list_audio_devices():
    """List all available audio devices (for debugging)."""
    try:
        print("\n=== Available Audio Devices ===")
        devices = sd.query_devices()
        for idx, device in enumerate(devices):
            device_type = []
            if device['max_input_channels'] > 0:
                device_type.append('INPUT')
            if device['max_output_channels'] > 0:
                device_type.append('OUTPUT')

            print(f"[{idx}] {device['name']}")
            print(f"    Type: {', '.join(device_type)}")
            print(f"    Channels: IN={device['max_input_channels']}, OUT={device['max_output_channels']}")
            print(f"    Sample Rate: {device['default_samplerate']} Hz")
            print()

    except Exception as e:
        print(f"Error listing devices: {e}")
