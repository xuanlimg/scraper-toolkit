"""m3u8 视频分片下载与合并脚本。

用法：
    python m3u8_video_downloader.py <m3u8 地址> [--name 输出文件名] [--out 输出目录]

特性：
    - 自动识别主播放列表（#EXT-X-STREAM-INF），选择码率最高的一路
    - 单个分片失败按指数退避重试，并加入随机抖动，避免持续冲击服务器
    - 检测到 AES-128 加密流时直接报错，而不是保存损坏的视频
    - 先写入 .part 临时文件，全部分片完成后再原子替换为正式文件

说明：脚本不处理 AES-128 分片解密，遇到加密流会明确停止。
"""
from __future__ import annotations

import argparse
import os
import random
import re
import time
from urllib.parse import urljoin

import requests
from tqdm import tqdm

# 默认输出目录
DEFAULT_OUTPUT_DIR = "downloads/video"

HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
    )
}


def build_session() -> requests.Session:
    """创建复用连接的会话对象。"""
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def get_m3u8_text(session: requests.Session, url: str) -> str:
    """下载并返回 m3u8 文本。"""
    response = session.get(url, timeout=30)
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.text


def select_best_variant(lines: list[str]) -> str | None:
    """从主播放列表中挑出码率最高的子播放列表地址。"""
    variants: list[tuple[int, str]] = []

    for index, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF"):
            continue

        bandwidth_match = re.search(r"BANDWIDTH=(\d+)", line)
        bandwidth = int(bandwidth_match.group(1)) if bandwidth_match else 0

        for next_line in lines[index + 1:]:
            if not next_line.startswith("#"):
                variants.append((bandwidth, next_line))
                break

    if not variants:
        return None
    return max(variants, key=lambda item: item[0])[1]


def get_segment_urls(session: requests.Session, url: str) -> list[str]:
    """解析 m3u8，返回全部视频分片地址。"""
    text = get_m3u8_text(session, url)
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # 主播放列表里存的是不同清晰度的子播放列表，先挑码率最高的一路再递归解析
    best_variant = select_best_variant(lines)
    if best_variant:
        return get_segment_urls(session, urljoin(url, best_variant))

    # AES-128 加密流需要额外解密，这里明确提示而不是保存损坏的视频
    if any(line.startswith("#EXT-X-KEY") and "METHOD=AES-128" in line for line in lines):
        raise RuntimeError("检测到 AES-128 加密的 m3u8，需要先解密视频分片")

    segment_urls = [urljoin(url, line) for line in lines if not line.startswith("#")]
    if not segment_urls:
        raise RuntimeError("m3u8 中没有找到可下载的视频分片")
    return segment_urls


def download_segment(session: requests.Session, url: str, retries: int = 3) -> bytes:
    """下载单个分片，失败后按指数退避重试。"""
    for attempt in range(1, retries + 1):
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
            if not response.content:
                raise requests.RequestException("分片内容为空")
            return response.content
        except requests.RequestException:
            if attempt == retries:
                raise
            time.sleep(2 ** (attempt - 1) + random.random())
    raise RuntimeError("分片下载失败")


def download_video(m3u8_url: str, name: str = "video.ts", output_dir: str = DEFAULT_OUTPUT_DIR) -> str:
    """下载全部分片并合并为完整视频文件。"""
    os.makedirs(output_dir, exist_ok=True)
    session = build_session()

    segment_urls = get_segment_urls(session, m3u8_url)
    output_file = os.path.join(output_dir, name)
    part_file = output_file + ".part"

    try:
        with open(part_file, "wb") as f, tqdm(
            total=len(segment_urls),
            desc="下载分片",
            unit="段",
        ) as progress:
            for segment_url in segment_urls:
                f.write(download_segment(session, segment_url))
                progress.update(1)

        # 全部下载完成后再替换正式文件，避免留下看似完整但实际损坏的视频
        os.replace(part_file, output_file)
    except Exception:
        if os.path.exists(part_file):
            os.remove(part_file)
        raise

    print(f"视频已保存到：{output_file}")
    return output_file


def main() -> None:
    parser = argparse.ArgumentParser(description="m3u8 视频分片下载并合并为完整视频")
    parser.add_argument("url", help="m3u8 播放列表地址")
    parser.add_argument("--name", default="video.ts", help="输出文件名（默认 video.ts）")
    parser.add_argument("--out", default=DEFAULT_OUTPUT_DIR, help=f"输出目录（默认 {DEFAULT_OUTPUT_DIR}）")
    args = parser.parse_args()

    download_video(args.url, args.name, args.out)


if __name__ == "__main__":
    main()
