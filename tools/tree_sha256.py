#!/usr/bin/env python3
"""目录内容指纹（跨平台）：对排好序的相对 POSIX 路径 + 文件内容算 sha256。
- 路径按 UTF-8 字节排序，与 locale / find 顺序 / 大小写无关的排序；
- 忽略文件权限位、mtime；
- 内容中的 CRLF 统一成 LF（Windows 上 git autocrlf / 编辑器转换不算篡改，其它任何字节改动都会被发现）。
用法：tree_sha256.py <根目录> <子目录或文件>...
"""
import hashlib, os, sys

def file_digest(p):
    with open(p, 'rb') as f:
        data = f.read()
    return hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()

def tree_sha256(root, paths):
    files = []
    for rel in paths:
        top = os.path.join(root, rel)
        if os.path.isfile(top):
            files.append(rel.replace(os.sep, '/'))
            continue
        for d, _, names in os.walk(top):
            for n in names:
                files.append(os.path.relpath(os.path.join(d, n), root).replace(os.sep, '/'))
    h = hashlib.sha256()
    for rel in sorted(set(files), key=lambda s: s.encode('utf-8')):
        h.update(rel.encode('utf-8') + b'\0' + file_digest(os.path.join(root, rel)).encode() + b'\n')
    return h.hexdigest()

if __name__ == '__main__':
    print(tree_sha256(sys.argv[1], sys.argv[2:]))
