import type { ToolCall } from "../types";

export const TOOL_NAMES_CN: Record<string, string> = {
  list_files: "查看目录",
  search_code: "搜索代码",
  read_file: "阅读文件",
  write_patch: "修改文件",
  run_tests: "运行测试",
  git_diff: "查看代码变更",
};

function asRecord(v: unknown): Record<string, unknown> | undefined {
  return v && typeof v === "object" ? (v as Record<string, unknown>) : undefined;
}

/** Build a human-readable Chinese description of a tool call from its result data. */
export function describeToolCall(call: ToolCall): string {
  const d = asRecord(call.data);
  const name = TOOL_NAMES_CN[call.tool] || `调用 ${call.tool}`;

  switch (call.tool) {
    case "list_files": {
      const count = d?.count ?? 0;
      const path = d?.path ? `「${d.path}」` : "工作目录";
      return `${name} ${path}（发现 ${count} 项）`;
    }
    case "search_code": {
      const pattern = d?.pattern ? `「${d.pattern}」` : "";
      const matches = d?.match_count ?? 0;
      return `${name} 正则 ${pattern} → ${matches} 处匹配`;
    }
    case "read_file": {
      const file = d?.file ? `「${d.file}」` : "文件";
      const lines = d?.lines_returned != null ? `返回 ${d.lines_returned} 行` : "";
      return `${name} ${file}${lines ? `（${lines}）` : ""}`;
    }
    case "write_patch": {
      const size = d?.size_bytes != null ? `，${d.size_bytes} 字节` : "";
      if (d && d.created_new_variant) {
        return `${name}「${d.original_file}」→ 写入新文件「${d.file}」（原文件保持不变）${size}`;
      }
      return `${name} 创建文件「${d?.file ?? "文件"}」${size}`;
    }
    case "run_tests": {
      const cmd = d?.command ? `「${d.command}」` : "测试命令";
      const exit = d?.exit_code != null ? `（退出码 ${d.exit_code}）` : "";
      return `${name} ${cmd}${exit}`;
    }
    case "git_diff": {
      const empty = d?.empty !== false;
      return `${name}（${empty ? "当前没有未提交的变更" : "存在未提交的变更"}）`;
    }
    default:
      return name;
  }
}
