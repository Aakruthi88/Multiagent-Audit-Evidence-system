import React, { useState } from "react";
import { Search, FileText, AlertTriangle, CheckCircle2, Loader2, Database, ChevronDown, ChevronRight, ExternalLink } from "lucide-react";

const API_BASE = "http://localhost:8000/api/v1";

interface BundleFile {
  filename: string;
  doc_type: string;
  label: string;
  size_bytes?: number;
  url: string;
}

const SourceDocumentsSection: React.FC<{
  files: BundleFile[];
  requiredDocuments?: string[];
  expanded: boolean;
  onToggle: () => void;
}> = ({ files, requiredDocuments, expanded, onToggle }) => {
  if (!files || files.length === 0) return null;

  // Filter existing files based on required_documents from the RetrievalPlan
  let displayFiles = files;
  if (requiredDocuments && Array.isArray(requiredDocuments) && requiredDocuments.length > 0) {
    const matched = files.filter(f => requiredDocuments.includes(f.doc_type));
    if (matched.length > 0) {
      displayFiles = matched;
    }
  }

  if (displayFiles.length === 0) return null;

  return (
    <div
      style={{
        marginTop: "1.25rem",
        marginBottom: "1rem",
        background: "rgba(255, 255, 255, 0.03)",
        border: "1px solid rgba(255, 255, 255, 0.08)",
        borderRadius: 8,
        overflow: "hidden",
      }}
    >
      <button
        type="button"
        onClick={onToggle}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0.75rem 1rem",
          background: "rgba(255, 255, 255, 0.03)",
          border: "none",
          borderBottom: expanded ? "1px solid rgba(255, 255, 255, 0.06)" : "none",
          color: "#e2e8f0",
          cursor: "pointer",
          fontSize: "0.9rem",
          fontWeight: 600,
          textAlign: "left",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {expanded ? <ChevronDown size={16} color="#94a3b8" /> : <ChevronRight size={16} color="#94a3b8" />}
          <span>Source Documents ({displayFiles.length})</span>
        </div>
        <span style={{ fontSize: "0.75rem", color: "#94a3b8" }}>
          {expanded ? "Click to collapse" : "Click to view documents"}
        </span>
      </button>

      {expanded && (
        <div
          style={{
            padding: "0.85rem 1rem",
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
            gap: "0.75rem",
          }}
        >
          {displayFiles.map((file, idx) => {
            const fileUrl = file.url.startsWith("http") ? file.url : `http://localhost:8000${file.url}`;
            return (
              <a
                key={idx}
                href={fileUrl}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 10,
                  padding: "0.75rem 0.9rem",
                  background: "rgba(255, 255, 255, 0.04)",
                  border: "1px solid rgba(255, 255, 255, 0.08)",
                  borderRadius: 6,
                  textDecoration: "none",
                  color: "#f1f5f9",
                  transition: "all 0.15s ease",
                  cursor: "pointer",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = "rgba(59, 130, 246, 0.12)";
                  e.currentTarget.style.borderColor = "rgba(59, 130, 246, 0.35)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = "rgba(255, 255, 255, 0.04)";
                  e.currentTarget.style.borderColor = "rgba(255, 255, 255, 0.08)";
                }}
              >
                <span style={{ fontSize: "1.25rem", lineHeight: 1 }}>📄</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: "0.88rem", color: "#60a5fa", display: "flex", alignItems: "center", gap: 4 }}>
                    <span>{file.label}</span>
                    <ExternalLink size={12} color="#94a3b8" />
                  </div>
                  <div
                    style={{
                      fontSize: "0.78rem",
                      color: "#94a3b8",
                      fontFamily: "monospace",
                      marginTop: 2,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                    title={file.filename}
                  >
                    {file.filename}
                  </div>
                </div>
              </a>
            );
          })}
        </div>
      )}
    </div>
  );
};

const AskQuery: React.FC = () => {
  const [query, setQuery] = useState("");
  const [bundleId, setBundleId] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [bundleFiles, setBundleFiles] = useState<BundleFile[]>([]);
  const [filesExpanded, setFilesExpanded] = useState<boolean>(false);

  const handleQuery = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setResult(null);
    setError(null);
    setBundleFiles([]);
    try {
      const payload: any = { query: query.trim() };
      if (bundleId.trim()) payload.bundle_id = bundleId.trim();
      const res = await fetch(`${API_BASE}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const errText = await res.text();
        throw new Error(`Server error ${res.status}: ${errText}`);
      }
      const data = await res.json();
      setResult(data);

      // Check if there is a bundle_id returned to discover existing source documents
      const activeBundleId = data?.bundle_id || data?.report?.result?.bundle_id || data?.report?.bundle_id || (bundleId.trim() || null);
      if (activeBundleId) {
        try {
          const filesRes = await fetch(`${API_BASE}/bundles/${activeBundleId}/files`);
          if (filesRes.ok) {
            const filesData = await filesRes.json();
            setBundleFiles(filesData.files || []);
          }
        } catch {
          setBundleFiles([]);
        }
      }

      // Collapsed by default for lookup queries, expanded for full verification/audit runs
      const isLookup = Boolean(
        data?.report?.answer &&
        ["field_lookup", "lookup", "payment_lookup"].includes(data?.report?.query_type)
      );
      setFilesExpanded(!isLookup);
    } catch (err: any) {
      setError(err.message || "Unknown error occurred");
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleQuery();
    }
  };

  // A field lookup is any QA response that contains a direct answer to a question
  // about a specific document (invoice, GRN, PO, bank statement).
  // Backend now returns query_type "field_lookup" but we also handle legacy "lookup" / "payment_lookup".
  const FIELD_LOOKUP_TYPES = new Set(["field_lookup", "lookup", "payment_lookup"]);
  const isFieldLookup = Boolean(
    result?.report?.answer &&
    FIELD_LOOKUP_TYPES.has(result?.report?.query_type)
  );

  // A status query is a system-wide bundle search that returns a bundles array.
  const bundles: any[] = result?.report?.bundles ?? [];
  const isStatusQuery =
    result?.report?.query_type === "status_query" ||
    (result?.action === "status_query" && !isFieldLookup);

  const requiredDocuments: string[] | undefined =
    result?.required_documents ||
    result?.retrieval_plan?.required_documents ||
    result?.report?.required_documents;

  return (
    <div style={{ padding: "2rem", maxWidth: 1100, margin: "0 auto", fontFamily: "Inter, sans-serif" }}>
      <div style={{ marginBottom: "2rem" }}>
        <h1 style={{ fontSize: "1.75rem", fontWeight: 700, color: "#f1f5f9", display: "flex", alignItems: "center", gap: 10 }}>
          <Search size={28} color="#3b82f6" />
          Audit Intelligence Query
        </h1>
        <p style={{ color: "#94a3b8", marginTop: 6, fontSize: "0.95rem" }}>
          Ask questions about bundles, check statuses, or run full verification audits.
        </p>
      </div>

      <div style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.10)", borderRadius: 12, padding: "1.5rem", marginBottom: "1.5rem" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: "0.85rem" }}>
          <textarea
            id="query-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="e.g. 'What bundles are flagged?', 'Verify bundle for Projector Full HD', 'Show all critical bundles'"
            rows={3}
            style={{ background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 8, padding: "0.75rem 1rem", color: "#f1f5f9", fontSize: "0.95rem", resize: "vertical", outline: "none", width: "100%", boxSizing: "border-box" }}
          />
          <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
            <input
              id="bundle-id-input"
              value={bundleId}
              onChange={(e) => setBundleId(e.target.value)}
              placeholder="Bundle ID (optional)"
              style={{ background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 8, padding: "0.6rem 0.9rem", color: "#f1f5f9", fontSize: "0.9rem", outline: "none", flex: 1 }}
            />
            <button
              id="run-query-btn"
              onClick={handleQuery}
              disabled={loading || !query.trim()}
              style={{ background: loading || !query.trim() ? "rgba(59,130,246,0.4)" : "linear-gradient(135deg,#3b82f6,#6366f1)", color: "#fff", border: "none", borderRadius: 8, padding: "0.6rem 1.5rem", fontSize: "0.95rem", fontWeight: 600, cursor: loading || !query.trim() ? "not-allowed" : "pointer", display: "flex", alignItems: "center", gap: 8, whiteSpace: "nowrap" }}
            >
              {loading ? <><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Running...</> : <><Search size={16} /> Run Query</>}
            </button>
          </div>
        </div>
      </div>

      {loading && (
        <div style={{ background: "rgba(59,130,246,0.08)", border: "1px solid rgba(59,130,246,0.2)", borderRadius: 12, padding: "2rem", textAlign: "center", color: "#93c5fd" }}>
          <Loader2 size={32} style={{ animation: "spin 1s linear infinite", marginBottom: 12 }} />
          <div style={{ fontSize: "1rem", fontWeight: 500 }}>Running agent pipeline...</div>
          <div style={{ fontSize: "0.85rem", color: "#64748b", marginTop: 4 }}>This may take 30-60 seconds for full audit runs.</div>
        </div>
      )}

      {!loading && error && (
        <div style={{ background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)", borderRadius: 12, padding: "1.5rem", color: "#fca5a5", display: "flex", gap: 10, alignItems: "flex-start" }}>
          <AlertTriangle size={20} color="#f87171" style={{ flexShrink: 0, marginTop: 2 }} />
          <div>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>Query Failed</div>
            <div style={{ fontSize: "0.9rem" }}>{error}</div>
          </div>
        </div>
      )}

      {!loading && result && (
        <div style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 12, padding: "1.5rem" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: "1.25rem", paddingBottom: "0.75rem", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
            {isFieldLookup ? <CheckCircle2 size={20} color="#10b981" /> : isStatusQuery ? <Database size={20} color="#60a5fa" /> : <FileText size={20} color="#3b82f6" />}
            <span style={{ fontWeight: 600, fontSize: "1.05rem", color: "#e2e8f0" }}>
              {isFieldLookup ? "Audit Intelligence Answer" : isStatusQuery ? "System Status & Bundle Search Results" : "Audit Report"}
            </span>
            {(result?.report?.query_type || result.action) && (
              <span style={{ marginLeft: "auto", fontSize: "0.75rem", background: "rgba(99,102,241,0.2)", color: "#a5b4fc", padding: "2px 8px", borderRadius: 4, fontFamily: "monospace" }}>
                {result?.report?.query_type || result.action}
              </span>
            )}

          </div>

          {/* === FIELD LOOKUP VIEW (Invoice/PO specific questions) === */}
          {isFieldLookup && (
            <div style={{ padding: "1.25rem", background: "rgba(16,185,129,0.08)", borderLeft: "4px solid #10b981", borderRadius: 8, lineHeight: 1.8 }}>
              <div style={{ fontWeight: 700, color: "#34d399", marginBottom: 8, fontSize: "1rem" }}>Answer</div>
              <div style={{ color: "#e2e8f0", fontSize: "1rem" }}>
                {result.report.answer || result.report.note || "See details below."}
              </div>
              {result.report.result && result.report.result.found && !result.report.result.ambiguous && (
                <div style={{ marginTop: "1rem", display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(160px,1fr))", gap: "0.75rem" }}>
                  {result.report.result.vendor_name && (
                    <div style={{ background: "rgba(255,255,255,0.04)", borderRadius: 8, padding: "0.75rem", border: "1px solid rgba(255,255,255,0.07)" }}>
                      <div style={{ fontSize: "0.7rem", color: "#94a3b8", textTransform: "uppercase", marginBottom: 2 }}>Vendor</div>
                      <div style={{ fontWeight: 600, color: "#f1f5f9" }}>{result.report.result.vendor_name}</div>
                    </div>
                  )}
                  {(result.report.result.invoice_number || result.report.result.po_number) && (
                    <div style={{ background: "rgba(255,255,255,0.04)", borderRadius: 8, padding: "0.75rem", border: "1px solid rgba(255,255,255,0.07)" }}>
                      <div style={{ fontSize: "0.7rem", color: "#94a3b8", textTransform: "uppercase", marginBottom: 2 }}>Document #</div>
                      <div style={{ fontWeight: 600, color: "#f1f5f9", fontFamily: "monospace" }}>{result.report.result.invoice_number || result.report.result.po_number}</div>
                    </div>
                  )}
                  {result.report.result.total_amount != null && (
                    <div style={{ background: "rgba(255,255,255,0.04)", borderRadius: 8, padding: "0.75rem", border: "1px solid rgba(255,255,255,0.07)" }}>
                      <div style={{ fontSize: "0.7rem", color: "#94a3b8", textTransform: "uppercase", marginBottom: 2 }}>Total Amount</div>
                      <div style={{ fontWeight: 600, color: "#fbbf24" }}>₹{result.report.result.total_amount?.toLocaleString()}</div>
                    </div>
                  )}
                  {result.report.result.bundle_id && (
                    <div style={{ background: "rgba(255,255,255,0.04)", borderRadius: 8, padding: "0.75rem", border: "1px solid rgba(255,255,255,0.07)" }}>
                      <div style={{ fontSize: "0.7rem", color: "#94a3b8", textTransform: "uppercase", marginBottom: 2 }}>Bundle ID</div>
                      <div style={{ fontWeight: 600, color: "#60a5fa", fontFamily: "monospace", fontSize: "0.82rem" }}>{result.report.result.bundle_id.slice(0,16)}...</div>
                    </div>
                  )}
                </div>
              )}
              {result.report.result && result.report.result.ambiguous && (
                <div style={{ marginTop: "1rem" }}>
                  <div style={{ color: "#fbbf24", fontWeight: 600, marginBottom: 8 }}>Multiple matches found — please clarify:</div>
                  {(result.report.result.matches || []).map((m: any, i: number) => (
                    <div key={i} style={{ background: "rgba(255,255,255,0.04)", borderRadius: 6, padding: "0.6rem 1rem", marginBottom: 6, color: "#e2e8f0", fontSize: "0.9rem" }}>
                      <strong>{m.invoice_number || m.po_number}</strong> — vendor: {m.vendor_name || "N/A"}, bundle: {m.bundle_id?.slice(0,8)}...
                    </div>
                  ))}
                </div>
              )}

              {/* Source Documents Collapsible Section */}
              <SourceDocumentsSection
                files={bundleFiles}
                requiredDocuments={requiredDocuments}
                expanded={filesExpanded}
                onToggle={() => setFilesExpanded(!filesExpanded)}
              />

              {/* Verification Checks for QA answers */}
              {Array.isArray(result.report.verification_checks) && result.report.verification_checks.length > 0 && (
                <div style={{ marginTop: "1.25rem", paddingTop: "1rem", borderTop: "1px solid rgba(255,255,255,0.08)" }}>
                  <h4 style={{ fontSize: "0.85rem", fontWeight: 600, color: "#94a3b8", marginBottom: 10, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                    Bundle Verification Checks ({result.report.verification_checks.length})
                  </h4>
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {result.report.verification_checks.map((chk: any, i: number) => {
                      const isPassed = chk.status === "pass";
                      const isWarning = chk.status === "warning";
                      const borderColor = isPassed ? "#10b981" : isWarning ? "#f59e0b" : "#ef4444";
                      const bgColor = isPassed ? "rgba(16,185,129,0.07)" : isWarning ? "rgba(245,158,11,0.07)" : "rgba(239,68,68,0.07)";
                      const statusColor = isPassed ? "#34d399" : isWarning ? "#fbbf24" : "#f87171";
                      return (
                        <div key={i} style={{ background: bgColor, borderLeft: `3px solid ${borderColor}`, borderRadius: 6, padding: "0.6rem 0.9rem", display: "flex", alignItems: "flex-start", gap: 10 }}>
                          <span style={{ fontSize: "0.85rem", fontWeight: 700, color: statusColor, minWidth: 48 }}>
                            {isPassed ? "✓ PASS" : isWarning ? "⚠ WARN" : "✗ FAIL"}
                          </span>
                          <div style={{ flex: 1 }}>
                            <div style={{ fontWeight: 600, color: "#e2e8f0", fontSize: "0.88rem" }}>
                              {chk.check_name || chk.check_type || `Check ${i + 1}`}
                            </div>
                            {chk.explanation && (
                              <div style={{ fontSize: "0.82rem", color: "#94a3b8", marginTop: 2 }}>{chk.explanation}</div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {!isFieldLookup && isStatusQuery && (
            <div>
              <div style={{ display: "flex", gap: "1rem", marginBottom: "1.25rem", flexWrap: "wrap" }}>
                <div style={{ background: "rgba(255,255,255,0.04)", borderRadius: 8, padding: "0.75rem 1.25rem", border: "1px solid rgba(255,255,255,0.07)" }}>
                  <div style={{ fontSize: "0.75rem", color: "#94a3b8", textTransform: "uppercase", marginBottom: 2 }}>Query Type</div>
                  <div style={{ fontWeight: 600, color: "#60a5fa" }}>{result.report?.query_type || "status_query"}</div>
                </div>
                <div style={{ background: "rgba(255,255,255,0.04)", borderRadius: 8, padding: "0.75rem 1.25rem", border: "1px solid rgba(255,255,255,0.07)" }}>
                  <div style={{ fontSize: "0.75rem", color: "#94a3b8", textTransform: "uppercase", marginBottom: 2 }}>Results Found</div>
                  <div style={{ fontWeight: 600, color: "#34d399" }}>{result.report?.result_count ?? bundles.length}</div>
                </div>
                {result.report?.filters_applied && (
                  <div style={{ background: "rgba(255,255,255,0.04)", borderRadius: 8, padding: "0.75rem 1.25rem", border: "1px solid rgba(255,255,255,0.07)" }}>
                    <div style={{ fontSize: "0.75rem", color: "#94a3b8", textTransform: "uppercase", marginBottom: 2 }}>Filters</div>
                    <div style={{ fontWeight: 600, color: "#fbbf24", fontSize: "0.85rem" }}>
                      {Object.entries(result.report.filters_applied).map(([k, v]) => `${k}: ${v}`).join(", ") || "None"}
                    </div>
                  </div>
                )}
              </div>
              {bundles.length > 0 ? (
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.9rem" }}>
                    <thead>
                      <tr style={{ background: "rgba(255,255,255,0.05)", color: "#94a3b8", textAlign: "left", fontSize: "0.8rem", textTransform: "uppercase" }}>
                        <th style={{ padding: "8px 12px" }}>Bundle ID</th>
                        <th style={{ padding: "8px 12px" }}>Txn Reference</th>
                        <th style={{ padding: "8px 12px" }}>Status</th>
                        <th style={{ padding: "8px 12px" }}>Risk Score</th>
                        <th style={{ padding: "8px 12px" }}>Failed Checks</th>
                      </tr>
                    </thead>
                    <tbody>
                      {bundles.map((b: any, idx: number) => (
                        <tr key={idx} style={{ borderBottom: "1px solid rgba(255,255,255,0.05)" }}>
                          <td style={{ padding: "10px 12px", fontFamily: "monospace", fontSize: "0.85rem" }}>
                            {b.bundle_id ? (
                              <a href={`#bundle-${b.bundle_id}`} style={{ color: "#60a5fa", textDecoration: "underline" }}>
                                {b.bundle_id.slice(0, 8)}...
                              </a>
                            ) : "N/A"}
                          </td>
                          <td style={{ padding: "10px 12px", color: "#cbd5e1" }}>{b.txn_reference || "N/A"}</td>
                          <td style={{ padding: "10px 12px" }}>
                            <span style={{ padding: "2px 8px", borderRadius: 4, fontSize: "0.75rem", fontWeight: 700, background: (b.status === "flagged" || b.overall_status === "critical") ? "rgba(239,68,68,0.2)" : "rgba(16,185,129,0.2)", color: (b.status === "flagged" || b.overall_status === "critical") ? "#f87171" : "#34d399" }}>
                              {(b.status || b.overall_status || "UNKNOWN").toUpperCase()}
                            </span>
                          </td>
                          <td style={{ padding: "10px 12px", fontWeight: 700, color: "#f1f5f9" }}>{b.risk_score ?? 0}</td>
                          <td style={{ padding: "10px 12px" }}>
                            {b.failed_checks && b.failed_checks.length > 0 ? (
                              <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                                {b.failed_checks.map((fc: string, i: number) => (
                                  <span key={i} style={{ background: "rgba(239,68,68,0.15)", color: "#f87171", padding: "2px 6px", borderRadius: 4, fontSize: "0.75rem" }}>{fc}</span>
                                ))}
                              </div>
                            ) : (
                              <span style={{ color: "#34d399" }}>None</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div style={{ padding: "2rem", textAlign: "center", background: "rgba(255,255,255,0.02)", borderRadius: 8, color: "#64748b" }}>
                  No bundles matched the applied filters.
                </div>
              )}
            </div>
          )}

          {!isStatusQuery && !isFieldLookup && result.report && (
            <div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))", gap: "1rem", marginBottom: "1.25rem" }}>
                <div style={{ background: "rgba(255,255,255,0.03)", padding: "0.85rem 1rem", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)" }}>
                  <div style={{ fontSize: "0.75rem", color: "#94a3b8", textTransform: "uppercase" }}>Checks</div>
                  <div style={{ fontSize: "1.1rem", fontWeight: 700, color: "#60a5fa", marginTop: 4 }}>
                    {result.report.checks_passed !== undefined ? `${result.report.checks_passed}/${result.report.checks_total ?? "?"}` : "See below"}
                  </div>
                </div>
                <div style={{ background: "rgba(255,255,255,0.03)", padding: "0.85rem 1rem", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)" }}>
                  <div style={{ fontSize: "0.75rem", color: "#94a3b8", textTransform: "uppercase" }}>Discrepancies</div>
                  <div style={{ fontSize: "1.1rem", fontWeight: 700, color: (result.report.discrepancies_count ?? result.report.failed_checks?.length ?? 0) > 0 ? "#f87171" : "#34d399", marginTop: 4 }}>
                    {result.report.discrepancies_count ?? result.report.failed_checks?.length ?? 0} Issues
                  </div>
                </div>
                <div style={{ background: "rgba(255,255,255,0.03)", padding: "0.85rem 1rem", borderRadius: 8, border: "1px solid rgba(255,255,255,0.08)" }}>
                  <div style={{ fontSize: "0.75rem", color: "#94a3b8", textTransform: "uppercase" }}>Risk Score</div>
                  <div style={{ fontSize: "1.1rem", fontWeight: 700, color: (result.risk_score ?? 0) > 50 ? "#f87171" : "#34d399", marginTop: 4 }}>
                    {result.risk_score ?? 0}/100
                  </div>
                </div>
              </div>
              {(result.report.narrative || result.report.executive_summary || result.report.note || result.report.summary) && (
                <div style={{ background: "rgba(16,185,129,0.08)", borderLeft: "4px solid #10b981", padding: "1rem", borderRadius: 8, marginBottom: "1rem", lineHeight: 1.7, color: "#e2e8f0", fontSize: "0.95rem" }}>
                  <strong style={{ color: "#34d399" }}>Audit Narrative: </strong>
                  {result.report.narrative || result.report.executive_summary || result.report.note || result.report.summary}
                  {result.report.narrative_source && (
                    <span style={{ marginLeft: 8, fontSize: "0.72rem", background: result.report.narrative_source === "llm" ? "rgba(99,102,241,0.2)" : "rgba(100,116,139,0.2)", color: result.report.narrative_source === "llm" ? "#a5b4fc" : "#94a3b8", padding: "1px 6px", borderRadius: 4, fontFamily: "monospace" }}>
                      {result.report.narrative_source === "llm" ? "🤖 LLM" : "📋 template"}
                    </span>
                  )}
                </div>
              )}

              {/* Source Documents Collapsible Section */}
              <SourceDocumentsSection
                files={bundleFiles}
                requiredDocuments={requiredDocuments}
                expanded={filesExpanded}
                onToggle={() => setFilesExpanded(!filesExpanded)}
              />

              {/* Verification Checks Table */}
              {Array.isArray(result.report.verification_checks) && result.report.verification_checks.length > 0 && (
                <div style={{ marginBottom: "1.25rem" }}>
                  <h4 style={{ fontSize: "0.9rem", fontWeight: 600, color: "#94a3b8", marginBottom: 10, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                    Verification Checks ({result.report.verification_checks.length})
                  </h4>
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {result.report.verification_checks.map((chk: any, i: number) => {
                      const isPassed = chk.status === "pass";
                      const isWarning = chk.status === "warning";
                      const borderColor = isPassed ? "#10b981" : isWarning ? "#f59e0b" : "#ef4444";
                      const bgColor = isPassed ? "rgba(16,185,129,0.07)" : isWarning ? "rgba(245,158,11,0.07)" : "rgba(239,68,68,0.07)";
                      const statusColor = isPassed ? "#34d399" : isWarning ? "#fbbf24" : "#f87171";
                      return (
                        <div key={i} style={{ background: bgColor, borderLeft: `3px solid ${borderColor}`, borderRadius: 6, padding: "0.6rem 0.9rem", display: "flex", alignItems: "flex-start", gap: 10 }}>
                          <span style={{ fontSize: "0.85rem", fontWeight: 700, color: statusColor, minWidth: 48 }}>
                            {isPassed ? "✓ PASS" : isWarning ? "⚠ WARN" : "✗ FAIL"}
                          </span>
                          <div style={{ flex: 1 }}>
                            <div style={{ fontWeight: 600, color: "#e2e8f0", fontSize: "0.88rem" }}>
                              {chk.check_name || chk.check_type || `Check ${i + 1}`}
                              {chk.severity && !isPassed && (
                                <span style={{ marginLeft: 6, fontSize: "0.7rem", padding: "1px 5px", borderRadius: 3, background: chk.severity === "critical" ? "rgba(239,68,68,0.3)" : chk.severity === "high" ? "rgba(249,115,22,0.3)" : "rgba(245,158,11,0.2)", color: chk.severity === "critical" ? "#fca5a5" : chk.severity === "high" ? "#fdba74" : "#fde68a" }}>
                                  {chk.severity?.toUpperCase()}
                                </span>
                              )}
                            </div>
                            {chk.explanation && (
                              <div style={{ fontSize: "0.82rem", color: "#94a3b8", marginTop: 2 }}>{chk.explanation}</div>
                            )}
                            {(chk.expected !== undefined || chk.actual !== undefined) && (
                              <div style={{ fontSize: "0.78rem", color: "#64748b", marginTop: 2, fontFamily: "monospace" }}>
                                {chk.expected !== undefined && <span>expected: <span style={{ color: "#a5b4fc" }}>{String(chk.expected)}</span></span>}
                                {chk.actual !== undefined && <span style={{ marginLeft: 12 }}>actual: <span style={{ color: statusColor }}>{String(chk.actual)}</span></span>}
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {Array.isArray(result.report.findings) && result.report.findings.length > 0 && (
                <div style={{ marginBottom: "1rem" }}>
                  <h4 style={{ fontSize: "0.9rem", fontWeight: 600, color: "#94a3b8", marginBottom: 8 }}>Key Findings:</h4>
                  <ul style={{ paddingLeft: "1.25rem", margin: 0, color: "#e2e8f0", lineHeight: 1.8 }}>
                    {result.report.findings.map((f: string, i: number) => <li key={i} style={{ marginBottom: 4 }}>{f}</li>)}
                  </ul>
                </div>
              )}
              {result.report.recommended_next_steps && (
                <div style={{ background: "rgba(59,130,246,0.08)", padding: "1rem", borderRadius: 8, borderLeft: "3px solid #3b82f6" }}>
                  <div style={{ fontWeight: 600, fontSize: "0.9rem", color: "#60a5fa", marginBottom: 4 }}>Recommended Action:</div>
                  <div style={{ fontSize: "0.9rem", color: "#e2e8f0" }}>{result.report.recommended_next_steps}</div>
                </div>
              )}
            </div>
          )}

          {!isStatusQuery && !isFieldLookup && !result.report && (
            <div style={{ padding: "1.5rem", background: "rgba(255,255,255,0.02)", borderRadius: 8, color: "#94a3b8", fontSize: "0.95rem" }}>
              <div style={{ marginBottom: 8 }}>
                <strong style={{ color: "#e2e8f0" }}>Agent Response</strong> — action: <code style={{ color: "#a5b4fc" }}>{result.action || "unknown"}</code>
              </div>
              {result.verdict && <div>Verdict: <span style={{ color: "#fbbf24", fontWeight: 600 }}>{result.verdict}</span></div>}
              <details style={{ marginTop: 12 }}>
                <summary style={{ cursor: "pointer", color: "#60a5fa" }}>View raw response</summary>
                <pre style={{ marginTop: 8, background: "rgba(0,0,0,0.3)", padding: "1rem", borderRadius: 6, fontSize: "0.8rem", color: "#94a3b8", overflow: "auto", maxHeight: 300 }}>
                  {JSON.stringify(result, null, 2)}
                </pre>
              </details>
            </div>
          )}

          {Array.isArray(result.errors) && result.errors.length > 0 && (
            <div style={{ marginTop: "1rem", padding: "1rem", background: "rgba(245,158,11,0.1)", borderRadius: 8, border: "1px solid rgba(245,158,11,0.2)" }}>
              <div style={{ fontWeight: 600, color: "#fbbf24", marginBottom: 6 }}>Warnings / Agent Logs</div>
              <ul style={{ paddingLeft: "1.25rem", margin: 0, fontSize: "0.85rem", color: "#cbd5e1" }}>
                {result.errors.map((e: string, i: number) => <li key={i} style={{ marginBottom: 4 }}>{e}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}

      {!loading && !result && !error && (
        <div style={{ padding: "3rem 2rem", textAlign: "center", color: "#475569", border: "1px dashed rgba(255,255,255,0.06)", borderRadius: 12 }}>
          <Search size={40} style={{ marginBottom: 12, opacity: 0.3 }} />
          <div style={{ fontSize: "1rem" }}>Enter a query above to get started.</div>
          <div style={{ fontSize: "0.85rem", marginTop: 6, color: "#334155" }}>
            Try: "show all flagged bundles" · "audit bundle for Projector Full HD" · "what bundles have high risk?"
          </div>
        </div>
      )}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
};

export { AskQuery };
export default AskQuery;




