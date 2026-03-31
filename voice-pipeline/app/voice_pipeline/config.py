from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceConfig:
    log_level: str = os.getenv("VOICE_LOG_LEVEL", "INFO").upper()
    debug_logging: bool = os.getenv("VOICE_DEBUG_LOGGING", "false").lower() in {"1", "true", "yes", "on"}

    sample_rate: int = int(os.getenv("AUDIO_SAMPLE_RATE", "16000"))
    channels: int = int(os.getenv("AUDIO_CHANNELS", "1"))
    mic_device: str = os.getenv("AUDIO_MIC_DEVICE", "")
    output_device: str = os.getenv("AUDIO_OUTPUT_DEVICE", "")

    wake_threshold: float = float(os.getenv("WAKE_WORD_THRESHOLD", "0.5"))
    wake_event_cooldown_seconds: float = float(os.getenv("WAKE_EVENT_COOLDOWN_SECONDS", "2.0"))
    wake_model_name: str = os.getenv("WAKEWORD_MODEL", "hey_jarvis")
    wake_model_path: str = os.getenv("WAKEWORD_MODEL_PATH", "").strip()

    silence_timeout_seconds: float = float(os.getenv("AUDIO_SILENCE_TIMEOUT_SECONDS", "1.2"))
    max_recording_duration_seconds: float = float(os.getenv("AUDIO_MAX_RECORDING_DURATION_SECONDS", "7.0"))
    min_voice_energy: int = int(os.getenv("AUDIO_MIN_VOICE_ENERGY", "400"))

    whisper_mode: str = os.getenv("WHISPER_BACKEND", "hailo_local_cmd").lower()
    whisper_language: str = os.getenv("WHISPER_LANGUAGE", "de")
    hailo_apps_dir: str = os.getenv("HAILO_APPS_DIR", "/home/siddy/workspace/hailo-apps")
    hailo_python: str = os.getenv("HAILO_VENV_PYTHON", "/home/siddy/workspace/hailo-apps/venv_hailo_apps/bin/python")
    hailo_whisper_cmd: str = os.getenv(
        "HAILO_WHISPER_CMD",
        "cd {hailo_apps_dir} && source setup_env.sh && {hailo_python} -m hailo_apps.python.gen_ai_apps.simple_whisper_chat.simple_whisper_chat --audio-file {audio_path} --language {language}",
    )
    hailo_whisper_timeout: int = int(os.getenv("HAILO_WHISPER_CMD_TIMEOUT", "120"))

    llm_api_endpoint: str = os.getenv("LLM_API_ENDPOINT", "http://localhost:8000/api/chat")
    llm_model_name: str = os.getenv("LLM_MODEL_NAME", "hailo-llama")
    llm_timeout_seconds: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "25"))
    llm_retries: int = int(os.getenv("LLM_RETRIES", "1"))

    tts_voice_model: str = os.getenv("TTS_VOICE", "de_DE-thorsten-high.onnx")
    tts_voice_config: str = os.getenv("TTS_VOICE_CONFIG", "")
    tts_output_gain: float = float(os.getenv("TTS_OUTPUT_GAIN", "1.0"))

    playback_cmd: str = os.getenv("PLAYBACK_CMD", "aplay")
    device_refresh_seconds: int = int(os.getenv("AUDIO_DEVICE_REFRESH_SECONDS", "30"))


def load_config() -> VoiceConfig:
    return VoiceConfig()
