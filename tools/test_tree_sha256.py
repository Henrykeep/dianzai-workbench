#!/usr/bin/env python3
"""tools/tree_sha256.py：LF 与 CRLF 检出、不同权限位 / 创建顺序得到同一指纹；任何真实改动都会改变指纹。"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tree_sha256 import tree_sha256

FILES = {'Inc/a.h': b'#define A 1\n/* x */\n', 'Inc/sub/b.h': b'int b;\n\nint c;\n', 'Inc/Z.h': b'\x00\x01bin\n'}

def make(files, crlf=False, order=None, mode=0o644):
    d = tempfile.mkdtemp()
    for rel in (order or list(files)):
        p = os.path.join(d, *rel.split('/'))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        data = files[rel].replace(b'\n', b'\r\n') if crlf else files[rel]
        open(p, 'wb').write(data); os.chmod(p, mode)
    return d

base = tree_sha256(make(FILES), ['Inc'])
assert tree_sha256(make(FILES, crlf=True), ['Inc']) == base, 'CRLF 检出指纹不同'
assert tree_sha256(make(FILES, order=list(reversed(FILES)), mode=0o755), ['Inc']) == base, '顺序/权限位影响指纹'
for mut in ({**FILES, 'Inc/a.h': b'#define A 2\n/* x */\n'},
            {**FILES, 'Inc/extra.h': b'\n'},
            {k: v for k, v in FILES.items() if k != 'Inc/Z.h'},
            {('Inc/c.h' if k == 'Inc/a.h' else k): v for k, v in FILES.items()}):
    assert tree_sha256(make(mut), ['Inc']) != base, '篡改未被发现'
print('✓ tree_sha256：LF/CRLF/顺序/权限位一致，改内容/增删/改名均可发现')
