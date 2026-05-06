import React, { useState } from "react";

interface Props {
  onSubmit: (task: string, workspace: string) => void;
  disabled: boolean;
  compact?: boolean;
}

const TaskInput: React.FC<Props> = ({ onSubmit, disabled, compact }) => {
  const [task, setTask] = useState("");
  const [workspace, setWorkspace] = useState("/workspace");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (task.trim()) {
      onSubmit(task.trim(), workspace.trim() || "/workspace");
    }
  };

  return (
    <form onSubmit={handleSubmit} className={`task-input ${compact ? "task-input-compact" : ""}`}>
      <div className="input-group">
        <textarea
          value={task}
          onChange={(e) => setTask(e.target.value)}
          placeholder={compact
            ? "输入新任务..."
            : "描述你的编程任务...\n例如：修复 auth.py 中的登录 bug\n例如：给所有公开函数添加类型注解\n例如：重构数据库模块以提升性能"}
          rows={compact ? 2 : 3}
          disabled={disabled}
        />
      </div>
      <div className="input-row">
        <input
          type="text"
          value={workspace}
          onChange={(e) => setWorkspace(e.target.value)}
          placeholder="工作目录路径"
          disabled={disabled}
          className="workspace-input"
        />
        <button type="submit" disabled={disabled || !task.trim()} className="btn-primary">
          {disabled ? "执行中..." : "开始任务"}
        </button>
      </div>
    </form>
  );
};

export default TaskInput;
