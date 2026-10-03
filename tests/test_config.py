from app.config import Config, DEFAULTS


def test_defaults_load_to_valid_config():
    config = Config(**DEFAULTS)
    assert config.hotkey == ["ctrl", "space"]
    assert config.auto_paste is False


def test_history_keeps_only_the_five_newest_entries(monkeypatch):
    config = Config(**DEFAULTS)
    monkeypatch.setattr(config, "save", lambda: None)
    for number in range(6):
        config.add_recent_transcription(f"text {number}")
    assert config.recent_transcriptions == ["text 5", "text 4", "text 3", "text 2", "text 1"]
