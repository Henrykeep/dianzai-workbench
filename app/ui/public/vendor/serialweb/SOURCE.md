# SerialWeb（原样拷贝，未修改）
- 来源：https://github.com/Conductance-lab/SerialWeb @ ff84c5d43dde6b6c49cddc1b7b01f9c55e3ece1a（2026-10-20）
- 许可：AGPL-3.0（见同目录 LICENSE）。本目录文件逐字节保持原样。
- 用法：工具箱「串口调试」页以 iframe srcdoc 加载 index.html，并在最前注入 serialslot.ts 的 navigator.serial 适配层（经 sidecar ws 收发，不用 Web Serial 直连硬件）。
- 路径与 vendor-tools 分支约定一致（vendor/serialweb），合并时去重即可。
