本项目致力于提供一套方便的工具，用于浏览部分Anime Provider。诸如各booru、pixiv、eh。

同时提供标签、登录、API/Cookie/批量下载功能，适用于对大量图片数据集有要求的AI Trainer

<s>以及满足某些屯屯党，或者是某些单纯想把整个互联网下载下来的怪胎的需求</s>

例如，需要从Danbooru批量分标签抓取大量数据的研究员，等。

部分Provider提供了便捷的下载方式，例如 Danbooru/Gelbooru提供了API可供下载图片、Ehentai允许你消耗代币进行ZIP归档下载，同时规避爬虫惩罚。

目标：

1. 分析已有的开源项目，一一对应并制作Python库（单文件）
2. 使用Flet，进行跨平台打包，打包为跨平台应用程序，以及可供服务器部署的应用程序。


参考目标：
Pix-Ez Viewer
Imgur Grabber
Ehviewer
Venera
Mihon(原Tachiyomi)
Emby


免责声明：用户及使用者均已成年，且目标网站已过滤了不符合普世价值的内容，且目标网站并不含有版权相关资源。

---

计划实现的内容：

1. 抓取器。分别位于对应的Provider的库里。
2. OS交互工具。安卓/Windows/Linux/Web对文件系统的交互方式并不相同。我们需要合适程度的抽象。
3. 针对海量文件的特殊优化：考虑到部分需求：比如大批量下载图像文件，我们需要更加妥善的文件存储方式。


## 文件存储-Booru：

自Booru上下载的图像文件，一般使用Hash进行命名。HatH（Ehentai维护的一套种子服务）会使用图像hash的前四个字符，用于索引。

例如， ABCDEF.png, 会位于 /AB/CD 目录里。 上述行为可以有效将文件分散到不同的目录下。

不过，EH只用了2+2位字符来进行索引。我们可以进一步： 假设一个目录下的图片超过了256张，那么，就考虑新建子目录，将当前目录下的所有东西都塞进去。 0-F

这就使得我们的文件以一种类似二叉树的方式被排列了。

## 文件存储：Pixiv-Ez
有待研究，因为不太经常用。

## 文件存储-EHentai：
EHViewer下载画廊有三种方式：

方法1：逐图片Fetch。 
    这种行为会增加EH本就贫瘠的服务器负担，且会导致你的账户/IP被限制。很不优雅。但如果只是用于图库预览，可以少量进行抓取。

方法2：使用档案下载（Archieve Download）。
    这种下载方式要求你登陆账号，且账号内有足够的代币 (EH管这个叫做GP)。此时，你可以选择下载原图/或者重新采样后的包。
    你将下载一个包含整个画廊内所有文件的压缩包。
    但由于没有画廊的元数据，因此你最好在其他地方准备提供并存储它的元数据，以防画廊需要更新/你的训练prompt需要输入画廊的TAG。

方法3： Hentai at Home
    效果和档案下载类似，只是会下载到你托管的HatH服务器上。暂不讨论。

我们将默认用户拥有账户，且内部有代币。获得代币的方法很简单：托管一台运行着HatH的VPS即可获得稳定的代币来源，可以说是过量的。


#### 分析任务：

我们将通过分析 Venera 和 EHviewer 的源代码，将图像下载、获取画廊、搜索 等方法，抽象为Python函数。

我们将分析EH的Kotlin工程、以及Venera中负责grab的部分。参考eh_grabber.js。



## 文件存储：其他：

TODO...


---

## 开发环境备注：

### Shell：

本机通过 scoop 安装了 MSYS2/MinGW64 包，提供了基于 MinGW 编译的 GNU coreutils + bash/sh（`uname` 显示 `MINGW64_NT`），运行在 Windows 原生，不依赖 WSL。

但 Windows 默认将 `bash` 命令 wrapped 到 WSL2，而本机 WSL 不可用（RAM不足等原因），因此**不要直接使用 `bash`**。

若需要类 Unix shell 环境（解决 PowerShell 引号转义、编码等问题），请使用 `sh`（未被 WSL 拦截，会正确调用 MSYS2 的 shell）：

```
sh -c "your command here"
```

并设置 UTF-8 编码以正确显示中文/日文：

```
sh -c "export PYTHONIOENCODING=utf-8 LANG=zh_CN.UTF-8; python script.py"
```

PowerShell 5.1 的默认编码为 GBK，会导致非 ASCII 字符乱码。通过 `sh -c` 配合环境变量可以规避此问题。

