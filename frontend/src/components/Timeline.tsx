import React from "react";
import type { TimelineEvent } from "../types";

interface Props {
  events: TimelineEvent[];
  running: boolean;
}

const AGENT_COLORS: Record<string, string> = {
  "规划者": "#3b82f6",
  "工具执行": "#6366f1",
  "观察者": "#10b981",
  "反思者": "#f59e0b",
  "总结者": "#ef4444",
  "编排器": "#3b82f6",
  "系统": "#94a3b8",
  "仓库分析师": "#3b82f6",
  "代码实现者": "#8b5cf6",
  "代码审查者": "#10b981",
};

const TYPE_ICONS: Record<string, string> = {
  plan: "\u{1F4CB}",
  tool_call: "\u{1F527}",
  observation: "\u{1F441}",
  reflection: "\u{1F9E0}",
  approval: "\u{1F6A6}",
  summary: "\u{1F4DD}",
};

const Timeline: React.FC<Props> = ({ events, running }) => {
  if (events.length === 0) return null;

  const lastIdx = events.length - 1;

  return (
    <div className="timeline">
      <h3>
        智能体时间线
        {running && <span className="timeline-live-badge">运行中</span>}
      </h3>
      <div className="timeline-list">
        {events.map((evt, i) => {
          const isLatest = i === lastIdx && running;
          return (
            <div key={evt.id} className={`timeline-item ${isLatest ? "timeline-item-latest" : ""}`}>
              <span
                className={`timeline-dot ${isLatest ? "timeline-dot-pulse" : ""}`}
                style={{ background: AGENT_COLORS[evt.agent] || "#94a3b8" }}
              />
              <span className="timeline-icon">{TYPE_ICONS[evt.type] || "\u{25CF}"}</span>
              <span className="timeline-agent" style={{ color: AGENT_COLORS[evt.agent] || "#94a3b8" }}>
                {evt.agent}
              </span>
              <span className="timeline-content">{evt.content}</span>
              <span className="timeline-time">
                {new Date(evt.timestamp).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default Timeline;
