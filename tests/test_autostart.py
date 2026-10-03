from app import autostart


def test_development_launch_command_includes_python_and_entry_point(monkeypatch):
    monkeypatch.setattr(autostart.sys, "frozen", False, raising=False)
    command = autostart.launch_command()
    assert command.startswith('"')
    assert 'main.py"' in command


def test_frozen_launch_command_uses_executable(monkeypatch):
    monkeypatch.setattr(autostart.sys, "frozen", True, raising=False)
    monkeypatch.setattr(autostart.sys, "executable", r"C:\\Apps\\VoiceInput.exe")
    assert autostart.launch_command() == '"C:\\Apps\\VoiceInput.exe"'
