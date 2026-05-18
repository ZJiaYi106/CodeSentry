import { useEffect, useRef, useCallback, useState } from "react";
import type { SSEEvent, TimelineEvent, ApprovalRequest, ToolCall } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

// Idle timeout: if no SSE event arrives within this window, treat the
// connection as dead and stop showing "running".
const SSE_IDLE_TIMEOUT_MS = 60_000; // 60 seconds

const AGENT_CN: Record<string, string> = {
  planner: "规划者",
  tool_executor: "工具执行",
  observer: "观察者",
  reflector: "反思者",
  summarizer: "总结者",
  orchestrator: "编排器",
  system: "系统",
};

const TYPE_CN: Record<string, string> = {
  plan: "制定计划",
  tool_call: "工具调用",
  observation: "观察记录",
  reflection: "反思评估",
  approval: "等待审批",
  summary: "任务完成",
};

interface UseSSEReturn {
  events: TimelineEvent[];
  plan: TimelineEvent | null;
  toolCalls: ToolCall[];
  approvals: ApprovalRequest[];
  summary: string | null;
  error: string | null;
  connected: boolean;
  running: boolean;
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
  const [running, setRunning] = useState(false);
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
      setRunning(true);

      const res = await fetch(`${API_BASE}/api/v1/tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task, workspace_root: workspace }),
      });
      const data = await res.json();
      const tid = data.task_id;
      setTaskId(tid);
      setConnected(true);

      abortRef.current = new AbortController();
      const response = await fetch(`${API_BASE}/api/v1/tasks/${tid}/stream`, {
        signal: abortRef.current.signal,
      });

      if (!response.body) {
        setError("无法获取 SSE 流");
        setRunning(false);
        return tid;
      }

      const reader = response.body.getReader();
      readerRef.current = reader;
      const decoder = new TextDecoder();
      let buffer = "";

      // ── Idle timeout: reset on every event, fire if silent too long ──
      let idleTimer: ReturnType<typeof setTimeout> | null = null;

      const resetIdleTimer = () => {
        if (idleTimer) clearTimeout(idleTimer);
        idleTimer = setTimeout(() => {
          setError("SSE 流超时：60 秒内未收到新事件，连接可能已断开");
          setConnected(false);
          setRunning(false);
          readerRef.current?.cancel();
        }, SSE_IDLE_TIMEOUT_MS);
      };

      // Start the idle timer — first event should arrive soon
      resetIdleTimer();

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
                  resetIdleTimer(); // received an event — reset idle countdown
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
        } finally {
          if (idleTimer) clearTimeout(idleTimer);
        }
        setConnected(false);
        setRunning(false);
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
        case "plan": {
          const steps = (data.steps as unknown[])?.length || 0;
          setPlan({ id: ts, type: "plan", content: JSON.stringify(data), agent: "规划者", timestamp: ts });
          addEvent({ id: ts, type: "plan", content: `生成了 ${steps} 个执行步骤`, agent: "规划者", timestamp: ts });
          break;
        }
        case "tool_call": {
          const tool = String(data.tool || "未知工具");
          setToolCalls((prev) => [...prev, data as unknown as ToolCall]);
          addEvent({ id: ts, type: "tool_call", content: `调用工具：${tool}`, agent: "工具执行", timestamp: ts });
          break;
        }
        case "approval_required": {
          const toolName = String(data.tool_name || data.tool || "未知");
          setApprovals((prev) => [...prev, data as unknown as ApprovalRequest]);
          addEvent({ id: ts, type: "approval", content: `需要审批：${toolName}`, agent: "编排器", timestamp: ts });
          break;
        }
        case "observation":
          addEvent({ id: ts, type: "observation", content: String(data.content || "").slice(0, 200), agent: "观察者", timestamp: ts });
          break;
        case "reflection":
          addEvent({ id: ts, type: "reflection", content: String(data.content || ""), agent: "反思者", timestamp: ts });
          break;
        case "progress": {
          const msg = String(data.message || "");
          const pct = data.percent || 0;
          addEvent({ id: ts, type: "reflection", content: `[${pct}%] ${msg}`, agent: "系统", timestamp: ts });
          break;
        }
        case "summary":
          setSummary(String(data.changes || ""));
          addEvent({ id: ts, type: "summary", content: "任务完成，报告已生成", agent: "总结者", timestamp: ts });
          break;
        case "error":
          setError(String(data.message || "未知错误"));
          addEvent({ id: ts, type: "reflection", content: `错误：${data.message}`, agent: "系统", timestamp: ts });
          break;
        case "done":
          setRunning(false);
          addEvent({ id: ts, type: "summary", content: "全部完成", agent: "系统", timestamp: ts });
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
      setConnected(false);
      setRunning(false);
    };
  }, []);

  return { events, plan, toolCalls, approvals, summary, error, connected, running, startTask, resolveApproval };
}
