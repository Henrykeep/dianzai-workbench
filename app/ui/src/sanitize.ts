// #90 Agent 回复里漏出来的工具调用标记：保守地只删明确的标记，正文一个字不改
const PAIRS: RegExp[] = [
  /<tool_call>[\s\S]*?(<\/tool_call>|$)/g,
  /<function_calls>[\s\S]*?(<\/function_calls>|$)/g,
  /<function=[\w.-]+>[\s\S]*?(<\/function>|$)/g,
  /<\|tool_calls?_(?:section_)?begin\|>[\s\S]*?(<\|tool_calls?_(?:section_)?end\|>|$)/g,
  /```(?:tool_call|tool_code|function_call)\b[\s\S]*?(```|$)/g,
  /\[TOOL_CALLS\][^\n]*/g,
];
const TOKENS = /<\|(?:tool_call|tool_calls|tool_sep|tool_call_argument_begin|tool_response|tool_output|python_tag|eom_id|eot_id|im_end|im_start)[^|<>]{0,40}\|>|<\/?(?:tool_call|tool_response)>/g;
export function stripToolMarkup(s: string): string {
  if (!s || !/[<\[`]/.test(s)) return s;
  let o = s;
  for (const re of PAIRS) o = o.replace(re, "");
  o = o.replace(TOKENS, "");
  return o === s ? s : o.replace(/\n{3,}/g, "\n\n").trim();
}
