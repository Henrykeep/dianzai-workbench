# third_party/vendored —— 直接搬用的外部代码（提交进仓库）

与 `third_party/` 下其它目录（官方 SDK，`tools/fetch_third_party.sh` 下载、不提交）不同，这里放**队友/开源项目里直接搬过来用的代码**，
尤其是 GPL/AGPL 这类传染性许可的代码，单独隔离，便于以后整体替换或删除。

规则（`tools/check_vendored.py` 在 `make check` 里强制）：
1. 每个子目录一个来源：必须有 `LICENSE`（原样复制）和 `SOURCE.md`（含 `Source: <repo>@<commit> <path>`、改了什么）。
2. 每个代码文件头部写 `Source: <repo>@<commit> <path>`。
3. 只搬"能独立成块"的部分并改造成本仓库分层；不整段粘贴巨石文件。
4. 仓库其它代码通过很薄的适配层调用它（例如 `app/sidecar/dzbench/tuning/`），删掉本目录时只影响那一层。
5. 在 `docs/参考来源.md` 登记。

许可：只收 MIT / BSD / Apache-2.0 / zlib 等宽松许可；GPL / LGPL / AGPL 或没有许可证的代码一律不进本目录（`tools/check_vendored.py` 强制）。
