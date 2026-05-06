import React from "react";
import type { ToolCall } from "../types";

interface Props {
  calls: ToolCall[];
}

const RISK_COLORS: Record<string, string> = {
  low: "#10b981",
  medium: "#f59e0b",
  high: "#ef4444",
};

const ToolCallCard: React.FC<Props> = ({ calls }) => {
  if (calls.length === 0) return null;

  return (
    <div className="tool-calls">
      <h3>工具调用（{calls.length}）</h3>
      <div className="tool-call-grid">
        {calls.map((call, i) => (
          <div key={call.id || i} className="tool-call-item">
            <div className="tool-call-header">
              <span className="tool-name">{call.tool}</span>
              <span
                className="tool-risk"
                style={{ color: RISK_COLORS[call.risk] || "#6b7280" }}
              >
                [{call.risk}]
              </span>
              {call.status && (
                <span className={`tool-status tool-status-${call.status}`}>
                  {call.status}
                </span>
              )}
            </div>
            <div className="tool-call-body">
              <pre>{JSON.stringify(call.arguments, null, 2) || "{}"}</pre>
              {call.result && (
                <div className="tool-result">
                  <pre>{typeof call.result === "string" ? call.result : JSON.stringify(call.result, null, 2)}</pre>
                </div>
              )}
            </div>
            <div className="tool-call-footer">
              <span>{call.duration_ms?.toFixed(1)}ms</span>
              <span>{new Date(call.timestamp).toLocaleTimeString()}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default ToolCallCard;
