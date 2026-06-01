import React, { useState } from "react";
import type { ToolCall } from "../types";
import { describeToolCall, TOOL_NAMES_CN } from "../lib/describe";

interface Props {
  calls: ToolCall[];
}

const RISK_COLORS: Record<string, string> = {
  low: "#10b981",
  medium: "#f59e0b",
  high: "#ef4444",
};

const RISK_CN: Record<string, string> = {
  low: "低风险",
  medium: "中风险",
  high: "高风险",
};

const ArrowIcon: React.FC<{ open: boolean }> = ({ open }) => (
  <svg
    className={`tool-calls-arrow ${open ? "tool-calls-arrow-open" : ""}`}
    width="16"
    height="16"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2.5"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <polyline points="6 9 12 15 18 9" />
  </svg>
);

const ToolCallCard: React.FC<Props> = ({ calls }) => {
  const [expanded, setExpanded] = useState(false);

  if (calls.length === 0) return null;

  const toggle = () => setExpanded((v) => !v);

  return (
    <div className={`tool-calls ${expanded ? "tool-calls-expanded" : ""}`}>
      <div
        className="tool-calls-header"
        onClick={toggle}
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            toggle();
          }
        }}
      >
        <h3>工具调用（{calls.length}）</h3>
        <ArrowIcon open={expanded} />
      </div>

      {!expanded && (
        <div className="tool-calls-preview">
          最近：{describeToolCall(calls[calls.length - 1])}
          {calls[calls.length - 1].success === false ? " ✗" : " ✓"}
        </div>
      )}

      {expanded && (
        <div className="tool-call-grid">
          {calls.map((call, i) => {
            const risk = String(call.risk_level || call.risk || "low");
            const failed = call.success === false;
            return (
              <div key={call.id || i} className="tool-call-item">
                <div className="tool-call-header">
                  <span className="tool-name">
                    {TOOL_NAMES_CN[call.tool] || call.tool}
                  </span>
                  <span
                    className="tool-risk"
                    style={{ color: RISK_COLORS[risk] || "#6b7280" }}
                  >
                    {RISK_CN[risk] || risk}
                  </span>
                  {call.agent && <span className="tool-agent">{call.agent}</span>}
                  <span
                    className={`tool-status ${failed ? "tool-status-failed" : "tool-status-completed"}`}
                  >
                    {failed ? "失败" : "成功"}
                  </span>
                </div>
                <div className="tool-call-body">
                  <div className="tool-call-desc">{describeToolCall(call)}</div>
                  {call.error && <div className="tool-call-error">{call.error}</div>}
                  {call.data && (
                    <details className="tool-result">
                      <summary>查看返回数据</summary>
                      <pre>{JSON.stringify(call.data, null, 2)}</pre>
                    </details>
                  )}
                </div>
                <div className="tool-call-footer">
                  <span>{call.duration_ms != null ? `${call.duration_ms.toFixed(0)}ms` : ""}</span>
                  <span>{call.timestamp ? new Date(call.timestamp).toLocaleTimeString() : ""}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default ToolCallCard;
