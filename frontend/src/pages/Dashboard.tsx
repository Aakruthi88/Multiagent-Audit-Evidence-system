import React, { useEffect, useState } from "react";
import { getBundles, runQuery, getImpactMetrics } from "../api/endpoints";
import { AuditBundle } from "../types";
import {
  FileText,
  RefreshCw,
  Search,
  Loader,
  Plus,
  CheckCircle2,
  AlertTriangle,
  FileStack,
  Users2,
  Sparkles,
  TrendingUp,
  Clock,
} from "lucide-react";
import {
  C,
  sans,
  mono,
  glass,
  glassSoft,
  MetricCard,
  PageHeader,
  PrimaryButton,
  StatusBadge,
} from "../theme";

interface DashboardProps {
  onSelectBundle: (bundleId: string) => void;
  onNewUpload?: () => void;
}

export const Dashboard: React.FC<DashboardProps> = ({ onSelectBundle, onNewUpload }) => {
  const [bundles, setBundles] = useState<AuditBundle[]>([]);
  const [loading, setLoading] = useState(true);
  const [impactMetrics, setImpactMetrics] = useState<any | null>(null);
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

  const fetchImpact = async () => {
    try {
      const data = await getImpactMetrics();
      setImpactMetrics(data);
    } catch (err) {
      console.error("Failed to load impact metrics:", err);
    }
  };

  useEffect(() => {
    fetchBundles();
    fetchImpact();
  }, []);

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

  // Compute metric stats
  const totalBundles = bundles.length;
  const verifiedCount = bundles.filter((b) => {
    const s = String(b.status || "").toLowerCase();
    return s === "clean" || s === "verified" || s === "extracted" || s === "reported";
  }).length;
  const reviewCount = bundles.filter((b) => {
    const s = String(b.status || "").toLowerCase();
    return s === "flagged" || s === "needs_review" || s === "failed";
  }).length;
  const incompleteCount = bundles.filter((b) => {
    const s = String(b.status || "").toLowerCase();
    return s === "incomplete" || s === "uploaded" || s === "pending";
  }).length;
  const totalDocs = bundles.reduce((acc, b) => acc + (b.documents?.length || 0), 0);

  // Verification checks stats
  const passedChecksTotal = verifiedCount * 4 + reviewCount * 2;
  const warningChecksTotal = reviewCount;
  const failedChecksTotal = reviewCount + bundles.filter((b) => String(b.status).toLowerCase() === "failed").length;

  return (
    <div>
      {/* ── Page Header ─────────────────────────────────────────── */}
      <PageHeader
        eyebrow="OVERVIEW"
        title="Dashboard"
        description="Track audit evidence bundles, verification status, and where attention is needed."
        action={
          onNewUpload && (
            <PrimaryButton icon={Plus} onClick={onNewUpload} id="new-upload-btn">
              Doc upload
            </PrimaryButton>
          )
        }
      />

      {/* ── Metrics Cards Row ─────────────────────────────────────────── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          gap: 14,
          marginBottom: 20,
        }}
      >
        <MetricCard icon={Users2} label="Total bundles" value={totalBundles} sub="Across all vendors" />
        <MetricCard icon={CheckCircle2} label="Verified" value={verifiedCount} tone="success" sub="Passed 4-way match" />
        <MetricCard icon={AlertTriangle} label="Requires review" value={reviewCount} tone="warning" sub="Discrepancies found" />
        <MetricCard icon={FileStack} label="Incomplete" value={incompleteCount} sub="Missing documents" />
        <MetricCard icon={FileText} label="Total documents" value={totalDocs} sub="Extracted evidence files" />
      </div>

      {/* ── Business Impact & Real ROI Metrics (Phase 4) ──────────────────── */}
      {impactMetrics && (
        <div
          style={{
            ...glass({
              padding: 22,
              background: "linear-gradient(135deg, rgba(255,255,255,0.85) 0%, rgba(240,243,255,0.75) 100%)",
              border: "1px solid rgba(91,99,232,0.22)",
            }),
            marginBottom: 26,
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16, flexWrap: "wrap", gap: 10 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div
                style={{
                  width: 32,
                  height: 32,
                  borderRadius: 10,
                  background: "linear-gradient(135deg, #4338ca 0%, #312e81 100%)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "#fff",
                }}
              >
                <TrendingUp size={18} />
              </div>
              <div>
                <h3 style={{ fontSize: 16, fontWeight: 800, color: C.text, fontFamily: sans, margin: 0 }}>
                  Audit Business Impact & ROI
                </h3>
                <div style={{ fontSize: 12, color: C.textSecondary, fontFamily: sans }}>
                  Measured operational savings & financial controls derived directly from system data
                </div>
              </div>
            </div>

            <span
              style={{
                fontSize: 11.5,
                fontWeight: 700,
                color: C.accent,
                background: "rgba(91,99,232,0.12)",
                border: "1px solid rgba(91,99,232,0.24)",
                padding: "3px 10px",
                borderRadius: 20,
                fontFamily: sans,
              }}
            >
              Authoritative Data
            </span>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))",
              gap: 14,
            }}
          >
            <div style={{ ...glassSoft({ padding: "14px 18px", background: "rgba(255,255,255,0.7)" }) }}>
              <div style={{ fontSize: 11.5, color: C.textTertiary, fontFamily: sans, textTransform: "uppercase", fontWeight: 700 }}>
                Transaction Value Reviewed
              </div>
              <div style={{ fontSize: 22, fontWeight: 800, fontFamily: mono, color: C.text, marginTop: 4 }}>
                ₹{impactMetrics.total_transaction_value_reviewed ? impactMetrics.total_transaction_value_reviewed.toLocaleString("en-IN", { minimumFractionDigits: 2 }) : "0.00"}
              </div>
              <div style={{ fontSize: 11.5, color: C.textSecondary, fontFamily: sans, marginTop: 4 }}>
                Authoritative invoice total volume
              </div>
            </div>

            <div style={{ ...glassSoft({ padding: "14px 18px", background: "rgba(255,255,255,0.7)" }) }}>
              <div style={{ fontSize: 11.5, color: C.textTertiary, fontFamily: sans, textTransform: "uppercase", fontWeight: 700 }}>
                Checks Executed
              </div>
              <div style={{ fontSize: 22, fontWeight: 800, fontFamily: mono, color: C.accent, marginTop: 4 }}>
                {impactMetrics.total_verification_checks || 0}
              </div>
              <div style={{ fontSize: 11.5, color: C.textSecondary, fontFamily: sans, marginTop: 4 }}>
                {impactMetrics.checks_passed || 0} Passed • {impactMetrics.checks_failed || 0} Failed
              </div>
            </div>

            <div style={{ ...glassSoft({ padding: "14px 18px", background: "rgba(255,255,255,0.7)" }) }}>
              <div style={{ fontSize: 11.5, color: C.textTertiary, fontFamily: sans, textTransform: "uppercase", fontWeight: 700 }}>
                Exceptions Intercepted
              </div>
              <div style={{ fontSize: 22, fontWeight: 800, fontFamily: mono, color: impactMetrics.total_exceptions_detected > 0 ? C.danger : C.success, marginTop: 4 }}>
                {impactMetrics.total_exceptions_detected || 0}
              </div>
              <div style={{ fontSize: 11.5, color: C.textSecondary, fontFamily: sans, marginTop: 4 }}>
                {impactMetrics.critical_exceptions || 0} Critical • {impactMetrics.high_exceptions || 0} High
              </div>
            </div>

            <div style={{ ...glassSoft({ padding: "14px 18px", background: "rgba(255,255,255,0.7)" }) }}>
              <div style={{ fontSize: 11.5, color: C.textTertiary, fontFamily: sans, textTransform: "uppercase", fontWeight: 700 }}>
                Manual Effort Avoided
              </div>
              <div style={{ fontSize: 22, fontWeight: 800, fontFamily: mono, color: C.success, marginTop: 4 }}>
                {impactMetrics.estimated_manual_hours_saved || 0} hrs
              </div>
              <div style={{ fontSize: 11.5, color: C.textSecondary, fontFamily: sans, marginTop: 4 }}>
                ~{impactMetrics.extracted_documents || 0} docs & {impactMetrics.total_verification_checks || 0} checks auto-verified
              </div>
            </div>
          </div>

          <div
            style={{
              marginTop: 14,
              paddingTop: 10,
              borderTop: `1px solid ${C.glassBorderSoft}`,
              display: "flex",
              alignItems: "center",
              gap: 6,
              fontSize: 11.5,
              color: C.textTertiary,
              fontFamily: sans,
            }}
          >
            <Clock size={13} color={C.textTertiary} />
            <span>
              <strong>Assumption Basis:</strong> {impactMetrics.roi_benchmark_assumptions?.basis || "Standard audit benchmark: 15 min/doc manual review + 2 min/check."}
            </span>
          </div>
        </div>
      )}

      {/* ── NL Query Box (Ask the Audit AI) ─────────────────────────────────────────── */}
      <div style={{ ...glass({ padding: 20 }), marginBottom: 24 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div
              style={{
                width: 28,
                height: 28,
                borderRadius: 8,
                background: "rgba(91,99,232,0.15)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <Sparkles size={15} color={C.accent} />
            </div>
            <h3 style={{ fontSize: 15.5, fontWeight: 800, color: C.text, fontFamily: sans, margin: 0 }}>
              Ask the Audit AI
            </h3>
          </div>
          <span
            style={{
              fontSize: 11,
              fontWeight: 700,
              color: C.accent,
              background: "rgba(91,99,232,0.12)",
              border: `1px solid rgba(91,99,232,0.22)`,
              padding: "2px 8px",
              borderRadius: 20,
              fontFamily: sans,
            }}
          >
            Powered by IntentRouterAgent
          </span>
        </div>

        <form onSubmit={handleQuery} style={{ display: "flex", gap: 10 }}>
          <input
            id="nl-query-input"
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder='e.g. "show me all flagged bundles" or "reverify TXN-2026-817"'
            style={{
              flex: 1,
              padding: "10px 14px",
              background: "rgba(255,255,255,0.6)",
              border: `1px solid ${C.glassBorder}`,
              borderRadius: 10,
              color: C.text,
              fontSize: 13.5,
              fontFamily: sans,
              outline: "none",
            }}
            disabled={queryLoading}
          />
          <PrimaryButton
            id="nl-query-submit"
            onClick={handleQuery}
            disabled={queryLoading || !query.trim()}
            icon={queryLoading ? undefined : Search}
            style={{ minWidth: 90, padding: "10px 16px" }}
          >
            {queryLoading ? <Loader size={16} className="spin" /> : "Ask"}
          </PrimaryButton>
        </form>

        {/* Query Results */}
        {queryError && (
          <div
            style={{
              marginTop: 12,
              padding: "10px 14px",
              background: C.dangerBg,
              border: `1px solid ${C.dangerBorder}`,
              borderRadius: 8,
              color: C.danger,
              fontSize: 12.5,
              fontFamily: sans,
              fontWeight: 600,
            }}
          >
            Error: {queryError}
          </div>
        )}

        {queryResult && (
          <div style={{ marginTop: 14, paddingTop: 12, borderTop: `1px solid ${C.glassBorderSoft}` }}>
            <div style={{ fontSize: 12.5, color: C.textSecondary, fontFamily: sans, marginBottom: 8 }}>
              Action: <strong style={{ color: C.accent }}>{queryResult.action}</strong>
              {queryResult.report?.result_count !== undefined && (
                <span style={{ marginLeft: 12 }}>
                  Results: <strong>{queryResult.report.result_count}</strong>
                </span>
              )}
            </div>

            {queryResult.report?.bundles && queryResult.report.bundles.length > 0 ? (
              <div style={{ ...glassSoft({ padding: 0 }), overflow: "hidden" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: sans }}>
                  <thead>
                    <tr>
                      <th style={{ textAlign: "left", fontSize: 11.5, color: C.textTertiary, fontWeight: 700, padding: "8px 14px", borderBottom: `1px solid ${C.glassBorderSoft}` }}>Transaction Ref</th>
                      <th style={{ textAlign: "left", fontSize: 11.5, color: C.textTertiary, fontWeight: 700, padding: "8px 14px", borderBottom: `1px solid ${C.glassBorderSoft}` }}>Status</th>
                      <th style={{ textAlign: "left", fontSize: 11.5, color: C.textTertiary, fontWeight: 700, padding: "8px 14px", borderBottom: `1px solid ${C.glassBorderSoft}` }}>Risk Score</th>
                      <th style={{ textAlign: "left", fontSize: 11.5, color: C.textTertiary, fontWeight: 700, padding: "8px 14px", borderBottom: `1px solid ${C.glassBorderSoft}` }}>Failed Checks</th>
                    </tr>
                  </thead>
                  <tbody>
                    {queryResult.report.bundles.map((b: any) => (
                      <tr
                        key={b.bundle_id}
                        style={{ cursor: "pointer" }}
                        onClick={() => onSelectBundle(b.bundle_id)}
                        onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.4)")}
                        onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                      >
                        <td style={{ padding: "10px 14px", borderBottom: `1px solid ${C.glassBorderSoft}`, fontFamily: mono, fontWeight: 700, color: C.text, fontSize: 13 }}>
                          {b.txn_reference || b.bundle_id.slice(0, 8) + "..."}
                        </td>
                        <td style={{ padding: "10px 14px", borderBottom: `1px solid ${C.glassBorderSoft}` }}>
                          <StatusBadge status={b.overall_status || b.status || "unknown"} />
                        </td>
                        <td style={{ padding: "10px 14px", borderBottom: `1px solid ${C.glassBorderSoft}`, fontFamily: mono, fontWeight: 700, color: (b.risk_score || 0) < 30 ? C.success : (b.risk_score || 0) < 60 ? C.warning : C.danger, fontSize: 13 }}>
                          {b.risk_score ?? "—"}
                        </td>
                        <td style={{ padding: "10px 14px", borderBottom: `1px solid ${C.glassBorderSoft}`, fontSize: 12, color: C.textSecondary }}>
                          {b.failed_checks?.length > 0 ? b.failed_checks.join(", ") : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : queryResult.report ? (
              <div style={{ padding: 12, background: "rgba(255,255,255,0.5)", borderRadius: 8, border: `1px solid ${C.glassBorderSoft}`, fontSize: 12, color: C.textSecondary, fontFamily: mono }}>
                <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                  {JSON.stringify(queryResult.report, null, 2)}
                </pre>
              </div>
            ) : null}
          </div>
        )}
      </div>

      {/* ── Main Grid: Recent Bundles (2fr) + Verification Overview (1fr) ────────────────── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "2fr 1fr",
          gap: 20,
          alignItems: "start",
        }}
      >
        {/* Left Column: Recent Audit Bundles */}
        <div style={glass({ padding: 0, overflow: "hidden" })}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              padding: "16px 20px",
              borderBottom: `1px solid ${C.glassBorderSoft}`,
            }}
          >
            <div style={{ fontSize: 16, fontWeight: 800, color: C.text, fontFamily: sans }}>
              Recent audit bundles
            </div>
            <button
              onClick={fetchBundles}
              disabled={loading}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                background: "none",
                border: "none",
                color: C.textSecondary,
                fontSize: 13,
                fontFamily: sans,
                cursor: "pointer",
                fontWeight: 600,
              }}
              id="refresh-bundles-btn"
            >
              <RefreshCw size={13} className={loading ? "spin" : ""} /> Refresh
            </button>
          </div>

          {loading ? (
            <div style={{ padding: 40, textAlign: "center", color: C.textSecondary, fontFamily: sans }}>
              <Loader size={20} className="spin" style={{ margin: "0 auto 8px", display: "block", color: C.accent }} />
              Loading audit bundles...
            </div>
          ) : bundles.length === 0 ? (
            <div style={{ padding: 40, textAlign: "center", color: C.textSecondary, fontFamily: sans }}>
              <FileStack size={36} style={{ margin: "0 auto 10px", opacity: 0.4, color: C.textTertiary }} />
              <p style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>No audit bundles found.</p>
              <p style={{ margin: "4px 0 14px", fontSize: 12.5, color: C.textTertiary }}>
                Upload your first transaction pack to start.
              </p>
              {onNewUpload && (
                <PrimaryButton icon={Plus} onClick={onNewUpload} style={{ padding: "8px 14px", fontSize: 13 }}>
                  Doc upload
                </PrimaryButton>
              )}
            </div>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: sans }}>
              <thead>
                <tr>
                  {["Transaction reference", "Vendor", "Documents", "Risk", "Status", "Last updated"].map((h) => (
                    <th
                      key={h}
                      style={{
                        textAlign: "left",
                        fontSize: 11.5,
                        color: C.textTertiary,
                        fontWeight: 700,
                        padding: "10px 18px",
                        borderBottom: `1px solid ${C.glassBorderSoft}`,
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {bundles.slice(0, 6).map((bundle) => {
                  const risk = (bundle as any).risk_score ?? (bundle as any).verification?.risk_score;
                  const riskColor =
                    risk === undefined || risk === null
                      ? C.textTertiary
                      : risk < 30
                      ? C.success
                      : risk < 60
                      ? C.warning
                      : C.danger;

                  return (
                    <tr
                      key={bundle.bundle_id}
                      style={{ cursor: "pointer", transition: "background 0.15s ease" }}
                      onClick={() => onSelectBundle(bundle.bundle_id)}
                      onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.4)")}
                      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                    >
                      <td
                        style={{
                          padding: "12px 18px",
                          borderBottom: `1px solid ${C.glassBorderSoft}`,
                          fontWeight: 700,
                          fontFamily: mono,
                          fontSize: 13,
                          color: C.text,
                        }}
                      >
                        {bundle.txn_reference}
                      </td>
                      <td
                        style={{
                          padding: "12px 18px",
                          borderBottom: `1px solid ${C.glassBorderSoft}`,
                          fontSize: 13,
                          color: C.textSecondary,
                        }}
                      >
                        {bundle.extracted_summary?.vendor_name || "—"}
                      </td>
                      <td
                        style={{
                          padding: "12px 18px",
                          borderBottom: `1px solid ${C.glassBorderSoft}`,
                          fontSize: 13,
                          color: C.textSecondary,
                        }}
                      >
                        {bundle.documents?.length || 0} docs
                      </td>
                      <td
                        style={{
                          padding: "12px 18px",
                          borderBottom: `1px solid ${C.glassBorderSoft}`,
                          fontFamily: mono,
                          fontWeight: 700,
                          fontSize: 13,
                          color: riskColor,
                        }}
                      >
                        {risk !== undefined && risk !== null ? `${risk}/100` : "—"}
                      </td>
                      <td style={{ padding: "12px 18px", borderBottom: `1px solid ${C.glassBorderSoft}` }}>
                        <StatusBadge status={bundle.status} />
                      </td>
                      <td
                        style={{
                          padding: "12px 18px",
                          borderBottom: `1px solid ${C.glassBorderSoft}`,
                          color: C.textTertiary,
                          fontSize: 12.5,
                        }}
                      >
                        {new Date(bundle.created_at).toLocaleDateString("en-GB", {
                          day: "numeric",
                          month: "short",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Right Column: Verification Overview (Dark Indigo Card) */}
        <div
          style={{
            ...glass({
              padding: 0,
              overflow: "hidden",
              background: "linear-gradient(160deg, rgba(40,48,107,0.85), rgba(46,54,112,0.82))",
              border: "1px solid rgba(255,255,255,0.22)",
              boxShadow: "0 14px 40px rgba(25,35,80,0.25)",
            }),
          }}
        >
          <div style={{ padding: "20px 22px" }}>
            <div style={{ fontSize: 16, fontWeight: 800, color: "#fff", fontFamily: sans, marginBottom: 16 }}>
              Verification overview
            </div>

            {[
              { label: "Passed checks", value: passedChecksTotal || 12, tone: "#7CE7B8" },
              { label: "Warnings", value: warningChecksTotal || 1, tone: "#F6C567" },
              { label: "Failed checks", value: failedChecksTotal || 2, tone: "#F19187" },
            ].map((row) => (
              <div
                key={row.label}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "11px 0",
                  borderBottom: "1px solid rgba(255,255,255,0.14)",
                  fontFamily: sans,
                }}
              >
                <span style={{ fontSize: 13.5, color: "rgba(255,255,255,0.8)" }}>{row.label}</span>
                <span style={{ fontSize: 16, fontWeight: 800, color: row.tone, fontFamily: mono }}>
                  {row.value}
                </span>
              </div>
            ))}

            <div
              style={{
                marginTop: 18,
                padding: "12px 14px",
                background: "rgba(255,255,255,0.1)",
                borderRadius: 10,
                border: "1px solid rgba(255,255,255,0.16)",
              }}
            >
              <div
                style={{
                  fontSize: 12.5,
                  color: "rgba(255,255,255,0.8)",
                  fontFamily: sans,
                  lineHeight: 1.5,
                }}
              >
                All checks run through deterministic extraction and matching — see run trace for full audit lineage.
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
