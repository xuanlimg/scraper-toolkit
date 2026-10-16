# Python 采集脚本合集

一组可直接运行的 Python 采集 / 下载脚本，覆盖**图片、视频、音频、小说**四类目标，
每个脚本都是单文件、可独立复制使用。

和「能跑就行」的练手脚本不同，这里的重点是**采集类脚本的工程化写法**：
请求重试、限速、临时文件原子替换、内容类型校验、失败不产生损坏文件。

## 脚本清单

| 脚本 | 用途 | 核心写法 |
| --- | --- | --- |
| `scripts/pixiv_image_downloader.py` | 下载 Pixiv 作品页公开预览图，支持批量列表 | 连接复用 + 429/5xx 重试、请求限速、Pillow 校验图片、`lru_cache` 缓存作品标题 |
| `scripts/m3u8_video_downloader.py` | 解析 m3u8 播放列表，下载分片并合并为完整视频 | 主播放列表按码率选最高一路、AES-128 加密流显式报错、分片指数退避重试 |
| `scripts/music_downloader.py` | 下载音频直链并保存为标准音频文件 | 流式写入、按 `Content-Type` 推断后缀、拦截失效链接返回的 HTML |
| `scripts/novel_downloader.py` | 抓取小说目录与章节正文（示例站点：刺猬猫 WAP） | Cookie 走环境变量、章节序号前缀、逐章限速、付费/未登录章节跳过且不写空文件 |

## 环境准备

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1      # Windows
pip install -r requirements.txt
```

依赖：`requests`、`beautifulsoup4`、`tqdm`、`Pillow`（Python 3.10+）。

## 使用方法

### 1. 图片下载

```bash
# 单个链接（作品页或图片直链）
python scripts/pixiv_image_downloader.py https://www.pixiv.net/artworks/12345678

# 多个链接 / 自定义文件名（用 | 分隔）
python scripts/pixiv_image_downloader.py "https://i.pximg.net/...jpg|封面"

# 批量：把链接逐行写进 image_urls.txt 后直接运行，无参数时自动读取
python scripts/pixiv_image_downloader.py
```

> 未使用访问令牌，只能获取作品页公开的预览图；保存目录 `downloads/images/`。

### 2. m3u8 视频下载

```bash
python scripts/m3u8_video_downloader.py "https://example.com/xxx/index.m3u8" --name 课程01.ts
```

脚本会自动选择码率最高的一路，分片逐个下载后合并；保存目录 `downloads/video/`。

### 3. 音频直链下载

```bash
python scripts/music_downloader.py "https://example.com/song.m4a" 歌曲名
```

保存目录 `downloads/music/`；链接失效（返回网页/JSON）时会直接报错，不会存下假文件。

### 4. 小说章节抓取

```bash
python scripts/novel_downloader.py "https://wap.ciweimao.com/book/100419416" --delay 1.5
```

需要登录才能看的章节，先把浏览器 Cookie 放进环境变量：

```powershell
$env:CIWEIMAO_COOKIE = "你的 Cookie"
```

保存目录 `downloads/novel/`，章节文件带 4 位序号前缀，方便按顺序合并。

## 通用工程写法

这些脚本共用了同一套处理套路，方便直接搬到别的采集任务里：

1. **连接复用**：`requests.Session()` + `HTTPAdapter`，减少重复握手开销；
2. **自动重试**：`urllib3.Retry` 处理 429 / 5xx，并遵守 `Retry-After`；
3. **主动限速**：相邻请求之间保证最小间隔，降低被限流的概率；
4. **原子写入**：先写 `.part` 临时文件，全部成功后再 `os.replace`，避免半个文件被当成成品；
5. **内容校验**：按 `Content-Type` 或 Pillow 校验真实类型，防止把 HTML 错误页存成媒体文件；
6. **不写死敏感信息**：Cookie 等凭证统一走环境变量，代码里不出现个人账号信息。

## 免责声明

- 本项目仅用于**编程学习与技术交流**，示例代码用于演示 HTTP 请求、分片合并、内容校验等通用技术。
- 请遵守目标网站的 `robots.txt`、用户协议与版权规定，**只下载你有权保存的内容**。
- 请勿用于绕过付费 / 登录限制、批量抓取或任何商业用途；因使用不当产生的后果由使用者自行承担。
- 仓库不包含任何抓取结果数据，`downloads/` 目录已在 `.gitignore` 中排除。

## License

[MIT](LICENSE)
