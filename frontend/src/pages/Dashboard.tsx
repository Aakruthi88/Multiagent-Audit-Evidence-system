import React, { useEffect, useState } from "react";
import { getBundles, runQuery } from "../api/endpoints";
import { AuditBundle } from "../types";
import { FileText, ArrowRight, RefreshCw, Layers, Search, Loader } from "lucide-react";

interface DashboardProps {
  onSelectBundle: (bundleId: string) => void;
}

const STATUS_CONFIG: Record<string, { label: string; cls: string }> = {
  clean:        { label: "CLEAN",        cls: "badge-extracted" },
  verified:     { label: "VERIFIED",     cls: "badge-extracted" },
  flagged:      { label: "FLAGGED",      cls: "badge-failed" },
  incomplete:   { label: "INCOMPLETE",   cls: "badge-failed" },
  needs_review: { label: "NEEDS REVIEW", cls: "badge-warning" },
  verifying:    { label: "VERIFYING",    cls: "badge-extracting" },
  extracting:   { label: "EXTRACTING",   cls: "badge-extracting" },
  uploaded:     { label: "UPLOADED",     cls: "badge-uploaded" },
  pending:      { label: "PENDING",      cls: "badge-uploaded" },
};

function StatusBadge({ status }: { status: string }) {
  const cfg = STATUS_CONFIG[status] ?? { label: status.toUpperCase(), cls: "badge-uploaded" };
  return <span className={`badge ${cfg.cls}`}>{cfg.label}</span>;
}

export const Dashboard: React.FC<DashboardProps> = ({ onSelectBundle }) => {
  const [bundles, setBundles] = useState<AuditBundle[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [queryLoading, setQueryLoading] = useState(false);
  const [queryResult, setQueryResult] = useState<any | null>(null);
  const [queryError, setQueryError] = useState<string | null>(null);

  const fetchBundles = async () => {
    setLoading(true);
    try {
      const data = await getBundles();
      setBundles(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchBundles(); }, []);

  const handleQuery = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    setQueryLoading(true);
    setQueryResult(null);
    setQueryError(null);
    try {
      const result = await runQuery(query.trim());
      setQueryResult(result);
    } catch (err: any) {
      setQueryError(err.message || "Query failed");
    } finally {
      setQueryLoading(false);
    }
  };

  return (
    <div>
      {/* ── NL Query Box ─────────────────────────────────────────── */}
      <div className="card" style={{ marginBottom: 24 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
          <Search size={18} color="var(--primary)" />
          <h3 style={{ fontSize: "1rem", fontWeight: 700 }}>Ask the Audit AI</h3>
          <span style={{ fontSize: "0.78rem", color: "var(--text-muted)", background: "rgba(255,255,255,0.06)", padding: "2px 8px", borderRadius: 9999 }}>
            powered by IntentRouterAgent
          </span>
        </div>
        <form onSubmit={handleQuery} style={{ display: "flex", gap: 10 }}>
          <input
            id="nl-query-input"
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder='e.g. "show me all flagged bundles" or "reverify TXN-001"'
            style={{
              flex: 1, padding: "10px 14px",
              background: "rgba(255,255,255,0.06)", border: "1px solid var(--border-color)",
              borderRadius: "var(--radius-md)", color: "var(--text-primary)", fontSize: "0.9rem",
              outline: "none",
            }}
            disabled={queryLoading}
          />
          <button
            id="nl-query-submit"
            type="submit"
            className="btn btn-primary"
            disabled={queryLoading || !query.trim()}
            style={{ minWidth: 90 }}
          >
            {queryLoading ? <Loader size={16} className="spin" /> : <><Search size={14} /> Ask</>}
          </button>
        </form>

        {/* Query Results */}
        {queryError && (
          <div style={{ marginTop: 12, padding: 12, background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.25)", borderRadius: "var(--radius-md)", color: "#f87171", fontSize: "0.85rem" }}>
            Error: {queryError}
          </div>
        )}
        {queryResult && (
          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginBottom: 8 }}>
              Action: <strong style={{ color: "var(--primary)" }}>{queryResult.action}</strong>
              {queryResult.report?.result_count !== undefined && (
                <span style={{ marginLeft: 12 }}>Results: <strong>{queryResult.report.result_count}</strong></span>
              )}
            </div>
            {queryResult.report?.bundles && queryResult.report.bundles.length > 0 ? (
              <div className="table-wrapper">
                <table>
                  <thead>
                    <tr>
                      <th>Transaction Ref</th>
                      <th>Status</th>
                      <th>Risk Score</th>
                      <th>Failed Checks</th>
                    </tr>
                  </thead>
                  <tbody>
                    {queryResult.report.bundles.map((b: any) => (
                      <tr key={b.bundle_id} style={{ cursor: "pointer" }} onClick={() => onSelectBundle(b.bundle_id)}>
                        <td style={{ fontFamily: "var(--font-mono)", fontWeight: 600 }}>
                          {b.txn_reference || b.bundle_id.slice(0, 8) + "..."}
                        </td>
                        <td><StatusBadge status={b.overall_status || b.status || "unknown"} /></td>
                        <td style={{ fontFamily: "var(--font-mono)" }}>{b.risk_score ?? "—"}</td>
                        <td style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
                          {b.failed_checks?.length > 0 ? b.failed_checks.join(", ") : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : queryResult.report ? (
              <div style={{ padding: 12, background: "rgba(255,255,255,0.03)", borderRadius: "var(--radius-md)", fontSize: "0.85rem", color: "var(--text-muted)" }}>
                <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                  {JSON.stringify(queryResult.report, null, 2)}
                </pre>
              </div>
            ) : null}
          </div>
        )}
      </div>

      {/* ── Bundle Table ──────────────────────────────────────────── */}
      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
          <div>
            <h2 style={{ fontSize: "1.25rem", fontWeight: 700, marginBottom: 4 }}>Audit Evidence Bundles</h2>
            <p style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
              All processed transaction packages and their verification status.
            </p>
          </div>
          <button className="nav-btn" onClick={fetchBundles} disabled={loading} id="refresh-bundles-btn">
            <RefreshCw size={16} className={loading ? "spin" : ""} /> Refresh
          </button>
        </div>

        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)" }}>
            Loading audit bundles...
          </div>
        ) : bundles.length === 0 ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)" }}>
            <Layers size={40} style={{ margin: "0 auto 12px auto", opacity: 0.5 }} />
            <p>No audit bundles found. Upload your first transaction pack!</p>
          </div>
        ) : (
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>Transaction Reference</th>
                  <th>Status</th>
                  <th>Documents</th>
                  <th>Created At</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {bundles.map((bundle) => (
                  <tr key={bundle.bundle_id} style={{ cursor: "pointer" }} onClick={() => onSelectBundle(bundle.bundle_id)}>
                    <td style={{ fontWeight: 600, fontFamily: "var(--font-mono)" }}>{bundle.txn_reference}</td>
                    <td><StatusBadge status={bundle.status} /></td>
                    <td>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                        <FileText size={14} color="var(--primary)" /> {bundle.documents?.length || 0} Docs
                      </span>
                    </td>
                    <td style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
                      {new Date(bundle.created_at).toLocaleString()}
                    </td>
                    <td>
                      <button
                        className="btn btn-primary"
                        style={{ padding: "6px 12px", fontSize: "0.8rem" }}
                        onClick={(e) => { e.stopPropagation(); onSelectBundle(bundle.bundle_id); }}
                      >
                        View Details <ArrowRight size={14} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
