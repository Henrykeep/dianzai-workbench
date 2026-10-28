export function matchNames(q: string, names: string[]): boolean[] {
  const pats = q.split(/[\s,]+/).filter(Boolean).map(w => new RegExp("^" + w.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*") + "$", "i"));
  return names.map((n, i) => pats.length ? pats.some(r => r.test(n)) : i < 4);
}
