import { exampleCandidates, type PortLike } from "./examples";
// 项目页第一入口：一句话需求 → 交给 Agent 建工程。未配置大模型时输入框照常显示，提交后引导去配置。
export function initPjAsk(call: (op: string, a?: any) => Promise<any>, go: (s: any) => void, ports: () => PortLike[] | undefined = () => [], quiet?: (op: string, a?: any) => Promise<any>) {
  const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
  const st = $("pj-ask-st");
  $<HTMLFormElement>("pj-ask").onsubmit = async e => {
    e.preventDefault();
    const t = $<HTMLInputElement>("pj-ask-in").value.trim();
    if (!t) { st.textContent = "请输入需求描述。"; return; }
    const c = await call("agent_config").catch(() => null);
    if (!c?.configured) { st.textContent = "未配置大模型 · 处理：在打开的窗口中完成配置后，再次点击「新建工程」。"; $("ag-cfg").click(); return; }
    st.textContent = "已提交 · Agent 正在生成需求与方案，进度见右侧 Agent 栏。";
    $<HTMLInputElement>("ag-in").value = `新建项目：${t}。请按项目页五步（读需求 → 选型 → 导入工程 → 资源分配 → 生成）推进，每步写入前请我确认。`;
    $<HTMLFormElement>("ag-form").requestSubmit();
  };
  // 「从示例开始」：例题只读，复制出一个新项目（op project_switch_example，回 project_forked 由 main 显示）
  $("pj-sample").onclick = async () => {
    st.textContent = "正在从内置示例新建项目…";
    st.textContent = await forkFirstExample(quiet ?? call, exampleCandidates(ports()));
    go("项目");
  };
}

// 按后端给的候选顺序试，第一个被后端认成例题的就用；都不是 → 说明原因
export async function forkFirstExample(call: (op: string, a?: any) => Promise<any>, cands: string[]): Promise<string> {
  for (const ex of cands) {
    try { const r = await call("project_switch_example", { example: ex }); return r?.message_zh ?? `已基于示例新建 ${r?.project ?? ""}`; }
    catch (e: any) { if (e?.code !== "bad_example" && e?.reason !== "bad_example") return e?.message_zh ?? ""; }
  }
  return "没有找到内置示例 · 原因：后端未列出仿真例题 · 处理：先在「连接」里刷新端口，再点击「从示例开始」。";
}
