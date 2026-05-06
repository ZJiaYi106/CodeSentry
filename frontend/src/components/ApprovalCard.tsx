import React from "react";
import type { ApprovalRequest } from "../types";

interface Props {
  approvals: ApprovalRequest[];
  onResolve: (approvalId: string, action: "approve" | "reject") => void;
  taskId: string | null;
}

const ApprovalCard: React.FC<Props> = ({ approvals, onResolve, taskId }) => {
  const pending = approvals.filter((a) => a.status === "pending");
  const resolved = approvals.filter((a) => a.status !== "pending");

  if (approvals.length === 0) return null;

  return (
    <div className="approvals">
      <h3>待审批</h3>

      {pending.length > 0 && (
        <div className="approval-pending">
          {pending.map((apr) => (
            <div key={apr.id} className="approval-item approval-pending-item">
              <div className="approval-header">
                <span className="approval-risk high">[{apr.risk.toUpperCase()}]</span>
                <span className="approval-tool">{apr.tool}</span>
              </div>
              <p className="approval-reason">{apr.reason}</p>
              <pre className="approval-args">
                {JSON.stringify(apr.arguments, null, 2)}
              </pre>
              <div className="approval-actions">
                <button
                  className="btn-approve"
                  onClick={() => onResolve(apr.id, "approve")}
                  disabled={!taskId}
                >
                  批准
                </button>
                <button
                  className="btn-reject"
                  onClick={() => onResolve(apr.id, "reject")}
                  disabled={!taskId}
                >
                  拒绝
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {resolved.length > 0 && (
        <div className="approval-resolved">
          {resolved.map((apr) => (
            <div key={apr.id} className={`approval-item approval-${apr.status}`}>
              <span className="approval-resolved-label">
                {apr.status === "approved" ? "✅" : "❌"}{" "}
                {apr.tool} — {apr.status === "approved" ? "已批准" : apr.status === "rejected" ? "已拒绝" : apr.status}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default ApprovalCard;
