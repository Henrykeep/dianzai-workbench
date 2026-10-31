// 项目页第一入口：一句话需求 → 交给 Agent 建工程。未配置大模型时输入框照常显示，提交后引导去配置。
export function initPjAsk(call: (op: string, a?: any) => Promise<any>, go: (s: any) => void) {
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
  $("pj-sample").onclick = () => {
    $<HTMLInputElement>("pf-code").value = "2026H";
    $<HTMLInputElement>("pf-dest").value = "examples/2026H_ball";
    ["pf-code", "pf-dest"].forEach(id => $(id).dispatchEvent(new Event("input", { bubbles: true })));
    st.textContent = "已载入示例项目 examples/2026H_ball · 从下方第 1 步「读需求」开始。";
    go("项目");
  };
}
