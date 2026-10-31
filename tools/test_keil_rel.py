#!/usr/bin/env python3
"""keil_inject.rel：同盘相对路径；跨盘符（relpath 抛 ValueError，模拟 Windows C:/D:）退回绝对路径、不崩。"""
import os, pathlib, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import keil_inject as K
b = pathlib.Path("/tmp/a/MDK-ARM"); p = pathlib.Path("/tmp/a/src/x.c")
assert K.rel(p, b) == "..\\src\\x.c", K.rel(p, b)
orig = os.path.relpath
def boom(*a, **k): raise ValueError("path is on mount 'D:', start on mount 'C:'")
os.path.relpath = boom
try:
    got = K.rel(p, b)
finally:
    os.path.relpath = orig
assert got == str(p.resolve()).replace("/", "\\"), got
print("✓ keil_inject.rel：同盘相对、跨盘符退回绝对路径")
