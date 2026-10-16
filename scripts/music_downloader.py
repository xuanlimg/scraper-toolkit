"""音频直链下载脚本。

用法：
    python music_downloader.py <音频直链> [保存名称]
    python music_downloader.py            # 交互式输入链接与名称

特性：流式写入避免大文件占内存、按 Content-Type 推断后缀、拦截失效直链返回的网页内容、临时文件写完后原子替换。
"""
import os
import re
import sys
from urllib.parse import unquote, urlparse

import requests
from tqdm import tqdm

# 保存音乐的目标文件夹
folder = "downloads/music"
os.makedirs(folder, exist_ok=True)

# 构造请求头字典，伪装浏览器身份
headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
}

# 根据响应类型识别常见音频后缀
content_type_extensions = {
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/flac": ".flac",
    "audio/wav": ".wav",
    "audio/ogg": ".ogg",
}


def clean_filename(name):
    """清理文件名中不能用于 Windows 的字符。"""
    name = re.sub(r'[\\/:*?"<>|]', "_", name).strip().strip(".")
    return name or "音乐"


def normalize_url(value):
    """清理 Markdown 链接和转义字符，得到可直接请求的 URL。"""
    value = value.strip()

    # 兼容 [链接说明](https://...) 格式
    markdown_match = re.fullmatch(r"\[[^\]]*\]\((https?://.+)\)", value, re.DOTALL)
    if markdown_match:
        value = markdown_match.group(1)

    value = value.strip("<>").replace("\\&", "&").replace("\\=", "=")
    return value.strip()


def get_extension(url, content_type):
    """优先使用 URL 后缀，否则根据响应类型选择音频后缀。"""
    url_extension = os.path.splitext(urlparse(url).path)[1].lower()
    if url_extension in {".m4a", ".mp3", ".flac", ".wav", ".ogg", ".aac"}:
        return url_extension

    mime_type = content_type.split(";", 1)[0].strip().lower()
    return content_type_extensions.get(mime_type, ".m4a")


def get_filename(url, response, custom_name=None):
    """从自定义名称或 URL 中生成安全的音乐文件名。"""
    extension = get_extension(url, response.headers.get("Content-Type", ""))

    if custom_name:
        filename = clean_filename(custom_name)
    else:
        filename = clean_filename(unquote(os.path.basename(urlparse(url).path)) or "音乐")

    if not os.path.splitext(filename)[1]:
        filename += extension
    return filename


def download_music(music_url, custom_name=None):
    """下载音频直链并保存到 downloads/music 目录。"""
    parsed_url = urlparse(music_url)
    if parsed_url.scheme not in {"http", "https"}:
        raise ValueError("请输入以 http:// 或 https:// 开头的音频直链")

    # 网易云 CDN 通常会校验来源页
    if "music.163.com" in parsed_url.netloc or "music.126.net" in parsed_url.netloc:
        headers["referer"] = "https://music.163.com/"

    # 使用流式下载，避免把大文件一次性读入内存
    with requests.get(music_url, headers=headers, stream=True, timeout=30) as response:
        response.raise_for_status()

        # 音频直链失效时，服务器可能返回 200 的网页，需要提前拦截
        content_type = response.headers.get("Content-Type", "").lower()
        if "text/html" in content_type or "application/json" in content_type:
            raise ValueError(
                "音频直链返回的是网页或 JSON，链接可能已失效或需要重新登录"
            )

        filename = get_filename(music_url, response, custom_name)
        output_file = os.path.join(folder, filename)
        part_file = output_file + ".part"

        total_size = int(response.headers.get("Content-Length", 0)) or None

        try:
            with open(part_file, "wb") as f, tqdm(
                total=total_size,
                unit="B",
                unit_scale=True,
                desc=f"下载 {filename}",
            ) as progress:
                for chunk in response.iter_content(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    progress.update(len(chunk))

            # 下载完整后再替换正式文件，避免留下损坏的音频
            os.replace(part_file, output_file)
        except Exception:
            if os.path.exists(part_file):
                os.remove(part_file)
            raise

    print(f"音乐已保存到：{output_file}")


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        url = normalize_url(sys.argv[1])
        music_name = sys.argv[2] if len(sys.argv) >= 3 else None
    else:
        url = ""
        for _ in range(2):
            try:
                raw_url = input("请输入有权下载的音频直链：")
            except EOFError:
                break

            url = normalize_url(raw_url)
            if url:
                break
            print("没有读取到链接，请重新粘贴。")

        if not url:
            raise SystemExit(
                "未输入音频直链。请在 PyCharm 运行配置的 Script parameters 中粘贴 URL，"
                "并使用英文单引号包住整个链接。"
            )

        music_name = input("请输入歌曲名称（可留空）：").strip() or None

    download_music(url, music_name)


