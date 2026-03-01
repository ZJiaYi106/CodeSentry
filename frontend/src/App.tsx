import type React from "react";

const App: React.FC = () => {
  return (
    <div style={{ padding: "2rem", fontFamily: "system-ui, sans-serif" }}>
      <h1>CodeSentry</h1>
      <p>AI Coding Agent — analyze, plan, and modify code repositories</p>
      <p>
        <small>
          Backend status:{" "}
          <a href="http://localhost:8000/health" target="_blank" rel="noreferrer">
            /health
          </a>
        </small>
      </p>
    </div>
  );
};

export default App;
