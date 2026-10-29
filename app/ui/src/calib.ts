// 单位标定（纯函数，可单测）：schema 字段的 cal = {unit, pts: [[原始, 物理], ...], mode?: linear|piecewise}。
// linear = 多点最小二乘直线（两点就是过两点）；piecewise = 按原始值排序后分段线性插值，两端用端段外推。
// 设定值字段（ref_for）没写 cal 时继承被控量的 cal，保证曲线和虚线同单位。
export type Cal = { unit: string; pts: [number, number][]; mode?: "linear" | "piecewise" };

export function calFn(c: Cal): (x: number) => number {
  const p = [...c.pts].sort((a, b) => a[0] - b[0]);
  if (c.mode === "piecewise") return x => {
    let k = 0; while (k < p.length - 2 && x > p[k + 1][0]) k++;
    const [x0, y0] = p[k], [x1, y1] = p[k + 1];
    return y0 + (x - x0) * (y1 - y0) / (x1 - x0);
  };
  const n = p.length, mx = p.reduce((s, q) => s + q[0], 0) / n, my = p.reduce((s, q) => s + q[1], 0) / n;
  const k = p.reduce((s, q) => s + (q[0] - mx) * (q[1] - my), 0) / p.reduce((s, q) => s + (q[0] - mx) ** 2, 0);
  return x => my + k * (x - mx);
}

// 每个字段一个换算函数（无 cal → null）；ref_for 字段继承目标的 cal
export function calMap(fields: { name: string; ref_for?: string; cal?: Cal }[]): Map<string, { f: (x: number) => number; unit: string }> {
  const m = new Map<string, { f: (x: number) => number; unit: string }>(), by = new Map(fields.map(f => [f.name, f]));
  for (const f of fields) {
    const c = f.cal ?? (f.ref_for ? by.get(f.ref_for)?.cal : undefined);
    if (c) m.set(f.name, { f: calFn(c), unit: c.unit });
  }
  return m;
}
