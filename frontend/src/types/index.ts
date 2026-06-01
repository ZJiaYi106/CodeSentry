// CodeSentry Frontend Types

/** A single step in the task plan. */
export interface PlanStep {
  id: string;
  description: string;
  status: "pending" | "running" | "completed" | "failed";
  agent: string;
}

/** A tool call entry. */
export interface ToolCall {
  id?: string;
  tool: string;
  arguments?: Record<string, unknown>;
  data?: Record<string, unknown>;
  result?: string | null;
  risk?: "low" | "medium" | "high" | string;
  risk_level?: "low" | "medium" | "high" | string;
  success?: boolean;
  error?: string | null;
  status?: "pending" | "approved" | "rejected" | "completed" | "error" | string;
  duration_ms?: number;
  timestamp?: string;
  agent?: string;
}

/** An approval request sent to the frontend. */
export interface ApprovalRequest {
  id: string;
  tool: string;
  arguments: Record<string, unknown>;
  risk: "low" | "medium" | "high";
  reason: string;
  timestamp: string;
  status?: "pending" | "approved" | "rejected" | "auto_approved";
}

/** A timeline event for the agent activity log. */
export interface TimelineEvent {
  id: string;
  type: "plan" | "tool_call" | "observation" | "reflection" | "approval" | "summary";
  content: string;
  agent: string;
  timestamp: string;
}

/** SSE event types from the backend. */
export type SSEEvent =
  | { type: "ping"; data: { t: string } }
  | { type: "plan"; data: { steps: PlanStep[] } }
  | { type: "tool_call"; data: ToolCall }
  | { type: "approval_required"; data: ApprovalRequest }
  | { type: "observation"; data: { content: string; agent: string } }
  | { type: "reflection"; data: { content: string; agent: string } }
  | { type: "progress"; data: { message: string; percent: number } }
  | { type: "summary"; data: { changes: string; test_results: string } }
  | { type: "error"; data: { message: string } }
  | { type: "done"; data: { task_id: string } };
