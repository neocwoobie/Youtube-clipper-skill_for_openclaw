#!/usr/bin/env python3
"""
烧录字幕到视频
处理 FFmpeg libass 支持和路径空格问题
"""

import sys
import os
import shutil
import subprocess
import tempfile
import platform
from pathlib import Path
from typing import Dict, Optional

from utils import format_file_size


def detect_ffmpeg_variant() -> Dict:
    """
    检测 FFmpeg 版本和 libass 支持

    Returns:
        Dict: {
            'type': 'full' | 'standard' | 'none',
            'path': FFmpeg 可执行文件路径,
            'has_libass': 是否支持 libass
        }
    """
    print("🔍 检测 FFmpeg 环境...")

    # 优先检查 ffmpeg-full（macOS）
    if platform.system() == 'Darwin':
        # Apple Silicon
        full_path_arm = '/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg'
        # Intel
        full_path_intel = '/usr/local/opt/ffmpeg-full/bin/ffmpeg'

        for full_path in [full_path_arm, full_path_intel]:
            if Path(full_path).exists():
                has_libass = check_libass_support(full_path)
                print(f"   找到 ffmpeg-full: {full_path}")
                print(f"   libass 支持: {'✅ 是' if has_libass else '❌ 否'}")
                return {
                    'type': 'full',
                    'path': full_path,
                    'has_libass': has_libass
                }

    # 检查标准 FFmpeg
    standard_path = shutil.which('ffmpeg')
    if standard_path:
        has_libass = check_libass_support(standard_path)
        variant_type = 'full' if has_libass else 'standard'
        print(f"   找到 FFmpeg: {standard_path}")
        print(f"   类型: {variant_type}")
        print(f"   libass 支持: {'✅ 是' if has_libass else '❌ 否'}")
        return {
            'type': variant_type,
            'path': standard_path,
            'has_libass': has_libass
        }

    # 未找到 FFmpeg
    print("   ❌ 未找到 FFmpeg")
    return {
        'type': 'none',
        'path': None,
        'has_libass': False
    }


def check_libass_support(ffmpeg_path: str) -> bool:
    """
    检查 FFmpeg 是否支持 libass（字幕烧录必需）

    Args:
        ffmpeg_path: FFmpeg 可执行文件路径

    Returns:
        bool: 是否支持 libass
    """
    try:
        # 检查是否有 subtitles 滤镜
        result = subprocess.run(
            [ffmpeg_path, '-filters'],
            capture_output=True,
            text=True,
            timeout=5
        )

        # 查找 subtitles 滤镜
        return 'subtitles' in result.stdout.lower()

    except Exception:
        return False


def install_ffmpeg_full_guide():
    """
    显示安装 ffmpeg-full 的指南
    """
    print("\n" + "="*60)
    print("⚠️  需要安装 ffmpeg-full 才能烧录字幕")
    print("="*60)

    if platform.system() == 'Darwin':
        print("\nmacOS 安装方法:")
        print("  brew install ffmpeg-full")
        print("\n安装后，FFmpeg 路径:")
        print("  /opt/homebrew/opt/ffmpeg-full/bin/ffmpeg  (Apple Silicon)")
        print("  /usr/local/opt/ffmpeg-full/bin/ffmpeg     (Intel)")
    else:
        print("\n其他系统:")
        print("  请从源码编译 FFmpeg，确保包含 libass 支持")
        print("  参考: https://trac.ffmpeg.org/wiki/CompilationGuide")

    print("\n验证安装:")
    print("  ffmpeg -filters 2>&1 | grep subtitles")
    print("="*60)


def _get_ffmpeg_subtitle_path(subtitle_path: str) -> str:
    """
    取得 FFmpeg subtitles 濾鏡可接受的字幕路徑格式
    
    Windows FFmpeg 7.x subtitles 濾鏡對路徑處理有 bug：
    - 反斜槓 \\ 會被誤解析為 \\U escape 序列
    - 解決方式：使用正斜槓 / 並確保路徑格式正確
    
    Args:
        subtitle_path: 原始字幕路徑
        
    Returns:
        str: FFmpeg 可接受的路徑格式
    """
    # 轉換為正斜槓格式，確保 FFmpeg 能正確解析
    # Windows 上路徑如 C:\Users\Neo Chen\... 
    # 轉為 C:/Users/Neo Chen/...
    # 並用雙引號包裝（FFmpeg 解析器需要）
    # 注意：冒號前需加反斜槓轉義（\\:），這是 FFmpeg 路徑語法
    return subtitle_path.replace('\\', '/').replace(':', '\\:')


def _convert_srt_to_ass(srt_path: str) -> Optional[str]:
    """
    將 SRT 字幕轉換為 ASS 格式，提升燒錄相容性
    
    ASS 格式對 FFmpeg libass 的支援更穩定，特別是含多行字幕時。
    
    Args:
        srt_path: SRT 字幕檔路徑
        
    Returns:
        str: ASS 檔路徑，失敗時回傳 None
    """
    try:
        import pysrt
        ass_path = srt_path.replace('.srt', '.ass')
        subs = pysrt.open(srt_path)
        subs.save(ass_path, encoding='utf-8')
        return ass_path
    except ImportError:
        # pysrt 未安裝，跳過轉換，使用原路徑
        return None
    except Exception:
        # 轉換失敗，使用原路徑
        return None


def burn_subtitles(
    video_path: str,
    subtitle_path: str,
    output_path: str,
    ffmpeg_path: str = None,
    font_size: int = 24,
    margin_v: int = 30
) -> str:
    """
    燒錄字幕到視頻（使用臨時目錄解決路徑空格問題）

    Windows FFmpeg 7.x subtitles 濾鏡特殊處理：
    - 使用正斜槓路徑格式（forward slash）並對驅動器冒號轉義
    - SRT 轉 ASS 提升中文多行字幕相容性
    - 臨時目錄確保路徑無特殊字元

    Args:
        video_path: 輸入視頻路徑
        subtitle_path: 字幕文件路徑（SRT 或 ASS 格式）
        output_path: 輸出視頻路徑
        ffmpeg_path: FFmpeg 可執行文件路徑（可選）
        font_size: 字體大小，默認 24
        margin_v: 底部邊距，默認 30

    Returns:
        str: 輸出視頻路徑

    Raises:
        FileNotFoundError: 輸入文件不存在
        RuntimeError: FFmpeg 執行失敗
    """
    video_path = Path(video_path)
    subtitle_path = Path(subtitle_path)
    output_path = Path(output_path)

    # 驗證輸入文件
    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")
    if not subtitle_path.exists():
        raise FileNotFoundError(f"Subtitle file not found: {subtitle_path}")

    # 檢測 FFmpeg
    if ffmpeg_path is None:
        ffmpeg_info = detect_ffmpeg_variant()

        if ffmpeg_info['type'] == 'none':
            install_ffmpeg_full_guide()
            raise RuntimeError("FFmpeg not found")

        if not ffmpeg_info['has_libass']:
            install_ffmpeg_full_guide()
            raise RuntimeError("FFmpeg does not support libass (subtitles filter)")

        ffmpeg_path = ffmpeg_info['path']

    print(f"\n🎬 燒錄字幕到視頻...")
    print(f"   視頻: {video_path.name}")
    print(f"   字幕: {subtitle_path.name}")
    print(f"   輸出: {output_path.name}")
    print(f"   FFmpeg: {ffmpeg_path}")

    # 建立臨時目錄（解決路徑空格問題）
    temp_dir = tempfile.mkdtemp(prefix='youtube_clipper_')
    print(f"   使用臨時目錄: {temp_dir}")

    try:
        # 複製文件到臨時目錄（路徑無空格）
        temp_video = os.path.join(temp_dir, 'video.mp4')
        temp_subtitle = os.path.join(temp_dir, 'subtitle.srt')
        temp_output = os.path.join(temp_dir, 'output.mp4')

        print(f"   複製文件到臨時目錄...")
        shutil.copy(video_path, temp_video)

        # 嘗試轉換 SRT 為 ASS（提升中文多行字幕相容性）
        ass_path = _convert_srt_to_ass(str(subtitle_path))
        if ass_path and Path(ass_path).exists():
            # 使用 ASS 字幕
            shutil.copy(ass_path, os.path.join(temp_dir, 'subtitle.ass'))
            subtitle_for_ffmpeg = os.path.join(temp_dir, 'subtitle.ass')
            print(f"   使用 ASS 字幕格式燒錄")
        else:
            shutil.copy(subtitle_path, temp_subtitle)
            subtitle_for_ffmpeg = temp_subtitle

        # Windows FFmpeg 7.x 特殊處理
        # FFmpeg subtitles 濾鏡不支援反斜槓路徑，需轉為正斜槓格式
        is_windows = platform.system() == 'Windows'
        
        if is_windows:
            # Windows: 使用 C\:/path/ 格式（正斜槓 + 驅動器冒號轉義）
            subtitle_for_ffmpeg_filter = _get_ffmpeg_subtitle_path(subtitle_for_ffmpeg)
            video_for_ffmpeg = _get_ffmpeg_subtitle_path(temp_video)
            output_for_ffmpeg = _get_ffmpeg_subtitle_path(temp_output)
        else:
            # macOS/Linux: 直接使用路徑
            subtitle_for_ffmpeg_filter = subtitle_for_ffmpeg
            video_for_ffmpeg = temp_video
            output_for_ffmpeg = temp_output

        # 建構 FFmpeg 命令
        subtitle_filter = f"subtitles='{subtitle_for_ffmpeg_filter}':force_style='FontSize={font_size},MarginV={margin_v}'"

        cmd = [
            ffmpeg_path,
            '-i', video_for_ffmpeg,
            '-vf', subtitle_filter,
            '-c:a', 'copy',  # 音頻直接複製，不重新編碼
            '-y',  # 覆蓋輸出文件
            output_for_ffmpeg
        ]

        print(f"   執行 FFmpeg...")
        print(f"   命令: {' '.join(cmd)}")

        # 執行 FFmpeg
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )

        if result.returncode != 0:
            print(f"\n❌ FFmpeg 執行失敗:")
            print(f"   stderr: {result.stderr[:500]}")

            # 如果 ASS 失敗，嘗試純 SRT（不做 ASS 轉換）
            if ass_path and Path(ass_path).exists():
                print(f"\n🔄 ASS 字幕失敗，嘗試使用原 SRT 字幕...")
                subtitle_srt_for_filter = _get_ffmpeg_subtitle_path(temp_subtitle)
                subtitle_filter_srt = f"subtitles='{subtitle_srt_for_filter}':force_style='FontSize={font_size},MarginV={margin_v}'"
                
                cmd_srt = [
                    ffmpeg_path,
                    '-i', video_for_ffmpeg,
                    '-vf', subtitle_filter_srt,
                    '-c:a', 'copy',
                    '-y',
                    output_for_ffmpeg
                ]
                
                result_srt = subprocess.run(
                    cmd_srt,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace'
                )
                
                if result_srt.returncode == 0:
                    print(f"✅ SRT 字幕燒錄成功")
                else:
                    print(f"❌ SRT 字幕也失敗: {result_srt.stderr[:300]}")
                    raise RuntimeError(f"FFmpeg failed with return code {result_srt.returncode}")
            else:
                raise RuntimeError(f"FFmpeg failed with return code {result.returncode}")

        # 驗證輸出文件
        if not Path(temp_output).exists():
            raise RuntimeError("Output file not created")

        # 移動輸出文件到目標位置
        print(f"   移動輸出文件...")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(temp_output, output_path)

        # 獲取文件大小
        output_size = output_path.stat().st_size
        print(f"✅ 字幕燒錄完成")
        print(f"   輸出文件: {output_path}")
        print(f"   文件大小: {format_file_size(output_size)}")

        return str(output_path)

    finally:
        # 清理臨時目錄
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
            print(f"   清理臨時目錄")
        except Exception:
            pass


def main():
    """命令行入口"""
    if len(sys.argv) < 4:
        print("Usage: python burn_subtitles.py <video> <subtitle> <output> [font_size] [margin_v]")
        print("\nArguments:")
        print("  video      - 输入视频文件路径")
        print("  subtitle   - 字幕文件路径（SRT 格式）")
        print("  output     - 输出视频文件路径")
        print("  font_size  - 字体大小，默认 24")
        print("  margin_v   - 底部边距，默认 30")
        print("\nExample:")
        print("  python burn_subtitles.py input.mp4 subtitle.srt output.mp4")
        print("  python burn_subtitles.py input.mp4 subtitle.srt output.mp4 28 40")
        sys.exit(1)

    video_path = sys.argv[1]
    subtitle_path = sys.argv[2]
    output_path = sys.argv[3]
    font_size = int(sys.argv[4]) if len(sys.argv) > 4 else 24
    margin_v = int(sys.argv[5]) if len(sys.argv) > 5 else 30

    try:
        result_path = burn_subtitles(
            video_path,
            subtitle_path,
            output_path,
            font_size=font_size,
            margin_v=margin_v
        )

        print(f"\n✨ 完成！输出文件: {result_path}")

    except Exception as e:
        print(f"\n❌ 错误: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
