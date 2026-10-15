"""
Verbum Transcription CLI
Command line interface for the standalone transcription engine.
"""

import argparse
import json
import os
import sys

from engine import (
    AVAILABLE_MODELS,
    DEFAULT_MODEL_NAME,
    TranscriptionEngine,
    download_model,
    get_installed_models,
    is_model_installed,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Verbum Transcription CLI")
    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    # Transcribe command
    t_parser = subparsers.add_parser("transcribe", help="Transcribe an audio file")
    t_parser.add_argument("path", help="Path to audio file")
    t_parser.add_argument("--model", default=DEFAULT_MODEL_NAME, choices=list(AVAILABLE_MODELS.keys()), help="Model to use")
    t_parser.add_argument("--language", default=None, help="Language code (or 'auto')")
    t_parser.add_argument("--no-vad", action="store_true", help="Disable voice activity detection filter")
    t_parser.add_argument("--prompt", default=None, help="Initial prompt vocabulary hint")
    t_parser.add_argument("--json", dest="json_out", action="store_true", help="Output results in JSON format")

    # Models command
    m_parser = subparsers.add_parser("models", help="Model management commands")
    m_sub = m_parser.add_subparsers(dest="model_action")
    
    # models list
    m_list = m_sub.add_parser("list", help="List installed and available models")
    m_list.add_argument("--json", dest="json_out", action="store_true", help="Output in JSON format")

    # models download
    m_dl = m_sub.add_parser("download", help="Download a model explicitly")
    m_dl.add_argument("name", choices=list(AVAILABLE_MODELS.keys()), help="Model name to download")
    m_dl.add_argument("--json", dest="json_out", action="store_true", help="Output in JSON format")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "models":
        if args.model_action == "list":
            installed = get_installed_models()
            res = []
            for name, meta in AVAILABLE_MODELS.items():
                res.append({
                    "name": name,
                    "installed": name in installed,
                    "size_mb": meta["size_mb"],
                    "approx_vram_mb": meta["approx_vram_mb"],
                })
            if getattr(args, "json_out", False):
                print(json.dumps(res, indent=2))
            else:
                print("Verbum Whisper Models:")
                for m in res:
                    status = "INSTALLED" if m["installed"] else f"NOT DOWNLOADED (~{m['size_mb']} MB)"
                    print(f"  - {m['name']:<8}: {status}")
            sys.exit(0)

        elif args.model_action == "download":
            name = args.name
            try:
                def on_prog(info: dict) -> None:
                    if not getattr(args, "json_out", False):
                        pct = info.get("percent", 0)
                        sys.stdout.write(f"\rDownloading {name}: {pct:.1f}%")
                        sys.stdout.flush()

                download_model(name, on_progress=on_prog)
                if not getattr(args, "json_out", False):
                    print(f"\nModel '{name}' downloaded successfully.")
                else:
                    print(json.dumps({"status": "success", "model": name}))
                sys.exit(0)
            except Exception as e:
                if getattr(args, "json_out", False):
                    print(json.dumps({"error": str(e), "code": "MODEL_DOWNLOAD_FAILED"}))
                else:
                    print(f"Error downloading model: {e}", file=sys.stderr)
                sys.exit(1)

    elif args.command == "transcribe":
        audio_path = os.path.abspath(args.path)
        if not os.path.isfile(audio_path):
            err_obj = {"error": f"Audio file not found: {audio_path}", "code": "BAD_AUDIO"}
            if args.json_out:
                print(json.dumps(err_obj))
            else:
                print(f"Error: {err_obj['error']}", file=sys.stderr)
            sys.exit(1)

        model_name = args.model
        if not is_model_installed(model_name):
            err_obj = {
                "error": f"Model '{model_name}' is not installed. Download it first using 'python cli.py models download {model_name}'.",
                "code": "NO_MODEL",
            }
            if args.json_out:
                print(json.dumps(err_obj))
            else:
                print(f"Error: {err_obj['error']}", file=sys.stderr)
            sys.exit(2)

        try:
            engine = TranscriptionEngine()
            engine.load_model(model_name)
            res = engine.transcribe(
                audio_path,
                language=args.language,
                vad=not args.no_vad,
                initial_prompt=args.prompt,
            )
            if args.json_out:
                print(json.dumps(res, indent=2))
            else:
                print(res["text"])
            sys.exit(0)
        except Exception as e:
            err_obj = {"error": str(e), "code": "INTERNAL"}
            if args.json_out:
                print(json.dumps(err_obj))
            else:
                print(f"Error: {e}", file=sys.stderr)
            sys.exit(3)


if __name__ == "__main__":
    main()
