from app import stt_whisper


def test_create_transcriber_hf(monkeypatch):
    monkeypatch.setenv("WHISPER_MODE", "hf_local")
    transcriber = stt_whisper.create_transcriber()
    assert isinstance(transcriber, stt_whisper.WhisperHFTranscriber)


def test_create_transcriber_hailo_mode(monkeypatch):
    monkeypatch.setenv("WHISPER_MODE", "hailo_local")

    sentinel = object()

    def _fake_hailo():
        return sentinel

    monkeypatch.setattr(stt_whisper, "WhisperHailoTranscriber", _fake_hailo)
    transcriber = stt_whisper.create_transcriber()
    assert transcriber is sentinel


def test_create_transcriber_auto_fallback(monkeypatch):
    monkeypatch.setenv("WHISPER_MODE", "auto")

    def _broken_hailo():
        raise RuntimeError("hailo unavailable")

    sentinel = object()

    def _fake_hf():
        return sentinel

    monkeypatch.setattr(stt_whisper, "WhisperHailoTranscriber", _broken_hailo)
    monkeypatch.setattr(stt_whisper, "WhisperHFTranscriber", _fake_hf)

    transcriber = stt_whisper.create_transcriber()
    assert transcriber is sentinel
