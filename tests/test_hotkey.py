from app.hotkey import PushToTalkHotkey
from app.hotkey import VK_CONTROL, VK_SPACE


def test_initial_hotkey_is_not_active():
    hotkey = PushToTalkHotkey(lambda: None, lambda: None)
    assert hotkey._active is False


def test_ctrl_space_emits_exactly_one_press_and_release():
    import time
    events = []
    hotkey = PushToTalkHotkey(lambda: events.append("press"), lambda: events.append("release"))
    hotkey._handle_key_event(VK_CONTROL, True)
    hotkey._handle_key_event(VK_SPACE, True)
    hotkey._handle_key_event(VK_SPACE, True)  # autorepeat
    time.sleep(0.36)  # Hold mode (> 350ms)
    hotkey._handle_key_event(VK_SPACE, False)
    hotkey._handle_key_event(VK_CONTROL, False)
    assert events == ["press", "release"]


def test_ctrl_space_tap_latches_and_second_tap_stops():
    events = []
    hotkey = PushToTalkHotkey(lambda: events.append("press"), lambda: events.append("release"))
    # First quick tap (<350ms): latches recording ON
    hotkey._handle_key_event(VK_CONTROL, True)
    hotkey._handle_key_event(VK_SPACE, True)
    hotkey._handle_key_event(VK_SPACE, False)
    hotkey._handle_key_event(VK_CONTROL, False)
    assert hotkey._latched is True
    assert events == ["press"]

    # Second tap: stops recording and releases
    hotkey._handle_key_event(VK_CONTROL, True)
    hotkey._handle_key_event(VK_SPACE, True)
    assert events == ["press", "release"]


def test_space_is_identified_as_part_of_an_active_hotkey():
    hotkey = PushToTalkHotkey(lambda: None, lambda: None)
    hotkey._handle_key_event(VK_CONTROL, True)
    assert hotkey._ctrl is True
    hotkey._handle_key_event(VK_SPACE, True)
    assert hotkey._space is True
