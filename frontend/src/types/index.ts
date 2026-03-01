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
  id: string;
  tool: string;
  arguments: Record<string, unknown>;
  result: string | null;
  risk: "low" | "medium" | "high";
  status: "pending" | "approved" | "rejected" | "completed" | "error";
  duration_ms: number;
  timestamp: string;
}

/** An approval request sent to the frontend. */
export interface ApprovalRequest {
  id: string;
  tool: string;
  arguments: Record<string, unknown>;
  risk: "low" | "medium" | "high";
  reason: string;
  timestamp: string;
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
  | { type: "plan"; data: { steps: PlanStep[] } }
  | { type: "tool_call"; data: ToolCall }
  | { type: "approval_required"; data: ApprovalRequest }
  | { type: "observation"; data: { content: string; agent: string } }
  | { type: "reflection"; data: { content: string; agent: string } }
  | { type: "progress"; data: { message: string; percent: number } }
  | { type: "summary"; data: { changes: string; test_results: string } }
  | { type: "error"; data: { message: string } }
  | { type: "done"; data: { task_id: string } };
