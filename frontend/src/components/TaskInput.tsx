import React, { useState } from "react";

interface Props {
  onSubmit: (task: string, workspace: string) => void;
  disabled: boolean;
}

const TaskInput: React.FC<Props> = ({ onSubmit, disabled }) => {
  const [task, setTask] = useState("");
  const [workspace, setWorkspace] = useState("/workspace");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (task.trim()) {
      onSubmit(task.trim(), workspace.trim() || "/workspace");
    }
  };

  return (
    <form onSubmit={handleSubmit} className="task-input">
      <div className="input-group">
        <textarea
          value={task}
          onChange={(e) => setTask(e.target.value)}
          placeholder="Describe your coding task...&#10;e.g., Fix the login bug in auth.py&#10;e.g., Add type hints to all public functions&#10;e.g., Refactor the database module for better performance"
          rows={3}
          disabled={disabled}
        />
      </div>
      <div className="input-row">
        <input
          type="text"
          value={workspace}
          onChange={(e) => setWorkspace(e.target.value)}
          placeholder="Workspace path"
          disabled={disabled}
          className="workspace-input"
        />
        <button type="submit" disabled={disabled || !task.trim()} className="btn-primary">
          {disabled ? "Running..." : "Run Task"}
        </button>
      </div>
    </form>
  );
};

export default TaskInput;
