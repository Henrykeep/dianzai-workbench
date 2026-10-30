// 构建时打入入口规则表原文（单一来源，避免前端另抄一份 ready 状态）
import raw from "../../../docs/dev/entrypoints.yaml?raw";
import { setEntrypoints } from "./entry";
setEntrypoints(raw);
