# FletViewer

FletViewer 是使用 Python 和 Flet 构建的 Anime Provider 浏览、阅读和下载工具。需要 Python 3.10 或更高版本。

## 桌面运行

```bash
python -m pip install -e .
python main.py
```

## Web 运行

```bash
python -m pip install -e ".[web]"
flet run --web --recursive
```

Web 服务默认适用于可信网络；公开部署前请配置反向代理、TLS 和认证。

## Android 构建

```bash
flet build apk
```

APK 位于 `build/apk/app-release.apk`。
