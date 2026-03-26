#!/usr/bin/env python3
"""
使用 faster-whisper 從影片自動生成字幕
當 YouTube 影片沒有字幕時作為 fallback

使用方法:
    python transcribe_audio.py <video_path> [output_dir] [model_size]

範例:
    python transcribe_audio.py video.mp4                    # 使用 small 模型
    python transcribe_audio.py video.mp4 ./output base      # 使用 base 模型輸出到 ./output
"""

import sys
import json
import warnings
from pathlib import Path

# 忽略 faster-whisper 的 warnings
warnings.filterwarnings("ignore")

try:
    from faster_whisper import WhisperModel
except ImportError:
    print("❌ Error: faster-whisper not installed")
    print("Please install: pip install faster-whisper")
    sys.exit(1)


def format_file_size(size_bytes: int) -> str:
    """格式化文件大小"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def seconds_to_vtt_time(seconds: float) -> str:
    """將秒數轉換為 VTT 時間格式 (HH:MM:SS.mmm)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def format_vtt_segment(start: float, end: float, text: str) -> str:
    """格式化單個 VTT 字幕區塊"""
    return f"{seconds_to_vtt_time(start)} --> {seconds_to_vtt_time(end)}\n{text.strip()}\n"


def transcribe_video(
    video_path: str,
    output_dir: str = None,
    model_size: str = "small",
    language: str = "en",
    progress_callback=None
) -> dict:
    """
    使用 faster-whisper 為影片生成字幕

    Args:
        video_path: 影片檔案路徑
        output_dir: 輸出目錄，預設為影片同目錄
        model_size: 模型大小 (tiny, base, small, medium, large)
        language: 語言代碼
        progress_callback: 進度回調函數

    Returns:
        dict: {
            'subtitle_path': 字幕檔案路徑,
            'video_path': 影片路徑,
            'duration': 影片時長（秒）,
            'language': 辨識語言,
            'model': 模型大小,
            'segments_count': 字幕段落數
        }
    """
    video_path = Path(video_path)

    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    # 設定輸出目錄
    if output_dir is None:
        output_dir = video_path.parent
    else:
        output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 輸出字幕檔案路徑
    subtitle_path = output_dir / f"{video_path.stem}.vtt"

    print(f"🎤 開始語音辨識...")
    print(f"   影片: {video_path.name}")
    print(f"   模型: {model_size}")
    print(f"   語言: {language}")
    print(f"   輸出: {subtitle_path}")

    # 計算影片時長（用於進度估算）
    import subprocess
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "json",
                str(video_path)
            ],
            capture_output=True,
            text=True,
            check=True
        )
        import json as json_lib
        info = json_lib.loads(result.stdout)
        duration = float(info["format"]["duration"])
    except Exception:
        duration = 0
        print("⚠️  無法取得影片時長")

    # 載入模型
    print(f"\n📦 載入模型 ({model_size})...")
    try:
        # 使用 CPU，compute_type="int8" 對 CPU 較友善
        model = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8"
        )
    except Exception as e:
        print(f"❌ 模型載入失敗: {e}")
        raise

    print(f"✅ 模型載入完成")
    print(f"\n🎙️  開始辨識...")

    # 執行辨識
    segments, info = model.transcribe(
        str(video_path),
        language=language,
        beam_size=5,
        vad_filter=True,  # 啟用語音活動檢測，過濾無語音區段
        vad_parameters=dict(min_silence_duration_ms=500)
    )

    # 收集資訊
    actual_language = info.language
    print(f"   偵測到語言: {actual_language} (confidence: {info.language_probability:.2%})")

    # 寫入 VTT 檔案
    with open(subtitle_path, "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")

        segment_count = 0
        for segment in segments:
            if progress_callback:
                # 進度回報（基於時間）
                progress = segment.end / duration if duration > 0 else 0
                progress_callback(progress, segment.text)

            # VTT 格式：每個段落間距 0.1 秒
            f.write(format_vtt_segment(segment.start, segment.end, segment.text))
            f.write("\n")
            segment_count += 1

            # 即時顯示進度
            elapsed = segment.end
            if duration > 0:
                pct = elapsed / duration * 100
                print(f"\r   進度: {pct:5.1f}% ({elapsed:.0f}s / {duration:.0f}s)", end="", flush=True)

    print()  # 換行

    # 取得檔案大小
    file_size = subtitle_path.stat().st_size if subtitle_path.exists() else 0

    print(f"\n✅ 字幕生成完成")
    print(f"   檔案: {subtitle_path.name}")
    print(f"   大小: {format_file_size(file_size)}")
    print(f"   段落: {segment_count} 個")

    return {
        "subtitle_path": str(subtitle_path),
        "video_path": str(video_path),
        "duration": duration,
        "language": actual_language,
        "model": model_size,
        "segments_count": segment_count,
        "file_size": file_size
    }


def main():
    """命令列入口"""
    if len(sys.argv) < 2:
        print("Usage: python transcribe_audio.py <video_path> [output_dir] [model_size]")
        print("\nExample:")
        print("  python transcribe_audio.py video.mp4")
        print("  python transcribe_audio.py video.mp4 ./output base")
        print("\nAvailable models: tiny, base, small, medium, large")
        sys.exit(1)

    video_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None
    model_size = sys.argv[3] if len(sys.argv) > 3 else "small"

    # 驗證模型大小
    valid_models = ["tiny", "base", "small", "medium", "large"]
    if model_size not in valid_models:
        print(f"❌ 無效的模型大小: {model_size}")
        print(f"可用模型: {', '.join(valid_models)}")
        sys.exit(1)

    try:
        result = transcribe_video(video_path, output_dir, model_size)

        # 輸出 JSON結果
        print("\n" + "="*60)
        print("辨識結果 (JSON):")
        print(json.dumps(result, indent=2, ensure_ascii=False))

    except Exception as e:
        print(f"\n❌ 錯誤: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
