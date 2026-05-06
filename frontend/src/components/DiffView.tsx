import React from "react";

interface Props {
  diff: string;
  fileName?: string;
}

const DiffView: React.FC<Props> = ({ diff, fileName }) => {
  if (!diff || diff.trim().length === 0) {
    return (
      <div className="diff-view">
        <h3>代码差异</h3>
        <p className="diff-empty">未检测到变更。</p>
      </div>
    );
  }

  const lines = diff.split("\n");

  return (
    <div className="diff-view">
      <h3>代码差异 {fileName ? `— ${fileName}` : ""}</h3>
      <div className="diff-content">
        {lines.map((line, i) => {
          let cls = "diff-line";
          if (line.startsWith("+") && !line.startsWith("+++")) cls += " diff-added";
          else if (line.startsWith("-") && !line.startsWith("---")) cls += " diff-removed";
          else if (line.startsWith("@@")) cls += " diff-hunk";
          else if (line.startsWith("diff ") || line.startsWith("index ") || line.startsWith("---") || line.startsWith("+++"))
            cls += " diff-header";

          return (
            <div key={i} className={cls}>
              <span className="diff-line-num">{i + 1}</span>
              <span className="diff-line-text">{line}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default DiffView;
