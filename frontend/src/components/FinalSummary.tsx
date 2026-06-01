import React from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import ProjectTree, { hasTreeMarkers } from "./ProjectTree";

interface Props {
  summary: string | null;
  error: string | null;
  question?: string | null;
}

const markdownComponents: Components = {
  pre({ children }) {
    const child = React.Children.toArray(children)[0] as React.ReactElement<{
      children?: React.ReactNode;
    }> | undefined;
    const text = String(child?.props.children ?? "").replace(/\n$/, "");
    if (hasTreeMarkers(text)) {
      return <ProjectTree source={text} />;
    }

    return <pre>{children}</pre>;
  },
};

const FinalSummary: React.FC<Props> = ({ summary, error, question }) => {
  if (!summary && !error) return null;

  return (
    <div className="final-summary">
      <h3>最终报告</h3>
      {question && <div className="followup-question">追问：{question}</div>}
      {error && (
        <div className="error-banner">
          <strong>错误：</strong> {error}
        </div>
      )}
      {summary && (
        <div className="summary-content markdown-body">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
            {summary}
          </ReactMarkdown>
        </div>
      )}
    </div>
  );
};

export default FinalSummary;
