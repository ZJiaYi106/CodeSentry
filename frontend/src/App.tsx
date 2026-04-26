import React from "react";
import { useSSE } from "./hooks/useSSE";
import TaskInput from "./components/TaskInput";
import PlanView from "./components/PlanView";
import Timeline from "./components/Timeline";
import ToolCallCard from "./components/ToolCallCard";
import ApprovalCard from "./components/ApprovalCard";
import FinalSummary from "./components/FinalSummary";
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
    startTask,
    resolveApproval,
  } = useSSE();

  const [taskId, setTaskId] = React.useState<string | null>(null);

  const handleStartTask = async (task: string, workspace: string) => {
    const tid = await startTask(task, workspace);
    setTaskId(tid);
  };

  const handleResolveApproval = (approvalId: string, action: "approve" | "reject") => {
    if (taskId) {
      resolveApproval(taskId, approvalId, action);
    }
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>
          <span className="logo">&lt;/&gt;</span> CodeSentry
        </h1>
        <span className={`status-badge ${connected ? "connected" : ""}`}>
          {connected ? "● Connected" : "○ Idle"}
        </span>
      </header>

      <main className="app-main">
        <section className="left-panel">
          <TaskInput onSubmit={handleStartTask} disabled={connected} />

          {plan && <PlanView plan={plan} />}

          {approvals.length > 0 && (
            <ApprovalCard
              approvals={approvals}
              onResolve={handleResolveApproval}
              taskId={taskId}
            />
          )}

          {summary && <FinalSummary summary={summary} error={error} />}
          {error && !summary && <FinalSummary summary={null} error={error} />}
        </section>

        <section className="right-panel">
          <Timeline events={events} />
        </section>
      </main>

      <section className="bottom-panel">
        {toolCalls.length > 0 && <ToolCallCard calls={toolCalls} />}
      </section>
    </div>
  );
};

export default App;
