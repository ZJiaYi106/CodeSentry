import React from "react";
import type { TimelineEvent } from "../types";

interface Props {
  plan: TimelineEvent | null;
}

const PlanView: React.FC<Props> = ({ plan }) => {
  if (!plan) return null;

  let steps: { id: string; description: string; tool_name: string | null; status: string }[] = [];
  try {
    const data = JSON.parse(plan.content);
    steps = data.steps || [];
  } catch {
    return null;
  }

  if (steps.length === 0) return null;

  return (
    <div className="plan-view">
      <h3>Execution Plan</h3>
      <div className="plan-steps">
        {steps.map((step) => (
          <div key={step.id} className={`plan-step plan-step-${step.status}`}>
            <span className="step-status">
              {step.status === "completed" ? "✅" : step.status === "failed" ? "❌" : step.status === "running" ? "⏳" : "○"}
            </span>
            <span className="step-desc">{step.description}</span>
            {step.tool_name && <span className="step-tool">{step.tool_name}</span>}
          </div>
        ))}
      </div>
    </div>
  );
};

export default PlanView;
