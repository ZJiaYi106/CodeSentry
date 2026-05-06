import React from "react";

interface TestResultItem {
  tool: string;
  success: boolean;
  exit_code?: number;
  stdout?: string;
  stderr?: string;
}

interface Props {
  results: TestResultItem[];
}

const TestResults: React.FC<Props> = ({ results }) => {
  if (results.length === 0) return null;

  const passed = results.filter((r) => r.success).length;
  const failed = results.filter((r) => !r.success).length;

  return (
    <div className="test-results">
      <h3>测试结果</h3>
      <div className="test-summary">
        <span className="test-passed">{passed} 通过</span>
        {failed > 0 && <span className="test-failed">{failed} 失败</span>}
      </div>
      {results.map((r, i) => (
        <div key={i} className={`test-item test-${r.success ? "pass" : "fail"}`}>
          <div className="test-item-header">
            <span className="test-tool">{r.tool}</span>
            <span className={`test-exit-code ${r.success ? "success" : "fail"}`}>
              {r.success ? "PASS" : `FAIL (exit ${r.exit_code ?? "?"})`}
            </span>
          </div>
          {r.stdout && (
            <details>
              <summary>stdout</summary>
              <pre>{r.stdout}</pre>
            </details>
          )}
          {r.stderr && (
            <details>
              <summary>stderr</summary>
              <pre className="stderr">{r.stderr}</pre>
            </details>
          )}
        </div>
      ))}
    </div>
  );
};

export default TestResults;
