"""按协处理板 board.yaml 的 channels/params 收发数据——与 MCU 侧 gen_coproc.py 生成的 C 代码使用同一份描述。"""
from . import protocol as P


def _load_yaml(path):
    try:
        import yaml
    except ImportError as e:  # 协处理器上没装 PyYAML 时，也可以直接传入 dict
        raise RuntimeError("读取 board.yaml 需要 PyYAML（pip install pyyaml），或改用 Link(cfg_dict, ...)") from e
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


class Link:
    def __init__(self, board: dict, transport):
        cp = board["coprocessor"]
        self.channels = {c["name"]: c for c in cp["channels"]}
        self.by_id = {c["id"]: c for c in cp["channels"]}
        self.params = {p["name"]: p for p in cp.get("params") or []}
        self.t = transport
        self.parser = P.Parser()
        self.seq = 0

    @classmethod
    def from_board(cls, path, transport):
        return cls(_load_yaml(path), transport)

    def send(self, channel: str, **values):
        ch = self.channels[channel]
        missing = [f["name"] for f in ch["fields"] if f["name"] not in values]
        if missing:
            raise ValueError(f"通道 {channel} 缺少字段 {missing}")
        self.t.write(P.encode(P.DATA, ch["id"], self.seq, P.pack_fields(ch["fields"], values)))
        self.seq = (self.seq + 1) & 0xFF

    def heartbeat(self):
        self.t.write(P.encode(P.HEARTBEAT, 0, self.seq, b""))
        self.seq = (self.seq + 1) & 0xFF

    def poll(self):
        """读走已到达的字节，返回 [(通道名或 ('param', 名字) / 'heartbeat', 值字典)]。未知通道/长度不符的帧丢弃并计数。"""
        out = []
        for kind, id_, seq, payload in self.parser.feed(self.t.read()):
            if kind == P.DATA and id_ in self.by_id:
                ch = self.by_id[id_]
                if len(payload) == sum(P.struct.calcsize("<" + P.FMT[f["type"]]) for f in ch["fields"]):
                    out.append((ch["name"], P.unpack_fields(ch["fields"], payload)))
                    continue
            elif kind == P.HEARTBEAT:
                out.append(("heartbeat", {"seq": seq}))
                continue
            elif kind == P.PARAM_SET:
                # 预留：参数下发（MCU/工作台 -> 协处理器）。格式：id 即 params[].id，payload 为按 type 打包的值
                p = next((x for x in self.params.values() if x["id"] == id_), None)
                if p is not None:
                    out.append((("param", p["name"]), P.unpack_fields([{"name": "value", "type": p["type"]}], payload)))
                    continue
            self.parser.bad += 1
        return out
