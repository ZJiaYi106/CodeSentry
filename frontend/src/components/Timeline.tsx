import React from "react";
import type { TimelineEvent } from "../types";

interface Props {
  events: TimelineEvent[];
}

const AGENT_COLORS: Record<string, string> = {
  planner: "#7c3aed",
  tool_executor: "#2563eb",
  observer: "#059669",
  reflector: "#d97706",
  summarizer: "#dc2626",
  orchestrator: "#7c3aed",
  system: "#6b7280",
};

const TYPE_ICONS: Record<string, string> = {
  plan: "\u{1F4CB}",
  tool_call: "\u{1F527}",
  observation: "\u{1F441}",
  reflection: "\u{1F9E0}",
  approval: "\u{1F6A6}",
  summary: "\u{1F4DD}",
};

const Timeline: React.FC<Props> = ({ events }) => {
  if (events.length === 0) return null;

  return (
    <div className="timeline">
      <h3>Agent Timeline</h3>
      <div className="timeline-list">
        {events.map((evt) => (
          <div key={evt.id} className="timeline-item">
            <span
              className="timeline-dot"
              style={{ background: AGENT_COLORS[evt.agent] || "#6b7280" }}
            />
            <span className="timeline-icon">{TYPE_ICONS[evt.type] || "\u{25CF}"}</span>
            <span className="timeline-agent" style={{ color: AGENT_COLORS[evt.agent] || "#6b7280" }}>
              [{evt.agent}]
            </span>
            <span className="timeline-content">{evt.content}</span>
            <span className="timeline-time">{new Date(evt.timestamp).toLocaleTimeString()}</span>
          </div>
        ))}
      </div>
    </div>
  );
};

export default Timeline;
