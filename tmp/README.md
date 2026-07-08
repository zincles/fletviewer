# tmp 实验区

`tmp/` 是隔离实验区，不属于正式应用；长期规则和实验结论已迁入根目录 `AGENTS.md`，这里仅保留可运行的 probe、实验库和本地缓存。

目录：`tmp/lib/` 放实验性 Python 库，`tmp/probes/` 放验证脚本和 notebook，`tmp/.cache/` 放本地 profile/cookie 缓存且必须保持 gitignore。

不要从 `app/` 或正式 provider 直接 import `tmp/` 代码；迁移前先按 `AGENTS.md` 检查依赖、敏感信息、协议边界和 Android 打包风险。
