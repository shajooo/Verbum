# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
datas += [
    ('metadata', 'metadata'),
    ('dataset/glyphs', 'dataset/glyphs'),
    ('models/character_ocr/character_ocr.onnx', 'models/character_ocr'),
    ('models/character_ocr/labels.json', 'models/character_ocr'),
    ('models/word_ocr/word_crnn.onnx', 'models/word_ocr'),
    ('models/context_ocr/context_bert.onnx', 'models/context_ocr'),
    ('models/context_ocr/tokenizer.json', 'models/context_ocr'),
    ('models/context_ocr/tokenizer_config.json', 'models/context_ocr'),
    ('models/context_ocr/config.json', 'models/context_ocr'),
]
hiddenimports = ['pymupdf', 'rapidocr_onnxruntime', 'docx', 'PIL', 'ctranslate2', 'sentencepiece', 'langdetect', 'huggingface_hub', 'fontTools', 'reportlab', 'onnxruntime', 'tokenizers', 'PySide6.QtPrintSupport']
for pkg in ['faster_whisper', 'ctranslate2', 'rapidocr_onnxruntime', 'pymupdf', 'docx', 'sentencepiece', 'langdetect', 'huggingface_hub', 'fontTools', 'reportlab', 'onnxruntime', 'tokenizers']:
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    excludes=['torch', 'torchvision', 'sympy'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='VoiceInput',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='VoiceInput',
)
