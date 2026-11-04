#!/usr/bin/env python3
"""检查配套 FreeRTOSConfig 的安全态和静态应用资源配置。"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="检查 FreeRTOS 安全态和资源配置")
    parser.add_argument("config", type=Path, help="FreeRTOSConfig.h 路径")
    parser.add_argument(
        "--library", type=Path,
        help="可选的 FreeRTOS 静态库；同时检查是否已按该配置重建",
    )
    args = parser.parse_args()

    try:
        content = args.config.read_text(encoding="utf-8")
    except OSError as error:
        parser.error(str(error))

    declaration_ok = re.search(
        r"extern\s+void\s+ApplicationFatalHalt\s*\(\s*void\s*\)\s*;",
        content,
    )
    macro_ok = re.search(
        r"#define\s+configASSERT\s*\([^)]*\)"
        r"(?:(?!#define)[\s\S])*?ApplicationFatalHalt\s*\(\s*\)",
        content,
    )
    if declaration_ok is None or macro_ok is None:
        print(
            "ERROR: configASSERT 未调用 ApplicationFatalHalt；"
            "请应用 freertos/FreeRTOSConfig.assert.patch 并重建内核库。"
        )
        return 1

    static_allocation_ok = re.search(
        r"#define\s+configSUPPORT_STATIC_ALLOCATION\s+1\b", content
    )
    timers_disabled = re.search(
        r"#define\s+configUSE_TIMERS\s+0\b", content
    )
    reserve_heap_is_small = re.search(
        r"#define\s+configTOTAL_HEAP_SIZE\s+"
        r"\(\(size_t\)\s*256\s*\)",
        content,
    )
    if (static_allocation_ok is None or timers_disabled is None or
            reserve_heap_is_small is None):
        print(
            "ERROR: FreeRTOS 未使用本框架的低占用配置；"
            "请应用 freertos/FreeRTOSConfig.resource.patch 并重建内核库。"
        )
        return 1

    if args.library is not None:
        try:
            library_stat = args.library.stat()
            config_stat = args.config.stat()
            library_content = args.library.read_bytes()
        except OSError as error:
            parser.error(str(error))

        if library_stat.st_mtime_ns < config_stat.st_mtime_ns:
            print(
                "ERROR: FreeRTOS 静态库早于 FreeRTOSConfig.h；"
                "请先重新构建 kernel 工程。"
            )
            return 1
        if b"ApplicationFatalHalt" not in library_content:
            print(
                "ERROR: FreeRTOS 静态库中没有 ApplicationFatalHalt 引用；"
                "请清理并重新构建 kernel 工程。"
            )
            return 1

    suffix = "，且静态库已重建" if args.library is not None else ""
    print(
        f"PASS: {args.config} 已接入安全态，已关闭未使用的 Timer Service，"
        f"备用堆为 256 B"
        f"{suffix}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
