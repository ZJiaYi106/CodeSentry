import { useEffect, useRef, useCallback, useState } from "react";
import type { SSEEvent, TimelineEvent, ApprovalRequest, ToolCall } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

interface UseSSEReturn {
  events: TimelineEvent[];
  plan: TimelineEvent | null;
  toolCalls: ToolCall[];
  approvals: ApprovalRequest[];
  summary: string | null;
  error: string | null;
  connected: boolean;
  startTask: (task: string, workspace?: string) => Promise<string>;
  resolveApproval: (taskId: string, approvalId: string, action: "approve" | "reject") => Promise<void>;
}

export function useSSE(): UseSSEReturn {
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [plan, setPlan] = useState<TimelineEvent | null>(null);
  const [toolCalls, setToolCalls] = useState<ToolCall[]>([]);
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [summary, setSummary] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const readerRef = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const addEvent = useCallback((event: TimelineEvent) => {
    setEvents((prev) => [...prev, event]);
  }, []);

  const startTask = useCallback(
    async (task: string, workspace = "/workspace"): Promise<string> => {
      setEvents([]);
      setPlan(null);
      setToolCalls([]);
      setApprovals([]);
      setSummary(null);
      setError(null);

      // Create task
      const res = await fetch(`${API_BASE}/api/v1/tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task, workspace_root: workspace }),
      });
      const data = await res.json();
      const tid = data.task_id;
      setTaskId(tid);
      setConnected(true);

      // Connect SSE
      abortRef.current = new AbortController();
      const response = await fetch(`${API_BASE}/api/v1/tasks/${tid}/stream`, {
        signal: abortRef.current.signal,
      });

      if (!response.body) {
        setError("No response body for SSE stream");
        return tid;
      }

      const reader = response.body.getReader();
      readerRef.current = reader;
      const decoder = new TextDecoder();
      let buffer = "";

      const readLoop = async () => {
        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() || "";

            let currentEvent = "";
            for (const line of lines) {
              if (line.startsWith("event: ")) {
                currentEvent = line.slice(7).trim();
              } else if (line.startsWith("data: ")) {
                const raw = line.slice(6);
                try {
                  const parsed = JSON.parse(raw);
                  processSSEEvent(currentEvent, parsed);
                } catch {
                  // skip malformed
                }
              }
            }
          }
        } catch (err) {
          if ((err as Error).name !== "AbortError") {
            setError((err as Error).message);
          }
        }
        setConnected(false);
      };

      readLoop();
      return tid;
    },
    [addEvent]
  );

  const processSSEEvent = useCallback(
    (eventType: string, data: Record<string, unknown>) => {
      const ts = new Date().toISOString();

      switch (eventType) {
        case "plan":
          setPlan({ id: ts, type: "plan", content: JSON.stringify(data), agent: "planner", timestamp: ts });
          addEvent({ id: ts, type: "plan", content: `Plan generated: ${(data.steps as unknown[])?.length || 0} steps`, agent: "planner", timestamp: ts });
          break;
        case "tool_call":
          setToolCalls((prev) => [...prev, data as unknown as ToolCall]);
          addEvent({ id: ts, type: "tool_call", content: `Tool: ${data.tool}`, agent: "tool_executor", timestamp: ts });
          break;
        case "approval_required":
          setApprovals((prev) => [...prev, data as unknown as ApprovalRequest]);
          addEvent({ id: ts, type: "approval", content: `Approval needed: ${data.tool_name}`, agent: "orchestrator", timestamp: ts });
          break;
        case "observation":
          addEvent({ id: ts, type: "observation", content: String(data.content || ""), agent: "observer", timestamp: ts });
          break;
        case "reflection":
          addEvent({ id: ts, type: "reflection", content: String(data.content || ""), agent: "reflector", timestamp: ts });
          break;
        case "progress":
          addEvent({ id: ts, type: "reflection", content: `[${data.percent}%] ${data.message}`, agent: "system", timestamp: ts });
          break;
        case "summary":
          setSummary(String(data.changes || ""));
          addEvent({ id: ts, type: "summary", content: "Task complete — summary available", agent: "summarizer", timestamp: ts });
          break;
        case "error":
          setError(String(data.message || "Unknown error"));
          addEvent({ id: ts, type: "reflection", content: `Error: ${data.message}`, agent: "system", timestamp: ts });
          break;
        case "done":
          addEvent({ id: ts, type: "summary", content: "Task finished", agent: "system", timestamp: ts });
          break;
      }
    },
    [addEvent]
  );

  const resolveApproval = useCallback(
    async (tid: string, approvalId: string, action: "approve" | "reject") => {
      await fetch(`${API_BASE}/api/v1/tasks/${tid}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approval_id: approvalId, action }),
      });
      setApprovals((prev) =>
        prev.map((a) => (a.id === approvalId ? { ...a, status: action === "approve" ? "approved" : "rejected" } : a))
      );
    },
    []
  );

  useEffect(() => {
    return () => {
      readerRef.current?.cancel();
      abortRef.current?.abort();
    };
  }, []);

  return { events, plan, toolCalls, approvals, summary, error, connected, startTask, resolveApproval };
}
