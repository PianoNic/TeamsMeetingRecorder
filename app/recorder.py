"""Audio recording module using sounddevice and PulseAudio."""

import logging
import os
import threading
import time
from datetime import datetime
from typing import Optional
import sounddevice as sd
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
        self.audio_data = []

        logger.info(f"Audio recorder initialized: {output_file}")

    def _log_available_devices(self):
        """Log available audio devices for debugging."""
        try:
            devices = sd.query_devices()
            msg = "Available audio devices:\n"
            for idx, device in enumerate(devices):
                msg += f"  [{idx}] {device['name']} - Inputs: {device['max_input_channels']}\n"
            msg += f"Recording from: {self.monitor_name}"
            logger.info(msg)
        except Exception as e:
            logger.error(f"Error querying audio devices: {e}")

    def _record_audio(self):
        """Internal method to record audio in a separate thread."""
    
        # Set PULSE_SOURCE environment variable to route audio from the session-specific monitor
        os.environ["PULSE_SOURCE"] = self.monitor_name
        logger.info(f"Recording from PulseAudio monitor: {self.monitor_name}")
        
        # Log available devices at debug level
        self._log_available_devices()

        logger.info(f"Starting audio recording: {self.sample_rate}Hz, {self.channels} channels")

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

            # Use device=None to let PulseAudio use PULSE_SOURCE environment variable
            with sd.InputStream(
                device=None,
                channels=self.channels,
                samplerate=self.sample_rate,
                callback=callback
            ):
                logger.info("Audio stream started successfully")

                # Record until stopped
                while self.is_recording:
                    time.sleep(0.1)

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