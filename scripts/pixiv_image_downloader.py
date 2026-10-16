"""Pixiv 公开预览图批量下载脚本。

用法：
    python pixiv_image_downloader.py                 # 交互式输入链接
    python pixiv_image_downloader.py <URL> [<URL>]   # 直接传入多个链接
    python pixiv_image_downloader.py <URL>|文件名   # 自定义保存名
    无输入且存在 image_urls.txt 时，会按该文件批量下载（每行一条）

特性：连接复用 + 429/5xx 自动重试、请求限速、Pillow 校验图片、临时文件写完后原子替换。
说明：未使用访问令牌，只能获取作品页公开的预览图。
"""
import os
import re
import sys
import time
from functools import lru_cache
from urllib.parse import unquote, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 图片保存文件夹
folder = "downloads/images"
os.makedirs(folder, exist_ok=True)

# 默认下载列表
default_task_file = "image_urls.txt"

# 用于图片 CDN 的请求头
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
    "Referer": "https://www.pixiv.net/",
    "Accept-Encoding": "identity",
}

# 复用连接并自动处理 429/5xx 错误
session = requests.Session()
retry = Retry(
    total=3,
    connect=3,
    read=3,
    status=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"GET"}),
    respect_retry_after_header=True,
)
adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
session.mount("http://", adapter)
session.mount("https://", adapter)

# 控制请求间隔，降低触发 Pixiv 限流的概率
minimum_request_interval = 0.8
last_request_time = 0.0


def request_get(url, **kwargs):
    """统一发送请求，并保证相邻请求之间有合理间隔。"""
    global last_request_time

    elapsed = time.monotonic() - last_request_time
    if elapsed < minimum_request_interval:
        time.sleep(minimum_request_interval - elapsed)

    kwargs.setdefault("timeout", (10, 60))
    last_request_time = time.monotonic()
    return session.get(url, **kwargs)


def validate_image(file_path):
    """使用 Pillow 校验图片，并返回图片真实后缀。"""
    image_extensions = {
        "JPEG": ".jpg",
        "PNG": ".png",
        "GIF": ".gif",
        "WEBP": ".webp",
        "BMP": ".bmp",
        "TIFF": ".tiff",
    }

    try:
        with Image.open(file_path) as image:
            image_format = image.format
            image.verify()
    except Exception as error:
        raise ValueError("下载内容不是有效图片") from error

    return image_extensions.get(image_format, ".jpg")


def normalize_url(value):
    """清理 Markdown 链接和转义字符，得到可直接请求的 URL。"""
    value = value.strip()

    markdown_match = re.fullmatch(r"\[[^\]]*\]\((https?://.+)\)", value, re.DOTALL)
    if markdown_match:
        value = markdown_match.group(1)

    value = value.strip("<>").replace("\\&", "&").replace("\\=", "=")
    return value.strip()


def clean_filename(name):
    """清理文件名中不能用于 Windows 的字符。"""
    name = re.sub(r'[\\/:*?"<>|]', "_", name).strip().strip(".")
    return name or "pixiv"


def get_pixiv_artwork_id(url):
    """从 Pixiv 作品页 URL 中提取作品 ID。"""
    parsed_url = urlparse(url)
    if "pixiv.net" not in parsed_url.netloc:
        return None

    match = re.search(r"/artworks/(\d+)", parsed_url.path)
    return match.group(1) if match else None


def get_pixiv_image_info(url):
    """从 Pixiv 图片文件名中提取作品 ID、页码和图片后缀。"""
    parsed_url = urlparse(url)
    if "pximg.net" not in parsed_url.netloc:
        return None

    filename = unquote(os.path.basename(parsed_url.path))
    match = re.match(r"(\d+)_p(\d+)_", filename)
    if not match:
        return None

    extension = os.path.splitext(filename)[1].lower() or ".jpg"
    return match.group(1), int(match.group(2)), extension


def extract_pixiv_title(soup):
    """从 Pixiv 页面公开元数据中提取作品标题。"""
    title_tag = soup.select_one('meta[name="twitter:title"]')
    if title_tag and title_tag.get("content"):
        return title_tag["content"].strip()

    title_tag = soup.select_one('meta[property="og:title"]')
    if title_tag and title_tag.get("content"):
        title = title_tag["content"]
        return re.sub(r"\s+-\s+.+\s+-\s+pixiv$", "", title).strip()

    return None


@lru_cache(maxsize=128)
def get_artwork_public_info(illust_id):
    """读取作品页公开标题和公开预览图，不依赖访问令牌。"""
    artwork_url = f"https://www.pixiv.net/artworks/{illust_id}"
    response = request_get(artwork_url, headers=headers, timeout=20)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    title = extract_pixiv_title(soup) or f"pixiv_{illust_id}"

    image_tag = soup.select_one('meta[property="og:image"]')
    image_url = image_tag.get("content") if image_tag else None
    if not image_url:
        image_url = f"https://embed.pixiv.net/artwork.php?illust_id={illust_id}"

    return title, image_url


def get_pixiv_title(illust_id):
    """返回缓存中的作品标题。"""
    title, _ = get_artwork_public_info(illust_id)
    return title


def parse_task(line):
    """解析“图片/作品 URL”或“URL|文件名”格式。"""
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    if "|" in line:
        url, filename = line.split("|", 1)
        return normalize_url(url), filename.strip() or None
    return normalize_url(line), None


def read_task_file(file_path):
    """逐行读取图片下载列表。"""
    with open(file_path, "r", encoding="utf-8-sig") as f:
        return [task for line in f if (task := parse_task(line))]


def get_tasks():
    """从命令行、交互输入或默认文本文件获取图片下载任务。"""
    args = sys.argv[1:]
    if args:
        return [task for arg in args if (task := parse_task(arg))]

    try:
        raw_url = input("请输入图片网址或 Pixiv 作品页网址：").strip()
    except EOFError:
        raw_url = ""

    if raw_url:
        task = parse_task(raw_url)
        if task:
            return [task]

    if os.path.exists(default_task_file):
        print(f"已读取批量列表：{default_task_file}")
        return read_task_file(default_task_file)

    return []


def get_output_filename(url, custom_name, index):
    """优先使用 Pixiv 作品标题，否则使用自定义名称或 URL 文件名。"""
    if custom_name:
        filename = clean_filename(custom_name)
        if not os.path.splitext(filename)[1]:
            filename += ".jpg"
        return f"{index:04d}_{filename}"

    pixiv_info = get_pixiv_image_info(url)
    if pixiv_info:
        illust_id, page_number, extension = pixiv_info
        try:
            title = get_pixiv_title(illust_id)
        except requests.RequestException:
            title = None

        if title:
            return clean_filename(f"{title}_p{page_number}{extension}")

    filename = clean_filename(unquote(os.path.basename(urlparse(url).path)))
    if not os.path.splitext(filename)[1]:
        filename += ".jpg"
    return f"{index:04d}_{filename}"


def download_image(url, output_name=None, index=1):
    """下载单张图片并保存到 downloads/images 目录。"""
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"}:
        raise ValueError("图片地址必须以 http:// 或 https:// 开头")

    with request_get(url, headers=headers, stream=True, timeout=30) as response:
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "").lower()
        if not content_type.startswith("image/"):
            raise ValueError(f"返回内容不是图片：{content_type or '未知类型'}")

        filename = output_name or get_output_filename(url, None, index)
        file_stem = os.path.splitext(filename)[0] or f"pixiv_{index}"
        part_file = os.path.join(folder, f".{file_stem}_{os.getpid()}.part")

        try:
            with open(part_file, "wb") as f:
                for chunk in response.iter_content(chunk_size=256 * 1024):
                    if chunk:
                        f.write(chunk)

            extension = validate_image(part_file)
            output_file = os.path.join(folder, f"{file_stem}{extension}")
            os.replace(part_file, output_file)
        except Exception:
            if os.path.exists(part_file):
                os.remove(part_file)
            raise

    print(f"图片已保存到：{output_file}")


def download_artwork(artwork_url, custom_name=None):
    """下载作品页公开提供的预览图。"""
    illust_id = get_pixiv_artwork_id(artwork_url)
    if not illust_id:
        raise ValueError("不是有效的 Pixiv 作品页 URL")

    title, image_url = get_artwork_public_info(illust_id)
    base_name = clean_filename(custom_name or title)

    print("当前为无需令牌模式，仅下载作品页公开预览图")
    download_image(image_url, output_name=f"{base_name}_p0")


def process_task(url, custom_name, index):
    """根据 URL 类型选择作品页下载或单张图片下载。"""
    if get_pixiv_artwork_id(url):
        download_artwork(url, custom_name)
    else:
        filename = get_output_filename(url, custom_name, index)
        download_image(url, output_name=filename, index=index)


if __name__ == "__main__":
    tasks = get_tasks()
    if not tasks:
        raise SystemExit("没有可下载的图片任务")

    success_count = 0
    failure_count = 0

    for index, (url, filename) in enumerate(tasks, start=1):
        try:
            process_task(url, filename, index)
            success_count += 1
        except Exception as error:
            failure_count += 1
            print(f"第 {index} 个任务下载失败：{error}")


    print(f"下载结束：成功 {success_count} 个任务，失败 {failure_count} 个任务")



