# FletViewer

## Windows / Linux

部署说明：需要 Python 3.10 或更高版本。

安装依赖：

```bash
python -m pip install -r requirements.txt
```

运行桌面应用：

```bash
python main.py
```

## Web 服务

依赖安装完成后运行：

```bash
python dev_web.py
```

默认地址：

```text
http://localhost:8765
```

## Android APK

安装依赖并准备好 Android SDK 后，在项目根目录运行：

```bash
flet build apk
```

构建产物位于：

```text
build/apk/
```
