"""小说章节抓取脚本（示例站点：刺猬猫 WAP 版）。

用法：
    python novel_downloader.py <书籍目录页地址> [--out 输出目录] [--delay 1.0]

需要抓取登录可见章节时，把浏览器里的 Cookie 放进环境变量：
    PowerShell:  $env:CIWEIMAO_COOKIE = "你的 Cookie"
    CMD:         set CIWEIMAO_COOKIE=你的 Cookie

特性：按章节保存 txt、序号前缀保证排序、清洗非法文件名、逐章请求间隔、识别登录重定向与空正文
（付费或未购章节不会生成空文件，直接跳过并提示）。

说明：仅抓取当前账号有权访问的内容，请遵守目标站点服务条款，不要用于批量分发。
"""
from __future__ import annotations

import argparse
import os
import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# 默认输出目录
DEFAULT_OUTPUT_DIR = "downloads/novel"

# 站点通用的请求头
BASE_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
    )
}


def build_headers() -> dict[str, str]:
    """构造请求头，Cookie 从环境变量读取，避免写死在代码里。"""
    headers = dict(BASE_HEADERS)
    cookie = os.getenv("CIWEIMAO_COOKIE")
    if cookie:
        headers["Cookie"] = cookie
    return headers


def fetch(url: str, headers: dict[str, str], retries: int = 3) -> requests.Response:
    """请求页面，失败后重试。"""
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            response.encoding = "utf-8"  # 中文站点固定 utf-8 解析，避免乱码
            return response
        except requests.RequestException as error:
            last_error = error
            if attempt < retries:
                time.sleep(1.5 * attempt)

    raise RuntimeError(f"请求失败：{last_error}")


def clean_filename(name: str) -> str:
    """清理文件名中不能用于 Windows 的字符。"""
    name = re.sub(r'[\\/:*?"<>|]', "_", name).strip().strip(".")
    return name or "chapter"


def parse_chapters(html: str, base_url: str) -> list[tuple[str, str]]:
    """从目录页解析出「章节名 + 章节地址」列表。"""
    soup = BeautifulSoup(html, "html.parser")
    chapters: list[tuple[str, str]] = []

    for link in soup.select(".catalogue-list a"):
        href = link.get("href")
        if not href:
            continue
        chapters.append((link.get_text(strip=True), urljoin(base_url, href)))

    return chapters


def extract_text(html: str) -> str:
    """提取正文段落；付费占位节点会被过滤掉。"""
    soup = BeautifulSoup(html, "html.parser")
    paragraphs = soup.select("#J_BookRead p")
    return "\n".join(filter(None, (p.get_text(strip=True) for p in paragraphs)))


def download_book(book_url: str, output_dir: str = DEFAULT_OUTPUT_DIR, delay: float = 1.0) -> None:
    """抓取整本书的所有可读章节。"""
    headers = build_headers()

    response = fetch(book_url, headers)
    chapters = parse_chapters(response.text, book_url)
    if not chapters:
        raise SystemExit("没有解析到章节，请确认传入的是书籍目录页地址")

    os.makedirs(output_dir, exist_ok=True)
    success_count = 0
    skipped_count = 0

    for index, (chapter_name, chapter_url) in enumerate(chapters, start=1):
        try:
            detail = fetch(chapter_url, headers)
        except RuntimeError as error:
            print(f"[{index}] {chapter_name} -- 请求失败：{error}")
            skipped_count += 1
            continue

        # 未登录时站点会跳转登录页
        if "/signup/login" in detail.url:
            print(f"[{index}] {chapter_name} -- 需要登录，已跳过（可设置 CIWEIMAO_COOKIE）")
            skipped_count += 1
            continue

        text = extract_text(detail.text)
        if not text:
            print(f"[{index}] {chapter_name} -- 未获取到正文（可能需要登录或购买）")
            skipped_count += 1
            continue

        file_path = os.path.join(output_dir, f"{index:04d}_{clean_filename(chapter_name)}.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(text + "\n")

        success_count += 1
        print(f"[{index}] {chapter_name} -- 已保存")

        # 逐章限速，避免给站点造成压力
        if delay:
            time.sleep(delay)

    print(f"抓取结束：成功 {success_count} 章，跳过 {skipped_count} 章")


def main() -> None:
    parser = argparse.ArgumentParser(description="小说章节抓取（示例站点：刺猬猫 WAP）")
    parser.add_argument("url", help="书籍目录页地址")
    parser.add_argument("--out", default=DEFAULT_OUTPUT_DIR, help=f"输出目录（默认 {DEFAULT_OUTPUT_DIR}）")
    parser.add_argument("--delay", type=float, default=1.0, help="每章请求间隔秒数（默认 1.0）")
    args = parser.parse_args()

    download_book(args.url, args.out, args.delay)


if __name__ == "__main__":
    main()
