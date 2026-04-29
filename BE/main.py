#!/usr/bin/env python3
"""
main.py — brseAI Live Interpreter

Chạy lệnh này rồi nói vào mic, AI tự dịch liên tục.

Mặc định: tự nhận diện ngôn ngữ (vi/en/ja) và dịch ngược lại.
Có thể chỉ định ngôn ngữ cụ thể bằng --src và --tgt.

Ví dụ:
    python main.py                          # tự nhận diện + dịch (vi->en, en->vi, ja->en)
    python main.py --src vi --tgt en        # cố định dịch tiếng Việt sang tiếng Anh
    python main.py --src en --tgt vi        # cố định dịch tiếng Anh sang tiếng Việt
    python main.py --src ja --tgt en        # cố định dịch tiếng Nhật sang tiếng Anh
    python main.py --no-speaker             # tắt loa (chỉ hiển thị text)
    python main.py --list-devices           # liệt kê thiết bị âm thanh
    python main.py --device 2              # dùng mic cụ thể theo index
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(_PROJECT_ROOT / ".env")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="main.py",
        description="brseAI — Phiên dịch trực tiếp (Việt / Anh / Nhật). Nói vào mic, AI dịch ngay.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--src",
        default="auto",
        choices=["auto", "vi", "en", "ja"],
        help="Ngôn ngữ nguồn: auto (tự nhận diện), vi, en, ja. Mặc định: auto.",
    )
    p.add_argument(
        "--tgt",
        default="auto",
        choices=["auto", "vi", "en", "ja"],
        help="Ngôn ngữ đích: auto (tự suy ra), vi, en, ja. Mặc định: auto.",
    )
    p.add_argument(
        "--device",
        type=int,
        default=None,
        metavar="INDEX",
        help="Index thiết bị mic (xem --list-devices). Mặc định: mic hệ thống.",
    )
    p.add_argument(
        "--list-devices",
        action="store_true",
        help="Liệt kê tất cả thiết bị âm thanh rồi thoát.",
    )
    p.add_argument(
        "--no-speaker",
        action="store_true",
        help="Tắt loa — chỉ hiển thị bản dịch trên màn hình.",
    )
    p.add_argument(
        "--speaker-device",
        type=int,
        default=None,
        metavar="INDEX",
        help="Index thiết bị loa (xem --list-devices).",
    )
    p.add_argument(
        "--mode",
        choices=["realtime", "fallback"],
        default="realtime",
        help=(
            "realtime (mặc định): dùng OpenAI Realtime API — dịch ngay khi nói xong câu. "
            "fallback: ghi âm từng đoạn rồi dịch — phù hợp khi Realtime API không khả dụng."
        ),
    )
    p.add_argument(
        "--seconds",
        type=float,
        default=5.0,
        metavar="N",
        help="[fallback] Độ dài mỗi đoạn ghi âm (giây). Mặc định: 5.",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Hiển thị log chi tiết.",
    )
    return p.parse_args()


def run_realtime(args: argparse.Namespace, api_key: str) -> int:
    from src.common.audio import MicInput
    from src.common.lang import parse_pairs
    from src.realtime.client import RealtimeClient

    audio_input = MicInput(device=args.device, sample_rate=16000)
    enable_speaker = not args.no_speaker

    client = RealtimeClient(
        api_key=api_key,
        enable_speaker=enable_speaker,
        speaker_device=args.speaker_device,
        debug=args.debug,
        src_lang=args.src,
        tgt_lang=args.tgt,
        allowed_pairs=set(),
        show_input=True,
        meeting_mode="locked",
        audio_input=audio_input,
    )
    client.run()
    return 0


def run_fallback_loop(args: argparse.Namespace, api_key: str) -> int:
    from src.fallback.pipeline import run_fallback

    print(
        f"[Fallback mode] Ghi âm {args.seconds:.0f}s mỗi lượt. Nói xong sẽ dịch. Ctrl+C để dừng.\n",
        flush=True,
    )
    while True:
        try:
            print(f"--- Đang ghi âm {args.seconds:.0f}s... Hãy nói ---", flush=True)
            translation = run_fallback(
                seconds=args.seconds,
                mic_device=args.device,
                sample_rate=16000,
                api_key=api_key,
                src_lang=args.src,
                tgt_lang=args.tgt,
                meeting_mode="locked",
            )
            if translation:
                print(f"[Dịch] {translation}\n", flush=True)
            else:
                print("[Không nhận được giọng nói hoặc transcript trống]\n", flush=True)
        except KeyboardInterrupt:
            print("\nĐã dừng.", flush=True)
            return 0
        except Exception as exc:
            print(f"[Lỗi] {exc}", file=sys.stderr)
            return 1


def main() -> int:
    args = parse_args()

    if args.list_devices:
        from src.common.audio import print_input_devices, print_output_devices
        print("=== Thiết bị đầu vào (mic) ===")
        print_input_devices()
        print("\n=== Thiết bị đầu ra (loa) ===")
        print_output_devices()
        return 0

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print(
            "Lỗi: Chưa thiết lập OPENAI_API_KEY.\n"
            "  Tạo file .env và thêm: OPENAI_API_KEY=sk-...\n"
            "  Hoặc: export OPENAI_API_KEY=sk-...",
            file=sys.stderr,
        )
        return 1

    lang_note = {
        ("auto", "auto"): "Tự nhận diện ngôn ngữ (vi↔en, ja→en)",
        ("vi", "en"): "Tiếng Việt → Tiếng Anh",
        ("en", "vi"): "Tiếng Anh → Tiếng Việt",
        ("ja", "en"): "Tiếng Nhật → Tiếng Anh",
        ("en", "ja"): "Tiếng Anh → Tiếng Nhật",
        ("vi", "ja"): "Tiếng Việt → Tiếng Nhật",
        ("ja", "vi"): "Tiếng Nhật → Tiếng Việt",
    }.get((args.src, args.tgt), f"{args.src} → {args.tgt}")

    speaker_note = "loa TẮT (chỉ hiển thị text)" if args.no_speaker else "loa BẬT"
    print(f"\nbrseAI Phiên dịch trực tiếp", flush=True)
    print(f"  Chế độ  : {args.mode}", flush=True)
    print(f"  Ngôn ngữ: {lang_note}", flush=True)
    print(f"  Âm thanh: {speaker_note}", flush=True)
    if args.device is not None:
        print(f"  Mic     : device #{args.device}", flush=True)
    print(f"\nNhấn Ctrl+C để dừng.\n", flush=True)

    if args.mode == "realtime":
        return run_realtime(args, api_key)
    else:
        return run_fallback_loop(args, api_key)


if __name__ == "__main__":
    sys.exit(main())
