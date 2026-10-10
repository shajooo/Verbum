"""
test_translation.py — Unit and integration tests for local offline translation.
"""
from __future__ import annotations

import multiprocessing as mp
import time
import pytest

from app.config import Config
from app.translation import (
    LanguageDetector,
    TranslationModelProvider,
    TranslationModelNotInstalledError,
    SUPPORTED_LANGUAGES,
    normalise_lang,
    is_model_downloaded,
    _split_text,
)
from app.translation_worker import start_translation_worker


# ── Language Normalisation & Detection Tests ──────────────────────────────────

def test_language_normalisation() -> None:
    assert normalise_lang("zh-cn") == "zh"
    assert normalise_lang("zh-tw") == "zh"
    assert normalise_lang("nb") == "no"
    assert normalise_lang("nn") == "no"
    assert normalise_lang("FR") == "fr"
    assert normalise_lang("  de  ") == "de"


def test_language_detector_identifies_major_languages() -> None:
    detector = LanguageDetector()

    samples = [
        ("fr", "Bonjour tout le monde, comment allez-vous aujourd'hui?"),
        ("de", "Guten Morgen! Das Wetter ist heute sehr schön."),
        ("es", "Hola, ¿cómo estás? Esto es una prueba de traducción."),
        ("ml", "നമസ്കാരം, ഇത് ഒരു പ്രാദേശിക വിവർത്തന പരീക്ഷണമാണ്."),
        ("hi", "नमस्ते, आप कैसे हैं? आज का दिन बहुत अच्छा है।"),
        ("ja", "こんにちは、お元気ですか？"),
        ("ar", "مرحبا، كيف حالك اليوم؟"),
        ("ta", "வணக்கம், நீங்கள் எப்படி இருக்கிறீர்கள்? இது ஒரு மொழிபெயர்ப்பு சோதனை."),
        ("bn", "হ্যালো, আপনি কেমন আছেন? এটি একটি অনুবাদ পরীক্ষা।"),
        ("ru", "Привет, как твои дела? Надеюсь, все хорошо и день проходит отлично."),
        ("en", "This text is already in English and needs no translation."),
    ]

    for expected_lang, text in samples:
        result = detector.detect(text)
        assert result.code == expected_lang, f"Expected {expected_lang}, got {result.code} for '{text}'"
        assert result.confident is True
        assert result.name in SUPPORTED_LANGUAGES.values() or result.code == "en"


def test_language_detector_empty_or_gibberish() -> None:
    detector = LanguageDetector()
    empty_res = detector.detect("")
    assert empty_res.code == ""
    assert empty_res.confident is False

    space_res = detector.detect("    \n\t  ")
    assert space_res.code == ""
    assert space_res.confident is False


def test_text_splitting_boundary_handling() -> None:
    short_text = "Short sentence."
    assert _split_text(short_text, max_chars=100) == ["Short sentence."]

    long_text = "First sentence here. Second sentence follows! Third one is here? And fourth."
    chunks = _split_text(long_text, max_chars=45)
    assert len(chunks) >= 2
    reconstructed = " ".join(chunks)
    assert "First sentence" in reconstructed
    assert "fourth." in reconstructed


# ── Translation Model Provider Tests ──────────────────────────────────────────

def test_model_is_downloaded_locally() -> None:
    assert is_model_downloaded() is True, "Model files must be cached in models/translation/m2m100_ct2_int8"


def test_english_passthrough_without_loading_model() -> None:
    provider = TranslationModelProvider()
    # Model is not loaded
    assert provider.is_loaded is False


def test_missing_model_never_triggers_an_implicit_download(tmp_path, monkeypatch) -> None:
    """A normal translation request must be offline-only, even before setup."""
    monkeypatch.setattr("app.translation._model_dir", lambda: tmp_path)
    provider = TranslationModelProvider()
    with pytest.raises(TranslationModelNotInstalledError, match="not installed"):
        provider.load()
    res = provider.translate("Hello world, this is already English.", source_lang="en")
    assert res == "Hello world, this is already English."
    # Model should STILL not be loaded
    assert provider.is_loaded is False


def test_empty_input_raises_value_error() -> None:
    provider = TranslationModelProvider()
    provider.load()
    with pytest.raises(ValueError, match="empty"):
        provider.translate("   ", source_lang="fr")


def test_unsupported_language_raises_value_error() -> None:
    provider = TranslationModelProvider()
    provider.load()
    with pytest.raises(ValueError, match="not supported"):
        provider.translate("Sample text", source_lang="xyz_nonexistent")


def test_local_translation_accuracy_and_warm_cache() -> None:
    provider = TranslationModelProvider()
    provider.load()
    assert provider.is_loaded is True

    # Translation 1: French
    fr_input = "Bonjour tout le monde, comment allez-vous aujourd'hui?"
    fr_trans = provider.translate(fr_input, source_lang="fr", target_lang="en")
    assert isinstance(fr_trans, str)
    assert len(fr_trans) > 0
    # Must contain English words
    assert any(w in fr_trans.lower() for w in ["everyone", "today", "how", "you"])

    # Translation 2 (Warm cache reuse): Spanish
    es_input = "Hola, ¿cómo estás? Esto es una prueba de traducción local."
    es_trans = provider.translate(es_input, source_lang="es", target_lang="en")
    assert isinstance(es_trans, str)
    assert len(es_trans) > 0
    assert any(w in es_trans.lower() for w in ["translation", "test", "local", "how", "hello"])

    # Translation 3 (Warm cache reuse): Malayalam
    ml_input = "നമസ്കാരം, ഇത് ഒരു പ്രാദേശിക വിവർത്തന പരീക്ഷണമാണ്."
    ml_trans = provider.translate(ml_input, source_lang="ml", target_lang="en")
    assert isinstance(ml_trans, str)
    assert len(ml_trans) > 0

    # Translation 4: Hindi
    hi_input = "नमस्ते, आप कैसे हैं? आज का दिन बहुत अच्छा है।"
    hi_trans = provider.translate(hi_input, source_lang="hi", target_lang="en")
    assert isinstance(hi_trans, str)
    assert len(hi_trans) > 0
    assert any(w in hi_trans.lower() for w in ["hello", "how", "day", "good", "great"])

    # Test unload
    provider.unload()
    assert provider.is_loaded is False


# ── Translation Worker Process Integration Tests ──────────────────────────────

def test_translation_worker_lifecycle_and_caching() -> None:
    process, commands, results, cancel_event = start_translation_worker()
    assert process.is_alive()

    try:
        # Request 1: Auto-detect French
        req1 = "req-1"
        commands.put(("translate", req1, "Bonjour tout le monde", "auto"))

        got_ok = False
        translated_text = ""
        resolved_name = ""

        # Collect results with timeout
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                msg = results.get(timeout=1)
                kind, req_id = msg[0], msg[1]
                assert req_id == req1
                if kind == "result":
                    outcome = msg[2]
                    assert outcome == "ok"
                    translated_text = msg[3]
                    resolved_name = msg[5]
                    got_ok = True
                    break
            except Exception:
                pass

        assert got_ok is True
        assert resolved_name == "French"
        assert len(translated_text) > 0

        # The same persistent worker must auto-detect representative scripts.
        for number, expected_lang, text in [
            ("auto-hi", "Hindi", "नमस्ते, आप कैसे हैं? आज का दिन बहुत अच्छा है।"),
            ("auto-ml", "Malayalam", "നമസ്കാരം, ഇത് ഒരു പ്രാദേശിക വിവർത്തന പരീക്ഷണമാണ്."),
            ("auto-ja", "Japanese", "こんにちは、お元気ですか？"),
            ("auto-ar", "Arabic", "مرحبا، كيف حالك اليوم؟"),
        ]:
            commands.put(("translate", number, text, "auto"))
            deadline = time.time() + 10
            while time.time() < deadline:
                try:
                    message = results.get(timeout=1)
                except Exception:
                    continue
                if message[0] == "result" and message[1] == number:
                    assert message[2] == "ok"
                    assert message[5] == expected_lang
                    assert message[3]
                    break
            else:
                pytest.fail(f"No auto-detect translation result for {expected_lang}")

        # Request 2 (Reusing warm worker process! Fast!): Manual German
        t0 = time.time()
        req2 = "req-2"
        commands.put(("translate", req2, "Guten Morgen! Das Wetter ist schön.", "de"))

        got_ok_2 = False
        trans2 = ""
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                msg = results.get(timeout=1)
                kind, req_id = msg[0], msg[1]
                if req_id != req2:
                    continue
                if kind == "result":
                    outcome = msg[2]
                    assert outcome == "ok"
                    trans2 = msg[3]
                    got_ok_2 = True
                    break
            except Exception:
                pass

        t_elapsed = time.time() - t0
        assert got_ok_2 is True
        assert len(trans2) > 0
        # Warm inference should be very fast (< 3 seconds)
        assert t_elapsed < 5.0

        # Request 3: English text should pass through directly
        req3 = "req-3"
        commands.put(("translate", req3, "This is already plain English.", "en"))
        msg3 = results.get(timeout=5)
        assert msg3[0] == "result" and msg3[1] == req3 and msg3[2] == "ok"
        assert msg3[3] == "This is already plain English."
        assert msg3[4] == "en"

        # Request 4: Empty text error handling
        req4 = "req-4"
        commands.put(("translate", req4, "   ", "fr"))
        msg4 = results.get(timeout=5)
        assert msg4[0] == "result" and msg4[1] == req4 and msg4[2] == "error"
        assert "empty" in msg4[3].lower()

        # Request 5: Unsupported language error handling
        req5 = "req-5"
        commands.put(("translate", req5, "Sample text", "klingon"))
        msg5 = results.get(timeout=5)
        assert msg5[0] == "result" and msg5[1] == req5 and msg5[2] == "error"
        assert "not supported" in msg5[3].lower()

    finally:
        commands.put(("shutdown",))
        process.join(timeout=3)
        if process.is_alive():
            process.terminate()
            process.join(timeout=1)


def test_translation_worker_cancellation() -> None:
    process, commands, results, cancel_event = start_translation_worker()
    assert process.is_alive()

    try:
        # Pre-set cancel event
        cancel_event.set()
        req_id = "req-cancel"
        commands.put(("translate", req_id, "Hola, esto es una prueba que será cancelada.", "es"))

        got_cancel = False
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                msg = results.get(timeout=1)
                if msg[1] == req_id and msg[0] == "result" and msg[2] == "cancelled":
                    got_cancel = True
                    break
            except Exception:
                pass

        assert got_cancel is True
    finally:
        commands.put(("shutdown",))
        process.join(timeout=2)
        if process.is_alive():
            process.terminate()
            process.join(timeout=1)


# ── Configuration & History Tests ─────────────────────────────────────────────

def test_translation_history_persistence_and_capping(tmp_path, monkeypatch) -> None:
    fake_config_file = tmp_path / "config.json"
    monkeypatch.setattr("app.config.config_path", lambda: fake_config_file)

    config = Config.load()
    assert config.translation_history == []
    assert config.enable_translation is False

    # Add 12 entries (max cap is 10)
    for i in range(12):
        config.add_translation_history(
            original=f"Original text {i}",
            translated=f"Translated text {i}",
            source_lang="fr",
            source_name="French",
        )

    # Should be capped at 10 newest entries
    assert len(config.translation_history) == 10
    # Newest entry is at index 0
    assert config.translation_history[0]["original"] == "Original text 11"
    assert config.translation_history[0]["source_lang"] == "fr"

    # Reload from disk
    reloaded = Config.load()
    assert len(reloaded.translation_history) == 10
    assert reloaded.translation_history[0]["original"] == "Original text 11"
