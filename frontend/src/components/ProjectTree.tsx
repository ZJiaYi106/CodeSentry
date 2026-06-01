import React, { useMemo, useState } from "react";

interface TreeNode {
  name: string;
  description: string;
  isDirectory: boolean;
  children: TreeNode[];
}

interface TreeNodeViewProps {
  node: TreeNode;
  depth: number;
  forceOpen?: boolean;
}

function hasTreeMarkers(text: string): boolean {
  return text.split("\n").filter((line) => /(?:├──|└──|\+--|\|--)/.test(line)).length >= 2;
}

function parseTree(source: string): TreeNode {
  const lines = source
    .split("\n")
    .map((line) => line.replace(/\t/g, "    ").replace(/\s+$/, ""))
    .filter((line) => line.trim());

  const firstLine = lines[0]?.trim() || ".";
  const root: TreeNode = {
    name: firstLine,
    description: "",
    isDirectory: true,
    children: [],
  };
  const stack: TreeNode[] = [root];

  for (const line of lines.slice(1)) {
    const marker = line.match(/(?:├──|└──|\+--|\|--)\s*(.*)$/);
    if (!marker) continue;

    const markerIndex = marker.index ?? 0;
    const depth = Math.max(1, Math.round(markerIndex / 4) + 1);
    const rawName = marker[1].trim();
    const comment = rawName.match(/^(.*?)\s+#\s+(.*)$/);
    const nameWithSlash = comment?.[1]?.trim() || rawName;
    const description = comment?.[2]?.trim() || "";
    const isDirectory = /[\\/]$/.test(nameWithSlash);
    const name = nameWithSlash.replace(/[\\/]$/, "") || nameWithSlash;
    const node: TreeNode = {
      name,
      description,
      isDirectory,
      children: [],
    };

    while (stack.length > depth) stack.pop();
    const parent = stack[depth - 1] || stack[stack.length - 1];
    parent.children.push(node);
    stack.length = depth;
    stack.push(node);
  }

  return root;
}

function countNodes(node: TreeNode): number {
  return node.children.reduce((total, child) => total + 1 + countNodes(child), 0);
}

const TreeNodeView: React.FC<TreeNodeViewProps> = ({ node, depth, forceOpen }) => {
  const hasChildren = node.children.length > 0;
  const [open, setOpen] = useState(forceOpen || (hasChildren && depth < 1));

  return (
    <div className="project-tree-node">
      <button
        type="button"
        className={`project-tree-row ${depth < 0 ? "project-tree-row-root" : ""}`}
        onClick={() => hasChildren && setOpen((value) => !value)}
        aria-expanded={hasChildren ? open : undefined}
      >
        <span className="project-tree-toggle" aria-hidden="true">
          {hasChildren ? (open ? "⌄" : "›") : ""}
        </span>
        <span
          className={`project-tree-kind ${node.isDirectory ? "project-tree-kind-directory" : "project-tree-kind-file"}`}
          aria-hidden="true"
        >
          {node.isDirectory ? "▰" : "•"}
        </span>
        <span className="project-tree-name">{node.name}{node.isDirectory ? "/" : ""}</span>
        {node.description && <span className="project-tree-description">{node.description}</span>}
      </button>

      {hasChildren && open && (
        <div className="project-tree-children">
          {node.children.map((child, index) => (
            <TreeNodeView key={`${child.name}-${index}`} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
};

interface Props {
  source: string;
}

const ProjectTree: React.FC<Props> = ({ source }) => {
  const tree = useMemo(() => parseTree(source), [source]);
  const total = countNodes(tree);

  return (
    <div className="project-tree">
      <div className="project-tree-toolbar">
        <span className="project-tree-label">文件树</span>
        <span className="project-tree-count">{total} 项 · 点击目录展开/收起</span>
      </div>
      <TreeNodeView node={tree} depth={-1} forceOpen />
    </div>
  );
};

export { hasTreeMarkers };
export default ProjectTree;
