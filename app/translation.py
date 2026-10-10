"""
translation.py — Local offline multilingual translation backend for Verbum.

Model:    facebook/m2m100_418M (quantized to CTranslate2 int8, MIT license)
Format:   local CTranslate2 int8 model cache (~490 MB)
Runtime:  ctranslate2 (MIT license, fast C++ inference engine)
Token:    sentencepiece (Apache-2.0, BPE tokenizer)
Detector: langdetect (Apache-2.0, lightweight local language identification)

Key Properties:
- 100% offline and private (no remote APIs, no cloud dependency)
- Broad language coverage (100 languages directly supported to English)
- Permissive MIT license (fully compatible with project license)
- Quantized int8 footprint (~490 MB); first-run latency depends on local hardware
- Fast lazy loading & model reuse while feature remains ON
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import sys
import uuid
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

# Hugging Face repository for CTranslate2 int8 quantized M2M100-418M
_CT2_MODEL_REPO = "gn64/M2M100_418M_CTranslate2"
_MODEL_FOLDER_NAME = "m2m100_ct2_int8"


def _model_dir() -> Path:
    """Return local directory where translation models are stored."""
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "VoiceInput"
    else:
        base = Path(__file__).resolve().parent.parent
    d = base / "models" / "translation"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Supported 100 Languages in M2M-100 ─────────────────────────────────────────
SUPPORTED_LANGUAGES: dict[str, str] = {
    "af": "Afrikaans",
    "am": "Amharic",
    "ar": "Arabic",
    "ast": "Asturian",
    "az": "Azerbaijani",
    "ba": "Bashkir",
    "be": "Belarusian",
    "bg": "Bulgarian",
    "bn": "Bengali",
    "br": "Breton",
    "bs": "Bosnian",
    "ca": "Catalan",
    "ceb": "Cebuano",
    "cs": "Czech",
    "cy": "Welsh",
    "da": "Danish",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "es": "Spanish",
    "et": "Estonian",
    "fa": "Persian",
    "ff": "Fulah",
    "fi": "Finnish",
    "fr": "French",
    "fy": "Western Frisian",
    "ga": "Irish",
    "gd": "Gaelic",
    "gl": "Galician",
    "gu": "Gujarati",
    "ha": "Hausa",
    "he": "Hebrew",
    "hi": "Hindi",
    "hr": "Croatian",
    "ht": "Haitian Creole",
    "hu": "Hungarian",
    "hy": "Armenian",
    "id": "Indonesian",
    "ig": "Igbo",
    "ilo": "Iloko",
    "is": "Icelandic",
    "it": "Italian",
    "ja": "Japanese",
    "jv": "Javanese",
    "ka": "Georgian",
    "kk": "Kazakh",
    "km": "Khmer",
    "kn": "Kannada",
    "ko": "Korean",
    "lb": "Luxembourgish",
    "lg": "Ganda",
    "ln": "Lingala",
    "lo": "Lao",
    "lt": "Lithuanian",
    "lv": "Latvian",
    "mg": "Malagasy",
    "mk": "Macedonian",
    "ml": "Malayalam",
    "mn": "Mongolian",
    "mr": "Marathi",
    "ms": "Malay",
    "my": "Burmese",
    "ne": "Nepali",
    "nl": "Dutch",
    "no": "Norwegian",
    "ns": "Northern Sotho",
    "oc": "Occitan",
    "or": "Oriya",
    "pa": "Panjabi",
    "pl": "Polish",
    "ps": "Pushto",
    "pt": "Portuguese",
    "ro": "Romanian",
    "ru": "Russian",
    "sd": "Sindhi",
    "si": "Sinhala",
    "sk": "Slovak",
    "sl": "Slovenian",
    "so": "Somali",
    "sq": "Albanian",
    "sr": "Serbian",
    "ss": "Swati",
    "su": "Sundanese",
    "sv": "Swedish",
    "sw": "Swahili",
    "ta": "Tamil",
    "th": "Thai",
    "tl": "Tagalog",
    "tn": "Tswana",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "ur": "Urdu",
    "uz": "Uzbek",
    "vi": "Vietnamese",
    "wo": "Wolof",
    "xh": "Xhosa",
    "yi": "Yiddish",
    "yo": "Yoruba",
    "zh": "Chinese",
    "zu": "Zulu",
}

# Normalise langdetect codes to M2M100 language codes
_LANG_NORM: dict[str, str] = {
    "zh-cn": "zh",
    "zh-tw": "zh",
    "nb": "no",
    "nn": "no",
    "war": "ceb",
}


def normalise_lang(code: str) -> str:
    code = code.lower().strip()
    return _LANG_NORM.get(code, code)


# ── Language Detection ────────────────────────────────────────────────────────

class DetectionResult:
    __slots__ = ("code", "name", "confident")

    def __init__(self, code: str, name: str, confident: bool) -> None:
        self.code = code
        self.name = name
        self.confident = confident

    def __repr__(self) -> str:
        return f"DetectionResult(code={self.code!r}, name={self.name!r}, confident={self.confident})"


class TranslationModelNotInstalledError(RuntimeError):
    """Raised when translation is requested before explicit local model setup."""


class TranslationModelValidationError(RuntimeError):
    """Raised when a local translation model is incomplete or cannot run."""


_REQUIRED_MODEL_FILES = (
    "model.bin", "config.json", "sentencepiece.bpe.model", "shared_vocabulary.json",
)


class _SilentTqdm:
    """A complete no-console tqdm substitute for a windowed application.

    ``snapshot_download`` uses more of tqdm's protocol than ``update``: it
    refreshes aggregate byte counters and sets descriptions at completion.
    Implementing those no-op members prevents the GUI build from either
    writing to its None-valued stderr or failing during progress aggregation.
    """

    def __init__(self, *args, **kwargs) -> None:
        self.n = 0
        self.total = kwargs.get("total")
        # Xet's aggregate progress reporter reads this tqdm attribute when it
        # calculates an optional transfer-rate label.
        self.format_dict = {"rate": None}

    def update(self, amount=1) -> None:
        self.n += amount

    def close(self) -> None:
        pass

    def refresh(self, *args, **kwargs) -> None:
        pass

    def set_description(self, *args, **kwargs) -> None:
        pass

    def set_description_str(self, *args, **kwargs) -> None:
        pass

    def set_postfix_str(self, *args, **kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        self.close()


def _validate_model_dir(model_path: Path, *, run_inference: bool = False) -> None:
    """Raise unless a complete, readable CTranslate2 M2M-100 model is present."""
    if not model_path.is_dir():
        raise TranslationModelValidationError("The translation model directory is missing.")
    missing = [name for name in _REQUIRED_MODEL_FILES if not (model_path / name).is_file()]
    if missing:
        raise TranslationModelValidationError(
            "The installed translation model is incomplete (missing: %s)." % ", ".join(missing)
        )
    try:
        for name in _REQUIRED_MODEL_FILES:
            with (model_path / name).open("rb") as stream:
                stream.read(1)
        if (model_path / "model.bin").stat().st_size < 1_000_000:
            raise TranslationModelValidationError("The installed model weights are invalid.")
    except OSError as exc:
        raise TranslationModelValidationError("The translation model files cannot be read.") from exc
    if not run_inference:
        return
    try:
        import ctranslate2  # type: ignore
        import sentencepiece as spm  # type: ignore
        tokenizer = spm.SentencePieceProcessor()
        if not tokenizer.Load(str(model_path / "sentencepiece.bpe.model")):
            raise RuntimeError("SentencePiece rejected the tokenizer file")
        translator = ctranslate2.Translator(
            str(model_path), device="cpu", inter_threads=1, intra_threads=1, compute_type="int8"
        )
        tokens = ["__hi__", *tokenizer.Encode("नमस्ते", out_type=str), "</s>"]
        outcome = translator.translate_batch([tokens], target_prefix=[["__en__"]], max_decoding_length=32)
        if not outcome or not outcome[0].hypotheses:
            raise RuntimeError("model returned no validation hypothesis")
    except Exception as exc:
        raise TranslationModelValidationError(
            "The downloaded translation model could not be initialized."
        ) from exc


class LanguageDetector:
    """Lightweight, 100% local language detector using langdetect."""

    _CONFIDENCE_THRESHOLD = 0.70

    def detect(self, text: str) -> DetectionResult:
        text = text.strip()
        if not text:
            return DetectionResult("", "Unknown", confident=False)
        try:
            from langdetect import detect_langs  # type: ignore
            results = detect_langs(text)
            if not results:
                return DetectionResult("", "Unknown", confident=False)
            top = results[0]
            code = normalise_lang(str(top.lang))
            prob = float(top.prob)
            name = SUPPORTED_LANGUAGES.get(code, code.upper())
            confident = prob >= self._CONFIDENCE_THRESHOLD
            log.info("Detected language=%s (%s), prob=%.2f, confident=%s", code, name, prob, confident)
            return DetectionResult(code=code, name=name, confident=confident)
        except Exception as exc:
            log.warning("Language detection failed: %s", exc)
            return DetectionResult("", "Unknown", confident=False)


# ── Translation Model Provider ────────────────────────────────────────────────

class TranslationModelProvider:
    """
    Manages the CTranslate2 M2M-100 multilingual translation model.
    Maintains loaded model in memory for fast repeated translations.
    """

    def __init__(self) -> None:
        self._translator = None
        self._sp = None
        self._model_path: Path | None = None

    def _get_model_path(self) -> Path:
        return _model_dir() / _MODEL_FOLDER_NAME

    def install(self, progress_cb: Callable[[str], None] | None = None) -> Path:
        """Explicitly download the one-time local model cache.

        ``load`` deliberately never calls this method: normal translation is
        offline-only and cannot start a network transfer on its own.
        """
        dest = self._get_model_path()
        # First validate an existing installation, including a tiny local CPU
        # inference. Presence of two filenames alone is not a ready model.
        if dest.exists():
            try:
                if progress_cb:
                    progress_cb("Verifying translation model...")
                _validate_model_dir(dest, run_inference=True)
                return dest
            except TranslationModelValidationError:
                log.warning("Existing translation model is invalid; replacing it", exc_info=True)

        # Keep download state separate from the active model. A working model
        # is never overwritten until the replacement has passed validation.
        staging = dest.parent / f".{_MODEL_FOLDER_NAME}.installing-{uuid.uuid4().hex}"
        backup: Path | None = None
        try:
            staging.mkdir(parents=True, exist_ok=False)
            if progress_cb:
                progress_cb("Downloading translation model... (one-time download, ~490 MB)")
            from huggingface_hub import snapshot_download  # type: ignore
            snapshot_download(
                repo_id=_CT2_MODEL_REPO,
                local_dir=str(staging),
                ignore_patterns=["*.md", "*.txt", "*.msgpack", ".git*"],
                tqdm_class=_SilentTqdm,
            )
            if progress_cb:
                progress_cb("Verifying translation model...")
            _validate_model_dir(staging, run_inference=True)
            if progress_cb:
                progress_cb("Activating translation model...")
            if dest.exists():
                backup = dest.parent / f".{_MODEL_FOLDER_NAME}.invalid-{uuid.uuid4().hex}"
                dest.replace(backup)
            staging.replace(dest)
            if backup:
                shutil.rmtree(backup, ignore_errors=True)
            return dest
        except Exception:
            if backup and backup.exists() and not dest.exists():
                backup.replace(dest)
            raise
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

        if progress_cb:
            progress_cb("Downloading translation model… (one-time download, ~490 MB)")

        log.info("Downloading M2M-100 CT2 model from Hugging Face: %s", _CT2_MODEL_REPO)
        from huggingface_hub import snapshot_download  # type: ignore
        downloaded = snapshot_download(
            repo_id=_CT2_MODEL_REPO,
            local_dir=str(dest),
            ignore_patterns=["*.md", "*.txt", "*.msgpack", ".git*"],
            # PyInstaller windowed builds deliberately have sys.stderr=None.
            # Default tqdm writes there and raises NoneType.write.
            tqdm_class=_SilentTqdm,
        )
        installed = Path(downloaded)
        _validate_model_dir(installed, run_inference=True)
        return installed

    def load(self, progress_cb: Callable[[str], None] | None = None, device: str = "auto") -> None:
        if self._translator is not None:
            return  # Model already warm in memory

        model_path = self._get_model_path()
        if not is_model_downloaded():
            raise TranslationModelNotInstalledError(
                "Translation model is not installed. Select Install model to set it up once."
            )
        _validate_model_dir(model_path)
        self._model_path = model_path

        if progress_cb:
            progress_cb("Loading translation model into memory…")

        import ctranslate2  # type: ignore
        import sentencepiece as spm  # type: ignore

        # Determine compute device with safe probing
        use_device = "cpu"
        if device == "auto" or device in ("cuda", "gpu"):
            if ctranslate2.get_cuda_device_count() > 0:
                use_device = "cuda"

        if use_device == "cuda":
            try:
                log.info("Testing CUDA translation runtime from %s...", model_path)
                test_trans = ctranslate2.Translator(
                    str(model_path),
                    device="cuda",
                    inter_threads=2,
                    intra_threads=4,
                    compute_type="int8",
                )
                # Probe inference to test if cuBLAS DLLs exist
                test_trans.translate_batch([["</s>"]])
                self._translator = test_trans
                log.info("CUDA translation acceleration verified active.")
            except Exception as exc:
                log.warning("CUDA initialization failed (%s); falling back to CPU int8", exc)
                use_device = "cpu"
                self._translator = None

        if self._translator is None:
            log.info("Loading CTranslate2 translator on CPU (compute_type=int8) from %s", model_path)
            self._translator = ctranslate2.Translator(
                str(model_path),
                device="cpu",
                inter_threads=2,
                intra_threads=4,
                compute_type="int8",
            )

        spm_path = model_path / "sentencepiece.bpe.model"
        self._sp = spm.SentencePieceProcessor()
        self._sp.Load(str(spm_path))

        log.info("Translation model loaded successfully (device=%s)", use_device)
        if progress_cb:
            progress_cb("Translation model ready.")

    def unload(self) -> None:
        """Release model and tokenizer from memory."""
        self._translator = None
        self._sp = None
        log.info("Translation model unloaded from memory.")

    @property
    def is_loaded(self) -> bool:
        return self._translator is not None

    def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str = "en",
        cancelled: Callable[[], bool] | None = None,
    ) -> str:
        """
        Translate text from source_lang to target_lang (default English).
        Splits into sentence chunks for long inputs.
        """
        text = text.strip()
        if not text:
            raise ValueError("Input text is empty.")

        src_code = normalise_lang(source_lang)
        tgt_code = normalise_lang(target_lang)

        # English to English returns immediately without requiring model in memory
        if src_code in ("en", "eng"):
            return text

        if self._translator is None or self._sp is None:
            raise RuntimeError("Translation model is not loaded.")

        if src_code not in SUPPORTED_LANGUAGES:
            raise ValueError(f"Language '{src_code}' is not supported by the translation model.")

        chunks = _split_text(text)
        translated_chunks: list[str] = []

        for chunk in chunks:
            if cancelled and cancelled():
                raise InterruptedError("Translation was cancelled.")
            if not chunk.strip():
                translated_chunks.append(chunk)
                continue
            translated_part = self._translate_chunk(chunk, src_code, tgt_code)
            translated_chunks.append(translated_part)

        return " ".join(translated_chunks)

    def _translate_chunk(self, chunk: str, src_lang: str, tgt_lang: str) -> str:
        assert self._sp is not None and self._translator is not None
        # M2M-100 encoding format: [__src__] + tokens + [</s>]
        raw_tokens = self._sp.Encode(chunk, out_type=str)
        src_tokens = [f"__{src_lang}__"] + raw_tokens + ["</s>"]

        # Decoding target prefix: [__tgt__]
        tgt_prefix = [[f"__{tgt_lang}__"]]

        try:
            results = self._translator.translate_batch(
                [src_tokens],
                target_prefix=tgt_prefix,
                max_decoding_length=512,
                beam_size=3,
            )
        except RuntimeError as exc:
            if "cublas" in str(exc).lower() or "cuda" in str(exc).lower():
                log.warning("CUDA execution error (%s); falling back to CPU int8", exc)
                import ctranslate2
                self._translator = ctranslate2.Translator(
                    str(self._model_path),
                    device="cpu",
                    inter_threads=2,
                    intra_threads=4,
                    compute_type="int8",
                )
                results = self._translator.translate_batch(
                    [src_tokens],
                    target_prefix=tgt_prefix,
                    max_decoding_length=512,
                    beam_size=3,
                )
            else:
                raise

        hyp = results[0].hypotheses[0]
        # Clean special prefix and EOS tokens
        clean_tokens = [t for t in hyp if not t.startswith("__") and t not in ("<s>", "</s>")]
        translated: str = self._sp.Decode(clean_tokens)
        return translated


# ── Text Chunking ─────────────────────────────────────────────────────────────

def _split_text(text: str, max_chars: int = 400) -> list[str]:
    """Split text into sentences or manageable chunks for model inference."""
    sentences = re.split(r'(?<=[.!?؟।。！？\n])\s+', text)
    chunks: list[str] = []
    current = ""

    for s in sentences:
        if len(current) + len(s) < max_chars:
            current = (current + " " + s).strip() if current else s
        else:
            if current:
                chunks.append(current)
            if len(s) > max_chars:
                words = s.split()
                cur_words = ""
                for w in words:
                    if len(cur_words) + len(w) + 1 < max_chars:
                        cur_words = (cur_words + " " + w).strip() if cur_words else w
                    else:
                        if cur_words:
                            chunks.append(cur_words)
                        cur_words = w
                current = cur_words
            else:
                current = s

    if current:
        chunks.append(current)
    return chunks if chunks else [text]


def is_model_downloaded() -> bool:
    """Return True if local model files are already cached on disk."""
    dest = _model_dir() / _MODEL_FOLDER_NAME
    try:
        _validate_model_dir(dest)
        return True
    except TranslationModelValidationError:
        return False
