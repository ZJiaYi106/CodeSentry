import React, { useEffect, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

interface Entry {
  name: string;
  path: string;
  type: string;
}

interface Listing {
  path: string;
  parent: string | null;
  entries: Entry[];
}

interface Props {
  open: boolean;
  onSelect: (path: string) => void;
  onClose: () => void;
}

const FolderPicker: React.FC<Props> = ({ open, onSelect, onClose }) => {
  const [listing, setListing] = useState<Listing | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchListing = async (path: string) => {
    setLoading(true);
    setError(null);
    try {
      const url = path
        ? `${API_BASE}/api/v1/browse?path=${encodeURIComponent(path)}`
        : `${API_BASE}/api/v1/browse`;
      const res = await fetch(url);
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail || `HTTP ${res.status}`);
      }
      setListing(await res.json());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) {
      // Always start at the top level (drive letters on Windows).
      fetchListing("");
    }
  }, [open]);

  if (!open) return null;

  return (
    <div className="folder-picker-overlay" onClick={onClose}>
      <div className="folder-picker" onClick={(e) => e.stopPropagation()}>
        <div className="picker-header">
          <h4>选择工作目录</h4>
          <button className="picker-close" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </div>

        <div className="picker-path">
          <input
            type="text"
            readOnly
            value={listing?.path ?? ""}
            placeholder="当前路径"
          />
          <button
            className="btn-secondary"
            onClick={() => listing?.parent != null && fetchListing(listing.parent)}
            disabled={loading || listing?.parent == null}
          >
            上一级
          </button>
        </div>

        {error && (
          <div className="picker-error">
            {error}
            {listing === null && (
              <button className="btn-secondary" onClick={() => fetchListing("")}>
                返回根目录
              </button>
            )}
          </div>
        )}

        <div className="folder-list">
          {loading && <div className="picker-loading">加载中…</div>}
          {!loading && !error && listing?.entries.length === 0 && (
            <div className="picker-empty">该目录下没有子文件夹</div>
          )}
          {!loading &&
            listing?.entries.map((e) => (
              <div key={e.path} className="folder-row" onClick={() => fetchListing(e.path)}>
                <span className="folder-icon">📁</span>
                <span className="folder-name">{e.name}</span>
              </div>
            ))}
        </div>

        <div className="picker-actions">
          <button className="btn-secondary" onClick={onClose}>
            取消
          </button>
          <button
            className="btn-primary"
            disabled={loading || !listing?.path}
            onClick={() => listing && onSelect(listing.path)}
          >
            选择此文件夹
          </button>
        </div>
      </div>
    </div>
  );
};

export default FolderPicker;
