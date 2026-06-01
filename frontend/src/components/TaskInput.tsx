import React, { useState } from "react";
import FolderPicker from "./FolderPicker";

interface Props {
  onSubmit: (task: string, workspace: string) => void;
  disabled: boolean;
  compact?: boolean;
}

const TaskInput: React.FC<Props> = ({ onSubmit, disabled, compact }) => {
  const [task, setTask] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (task.trim()) {
      onSubmit(task.trim(), workspace.trim() || "/workspace");
    }
  };

  return (
    <>
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
            placeholder="工作目录（可留空，或点「浏览…」选择）"
            disabled={disabled}
            className="workspace-input"
            title={workspace}
          />
          <button
            type="button"
            className="btn-secondary"
            disabled={disabled}
            onClick={() => setPickerOpen(true)}
          >
            浏览…
          </button>
          <button type="submit" disabled={disabled || !task.trim()} className="btn-primary">
            {disabled ? "执行中..." : "开始任务"}
          </button>
        </div>
      </form>

      <FolderPicker
        open={pickerOpen}
        onSelect={(p) => {
          setWorkspace(p);
          setPickerOpen(false);
        }}
        onClose={() => setPickerOpen(false)}
      />
    </>
  );
};

export default TaskInput;
