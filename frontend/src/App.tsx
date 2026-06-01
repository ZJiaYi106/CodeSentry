import React from "react";
import { useSSE } from "./hooks/useSSE";
import TaskInput from "./components/TaskInput";
import PlanView from "./components/PlanView";
import Timeline from "./components/Timeline";
import ToolCallCard from "./components/ToolCallCard";
import ApprovalCard from "./components/ApprovalCard";
import FinalSummary from "./components/FinalSummary";
import FollowUpInput from "./components/FollowUpInput";
import "./App.css";

const App: React.FC = () => {
  const {
    events,
    plan,
    toolCalls,
    approvals,
    summary,
    error,
    connected,
    running,
    startTask,
    resolveApproval,
  } = useSSE();

  const [taskId, setTaskId] = React.useState<string | null>(null);
  const [hasStarted, setHasStarted] = React.useState(false);
  const [lastWorkspace, setLastWorkspace] = React.useState("/workspace");
  const [followupQuestion, setFollowupQuestion] = React.useState<string | null>(null);

  const handleStartTask = async (task: string, workspace: string, followupOf?: string) => {
    setHasStarted(true);
    setLastWorkspace(workspace);
    setFollowupQuestion(followupOf ? task : null);
    const tid = await startTask(task, workspace, followupOf);
    setTaskId(tid);
  };

  const handleResolveApproval = (approvalId: string, action: "approve" | "reject") => {
    if (taskId) {
      resolveApproval(taskId, approvalId, action);
    }
  };

  // Only the `running` flag from useSSE reflects the actual task lifecycle
  // (set true on submit, false on "done"/stream end/timeout). Deriving
  // "running" from connected/events makes it sticky — events stay populated
  // after the task ends, which would disable inputs forever.
  const isRunning = running;
  const showResults = hasStarted || isRunning;

  return (
    <div className="app">
      <header className="app-header">
        <h1>
          <span className="logo">&lt;/&gt;</span> CodeSentry
        </h1>
        <span className={`status-badge ${connected ? "connected" : ""}`}>
          {connected ? "● 运行中" : "○ 空闲"}
        </span>
      </header>

      {/* Hero input — transitions from centered to inside left panel */}
      <div className={`app-hero ${showResults ? "hero-compact" : "hero-full"}`}>
        <div className={`hero-content ${showResults ? "hero-content-hide" : "hero-content-show"}`}>
          <h2 className="hero-title">你想让 AI 帮你做什么？</h2>
          <p className="hero-sub">
            描述你的任务 — AI 智能体将自动探索代码、制定计划并执行。
          </p>
          <TaskInput onSubmit={handleStartTask} disabled={isRunning} />
        </div>
      </div>

      {/* Results — left: input+report, right: timeline */}
      <div className={`app-results ${showResults ? "results-visible" : "results-hidden"}`}>
        <main className="app-main">
          <section className="left-panel">
            {/* Compact input sits at top of left panel */}
            <div className="hero-compact-inner">
              <TaskInput onSubmit={handleStartTask} disabled={isRunning} compact />
            </div>

            {plan && <PlanView plan={plan} />}

            {approvals.length > 0 && (
              <ApprovalCard
                approvals={approvals}
                onResolve={handleResolveApproval}
                taskId={taskId}
              />
            )}

            {summary && <FinalSummary summary={summary} error={error} question={followupQuestion} />}
            {error && !summary && <FinalSummary summary={null} error={error} question={followupQuestion} />}

            {summary && !isRunning && (
              <FollowUpInput
                onSubmit={(q) => handleStartTask(q, lastWorkspace, taskId ?? undefined)}
                disabled={isRunning}
              />
            )}
          </section>

          <section className="right-panel">
            <Timeline events={events} running={isRunning} />
          </section>
        </main>

        <section className="bottom-panel">
          {toolCalls.length > 0 && <ToolCallCard calls={toolCalls} />}
        </section>
      </div>
    </div>
  );
};

export default App;
