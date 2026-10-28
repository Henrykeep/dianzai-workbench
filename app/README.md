# app/ — 电赛工作台桌面程序

见 [docs/17-桌面工作台.md](../docs/17-桌面工作台.md)。

| 目录 | 内容 |
|---|---|
| sidecar/ | Python 侧车 dzbench（`python -m dzbench`），tests/ 为 pytest（`make test` 会跑） |
| ui/ | Vite + TS + uPlot 界面（`npm ci && npm run build`） |
| src-tauri/ | Tauri v2 外壳（未测） |
| tools/shot.py | 起侧车+仿真板，playwright 截图 |
