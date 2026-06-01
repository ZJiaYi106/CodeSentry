import React, { useState } from "react";

interface Props {
  onSubmit: (question: string) => void;
  disabled: boolean;
}

const FollowUpInput: React.FC<Props> = ({ onSubmit, disabled }) => {
  const [question, setQuestion] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (question.trim()) {
      onSubmit(question.trim());
      setQuestion("");
    }
  };

  return (
    <form onSubmit={handleSubmit} className="followup-input">
      <input
        type="text"
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        placeholder="对这份报告继续追问… 例如：这个模块具体是做什么的？"
        disabled={disabled}
      />
      <button type="submit" disabled={disabled || !question.trim()} className="btn-primary">
        追问
      </button>
    </form>
  );
};

export default FollowUpInput;
