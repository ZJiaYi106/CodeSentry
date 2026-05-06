import React from "react";

interface Props {
  summary: string | null;
  error: string | null;
}

const FinalSummary: React.FC<Props> = ({ summary, error }) => {
  if (!summary && !error) return null;

  return (
    <div className="final-summary">
      <h3>最终报告</h3>
      {error && (
        <div className="error-banner">
          <strong>错误：</strong> {error}
        </div>
      )}
      {summary && (
        <div className="summary-content">
          {summary.split("\n").map((line, i) => {
            if (line.startsWith("# ")) return <h2 key={i}>{line.slice(2)}</h2>;
            if (line.startsWith("## ")) return <h3 key={i}>{line.slice(3)}</h3>;
            if (line.startsWith("### ")) return <h4 key={i}>{line.slice(4)}</h4>;
            if (line.startsWith("- ")) return <li key={i}>{line.slice(2)}</li>;
            if (line.startsWith("```")) return <pre key={i} className="code-block">{line}</pre>;
            if (line.trim() === "") return <br key={i} />;
            return <p key={i}>{line}</p>;
          })}
        </div>
      )}
    </div>
  );
};

export default FinalSummary;
