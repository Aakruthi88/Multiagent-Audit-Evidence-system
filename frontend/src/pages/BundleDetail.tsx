import React, { useEffect, useState, useCallback } from "react";
import { runAction, getBundle, getBundleTrace, getLatestVerificationRun, exportWorkpaper } from "../api/endpoints";
import { AuditBundle, AgentLog, VerificationRun } from "../types";
import { DocumentPreviewCard } from "../components/DocumentPreviewCard";
import { VerificationPanel } from "../components/VerificationPanel";
import { RefreshCw, ArrowLeft, Cpu, CheckCircle2, AlertTriangle, Sparkles, FileDown, Loader2 } from "lucide-react";
import {
  C,
  sans,
  mono,
  glass,
  glassSoft,
  StatusBadge,
  PrimaryButton,
  SecondaryButton,
} from "../theme";

interface BundleDetailProps {
  bundleId: string;
  onBack: () => void;
}

export const BundleDetail: React.FC<BundleDetailProps> = ({ bundleId, onBack }) => {
  const [bundle, setBundle] = useState<AuditBundle | null>(null);
  const [logs, setLogs] = useState<AgentLog[]>([]);
  const [existingRun, setExistingRun] = useState<VerificationRun | null>(null);
  const [runReport, setRunReport] = useState<any | null>(null);
  const [runLoading, setRunLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    try {
      const data = await getBundle(bundleId);
      setBundle(data);

      const logData = await getBundleTrace(bundleId);
      setLogs(logData);

      // Try to load the latest verification run (if one exists)
      try {
        const runData = await getLatestVerificationRun(bundleId);
        setExistingRun(runData);
      } catch {
        // 404 is expected when no run exists yet - ignore
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [bundleId]);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 5000);
    return () => clearInterval(interval);
  }, [loadData]);

  if (loading && !bundle) {
    return (
      <div style={{ padding: 48, textAlign: "center", color: C.textSecondary, fontFamily: sans }}>
        <RefreshCw size={24} className="spin" style={{ margin: "0 auto 10px", display: "block", color: C.accent }} />
        Loading bundle details...
      </div>
    );
  }

  if (!bundle) {
    return (
      <div style={{ padding: 48, textAlign: "center", color: C.textSecondary, fontFamily: sans }}>
        Bundle not found.
      </div>
    );
  }

  const extractedDocs = bundle.documents?.filter((d) => d.extraction_status === "success") ?? [];
  const canVerify = extractedDocs.length > 0;

  const handleExportWorkpaper = async () => {
    setExporting(true);
    setExportError(null);
    try {
      await exportWorkpaper(bundleId, bundle?.txn_reference);
    } catch (err: any) {
      console.error(err);
      setExportError(err?.response?.data?.detail || "Failed to download audit workpaper PDF.");
    } finally {
      setExporting(false);
    }
  };

  return (
    <div>
      {/* Back Button */}
      <button
        onClick={onBack}
        id="back-to-dashboard"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          background: "none",
          border: "none",
          color: C.textSecondary,
          fontSize: 13.5,
          fontFamily: sans,
          cursor: "pointer",
          marginBottom: 18,
          fontWeight: 600,
          padding: 0,
        }}
      >
        <ArrowLeft size={15} /> Back to dashboard
      </button>

      {/* Bundle Header Card */}
      <div style={{ ...glass({ padding: 26 }), marginBottom: 22 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 16 }}>
          <div>
            <div style={{ fontSize: 12, color: C.textTertiary, fontFamily: sans, fontWeight: 700, letterSpacing: 0.4, textTransform: "uppercase" }}>
              TRANSACTION REFERENCE
            </div>
            <h2 style={{ fontSize: 28, fontWeight: 800, fontFamily: mono, color: C.text, margin: "4px 0 8px 0", letterSpacing: "-0.02em" }}>
              {bundle.txn_reference}
            </h2>
            <div style={{ fontSize: 12.5, color: C.textTertiary, fontFamily: mono }}>
              Bundle ID: {bundle.bundle_id}
            </div>
            <div style={{ fontSize: 12.5, color: C.textTertiary, fontFamily: sans, marginTop: 2 }}>
              Created {new Date(bundle.created_at).toLocaleString()}
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 10 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <StatusBadge status={bundle.status} />
              <SecondaryButton onClick={loadData} id="sync-status-btn" icon={RefreshCw} style={{ padding: "6px 12px", fontSize: 12.5 }}>
                Sync
              </SecondaryButton>
            </div>

            <PrimaryButton
              id="export-workpaper-btn"
              onClick={handleExportWorkpaper}
              disabled={exporting}
              icon={exporting ? undefined : FileDown}
              style={{
                padding: "8px 16px",
                fontSize: 13,
                fontWeight: 700,
                background: "linear-gradient(135deg, #1e293b 0%, #334155 100%)",
                boxShadow: "0 4px 12px rgba(15,23,42,0.18)",
              }}
            >
              {exporting ? (
                <>
                  <Loader2 size={14} className="spin" style={{ marginRight: 6 }} /> Generating PDF...
                </>
              ) : (
                "Export Audit Workpaper"
              )}
            </PrimaryButton>
          </div>
        </div>

        {exportError && (
          <div
            style={{
              marginTop: 14,
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
            {exportError}
          </div>
        )}

        {/* Document coverage bar */}
        <div style={{ marginTop: 20, paddingTop: 16, borderTop: `1px solid ${C.glassBorderSoft}` }}>
          <div style={{ fontSize: 12, color: C.textTertiary, fontFamily: sans, fontWeight: 700, letterSpacing: 0.3, marginBottom: 10, textTransform: "uppercase" }}>
            DOCUMENT COVERAGE - {extractedDocs.length} / {bundle.documents?.length ?? 0} EXTRACTED
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {(["purchase_order", "invoice", "grn", "bank_statement"] as const).map((dt) => {
              const doc = bundle.documents?.find((d) => d.doc_type === dt);
              const ok = doc?.extraction_status === "success";
              const pending = doc && doc.extraction_status !== "success";

              return (
                <span
                  key={dt}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    padding: "6px 12px",
                    borderRadius: 8,
                    fontSize: 12,
                    fontWeight: 700,
                    textTransform: "capitalize",
                    fontFamily: sans,
                    background: ok ? C.successBg : pending ? C.warningBg : "rgba(120,125,145,0.12)",
                    color: ok ? C.success : pending ? C.warning : C.textTertiary,
                    border: `1px solid ${ok ? C.successBorder : pending ? C.warningBorder : "rgba(120,125,145,0.22)"}`,
                  }}
                >
                  {ok ? (
                    <CheckCircle2 size={13} strokeWidth={2.4} />
                  ) : pending ? (
                    <AlertTriangle size={13} strokeWidth={2.4} />
                  ) : (
                    <span style={{ width: 13, textAlign: "center" }}>-</span>
                  )}
                  {dt.replace(/_/g, " ")}
                </span>
              );
            })}
          </div>
          {!canVerify && (
            <div style={{ marginTop: 10, fontSize: 12.5, color: C.warning, fontFamily: sans, fontWeight: 600 }}>
              * Upload and extract documents before running verification.
            </div>
          )}
        </div>
      </div>

      {/* Documents Section */}
      <div style={{ marginBottom: 24 }}>
        <h3 style={{ fontSize: 16, fontWeight: 800, color: C.text, fontFamily: sans, marginBottom: 14, display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ width: 4, height: 18, background: C.accent, borderRadius: 2, display: "inline-block" }} />
          Attached Documents ({bundle.documents?.length || 0})
        </h3>
        {bundle.documents?.map((doc) => (
          <DocumentPreviewCard key={doc.document_id} document={doc} />
        ))}
      </div>

      {/* Verification Panel */}
      <VerificationPanel bundleId={bundleId} initialRun={existingRun} />

      {/* Vendor Similarity Matches */}
      {existingRun && (
        <div style={{ ...glass({ padding: 22 }), marginTop: 24 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
            <div
              style={{
                width: 28,
                height: 28,
                borderRadius: 8,
                background: "rgba(91,99,232,0.14)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <Sparkles size={15} color={C.accent} />
            </div>
            <h3 style={{ fontSize: 16, fontWeight: 800, color: C.text, fontFamily: sans, margin: 0 }}>
              Similar Vendors in Other Bundles
            </h3>
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
              ChromaDB Vector Similarity
            </span>
          </div>

          {bundle.extracted_summary?.vendor_similarity_matches?.length > 0 ? (
            <div style={{ ...glassSoft({ padding: 0 }), overflow: "hidden" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: sans }}>
                <thead>
                  <tr>
                    <th style={{ textAlign: "left", fontSize: 12, color: C.textTertiary, fontWeight: 700, padding: "10px 18px", borderBottom: `1px solid ${C.glassBorderSoft}` }}>Bundle ID</th>
                    <th style={{ textAlign: "left", fontSize: 12, color: C.textTertiary, fontWeight: 700, padding: "10px 18px", borderBottom: `1px solid ${C.glassBorderSoft}` }}>Vendor Name</th>
                    <th style={{ textAlign: "left", fontSize: 12, color: C.textTertiary, fontWeight: 700, padding: "10px 18px", borderBottom: `1px solid ${C.glassBorderSoft}` }}>Similarity Score</th>
                  </tr>
                </thead>
                <tbody>
                  {(bundle.extracted_summary?.vendor_similarity_matches || []).map((m: any, i: number) => (
                    <tr key={i}>
                      <td style={{ padding: "12px 18px", borderBottom: `1px solid ${C.glassBorderSoft}`, fontFamily: mono, fontSize: 12.5, color: C.textSecondary }}>
                        {m.bundle_id?.slice(0, 8)}...
                      </td>
                      <td style={{ padding: "12px 18px", borderBottom: `1px solid ${C.glassBorderSoft}`, fontWeight: 700, color: C.text }}>
                        {m.vendor_name}
                      </td>
                      <td style={{ padding: "12px 18px", borderBottom: `1px solid ${C.glassBorderSoft}` }}>
                        <span
                          style={{
                            padding: "3px 10px",
                            borderRadius: 20,
                            fontSize: 12,
                            fontWeight: 700,
                            fontFamily: mono,
                            background: m.similarity_score > 0.8 ? C.dangerBg : C.warningBg,
                            color: m.similarity_score > 0.8 ? C.danger : C.warning,
                            border: `1px solid ${m.similarity_score > 0.8 ? C.dangerBorder : C.warningBorder}`,
                          }}
                        >
                          {(m.similarity_score * 100).toFixed(1)}%
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p style={{ color: C.textSecondary, fontSize: 13, fontFamily: sans, margin: 0 }}>
              No similar vendors found in other bundles (vector search returned no matches).
            </p>
          )}
        </div>
      )}

      {/* Run Full Pipeline Button + Report */}
      <div style={{ ...glass({ padding: 22 }), marginTop: 24 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14, flexWrap: "wrap", gap: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div
              style={{
                width: 28,
                height: 28,
                borderRadius: 8,
                background: "rgba(91,99,232,0.14)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <Cpu size={15} color={C.accent} />
            </div>
            <h3 style={{ fontSize: 16, fontWeight: 800, color: C.text, fontFamily: sans, margin: 0 }}>
              AI Audit Report
            </h3>
          </div>

          <PrimaryButton
            id="run-pipeline-btn"
            disabled={runLoading}
            onClick={async () => {
              setRunLoading(true);
              try {
                const result = await runAction(bundleId, "new_bundle_run");
                setRunReport(result.report);
              } catch (e) {
                console.error(e);
              } finally {
                setRunLoading(false);
                loadData();
              }
            }}
            icon={runLoading ? undefined : Sparkles}
          >
            {runLoading ? "Running pipeline..." : "Run Full Pipeline"}
          </PrimaryButton>
        </div>

        {runReport ? (
          <div>
            <div style={{ display: "flex", gap: 14, marginBottom: 16, flexWrap: "wrap" }}>
              <div style={{ ...glassSoft({ padding: "12px 18px", flex: 1, minWidth: 140 }), background: "rgba(255,255,255,0.4)" }}>
                <div style={{ fontSize: 11.5, color: C.textTertiary, fontFamily: sans, textTransform: "uppercase", fontWeight: 700 }}>Verdict</div>
                <div style={{ fontSize: 18, fontWeight: 800, fontFamily: sans, color: runReport.verdict === "clean" ? C.success : C.danger, marginTop: 2 }}>
                  {runReport.verdict?.toUpperCase() || "-"}
                </div>
              </div>
              <div style={{ ...glassSoft({ padding: "12px 18px", flex: 1, minWidth: 140 }), background: "rgba(255,255,255,0.4)" }}>
                <div style={{ fontSize: 11.5, color: C.textTertiary, fontFamily: sans, textTransform: "uppercase", fontWeight: 700 }}>Risk Score</div>
                <div style={{ fontSize: 18, fontWeight: 800, fontFamily: mono, color: (runReport.risk_score || 0) > 50 ? C.danger : C.success, marginTop: 2 }}>
                  {runReport.risk_score ?? "-"}
                </div>
              </div>
              <div style={{ ...glassSoft({ padding: "12px 18px", flex: 1, minWidth: 140 }), background: "rgba(255,255,255,0.4)" }}>
                <div style={{ fontSize: 11.5, color: C.textTertiary, fontFamily: sans, textTransform: "uppercase", fontWeight: 700 }}>Checks Passed</div>
                <div style={{ fontSize: 18, fontWeight: 800, fontFamily: sans, color: C.text, marginTop: 2 }}>
                  {runReport.checks_passed ?? "-"} / {runReport.checks_total ?? "-"}
                </div>
              </div>
            </div>

            {runReport.narrative && (
              <div
                style={{
                  padding: 16,
                  background: "rgba(255,255,255,0.5)",
                  borderRadius: 12,
                  border: `1px solid ${C.glassBorderSoft}`,
                  fontSize: 13.5,
                  fontFamily: sans,
                  lineHeight: 1.6,
                  color: C.text,
                  whiteSpace: "pre-wrap",
                }}
              >
                {runReport.narrative}
              </div>
            )}

            {runReport.note && !runReport.narrative && (
              <div
                style={{
                  padding: 14,
                  background: C.successBg,
                  borderRadius: 10,
                  border: `1px solid ${C.successBorder}`,
                  fontSize: 13.5,
                  color: C.success,
                  fontFamily: sans,
                  fontWeight: 600,
                }}
              >
                {runReport.note}
              </div>
            )}
          </div>
        ) : (
          <p style={{ color: C.textSecondary, fontSize: 13, fontFamily: sans, margin: 0 }}>
            Click "Run Full Pipeline" to trigger the LangGraph audit and generate a complete narrative report.
          </p>
        )}
      </div>

      {/* Agent Execution Trace */}
      <div style={{ ...glass({ padding: 22 }), marginTop: 24 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
          <div
            style={{
              width: 28,
              height: 28,
              borderRadius: 8,
              background: "rgba(91,99,232,0.14)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <Cpu size={15} color={C.accent} />
          </div>
          <h3 style={{ fontSize: 16, fontWeight: 800, color: C.text, fontFamily: sans, margin: 0 }}>
            LangGraph Agent Trace
          </h3>
          <span
            style={{
              fontSize: 11,
              fontWeight: 700,
              padding: "2px 8px",
              borderRadius: 20,
              background: "rgba(120,125,145,0.12)",
              color: C.textSecondary,
              fontFamily: sans,
            }}
          >
            {logs.length} entries
          </span>
        </div>

        {logs.length === 0 ? (
          <div style={{ fontSize: 13, color: C.textTertiary, fontFamily: sans, fontStyle: "italic" }}>
            No execution trace entries logged yet.
          </div>
        ) : (
          <div style={{ ...glassSoft({ padding: 0 }), overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: sans }}>
              <thead>
                <tr>
                  <th style={{ textAlign: "left", fontSize: 12, color: C.textTertiary, fontWeight: 700, padding: "10px 18px", borderBottom: `1px solid ${C.glassBorderSoft}` }}>Agent</th>
                  <th style={{ textAlign: "left", fontSize: 12, color: C.textTertiary, fontWeight: 700, padding: "10px 18px", borderBottom: `1px solid ${C.glassBorderSoft}` }}>Model</th>
                  <th style={{ textAlign: "left", fontSize: 12, color: C.textTertiary, fontWeight: 700, padding: "10px 18px", borderBottom: `1px solid ${C.glassBorderSoft}` }}>Tokens</th>
                  <th style={{ textAlign: "left", fontSize: 12, color: C.textTertiary, fontWeight: 700, padding: "10px 18px", borderBottom: `1px solid ${C.glassBorderSoft}` }}>Latency</th>
                  <th style={{ textAlign: "left", fontSize: 12, color: C.textTertiary, fontWeight: 700, padding: "10px 18px", borderBottom: `1px solid ${C.glassBorderSoft}` }}>Status</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log) => (
                  <tr key={log.log_id}>
                    <td style={{ padding: "12px 18px", borderBottom: `1px solid ${C.glassBorderSoft}`, fontWeight: 700, color: C.text }}>
                      {log.agent_name}
                    </td>
                    <td style={{ padding: "12px 18px", borderBottom: `1px solid ${C.glassBorderSoft}`, fontFamily: mono, fontSize: 12.5, color: C.textSecondary }}>
                      {log.model_used || "N/A"}
                    </td>
                    <td style={{ padding: "12px 18px", borderBottom: `1px solid ${C.glassBorderSoft}`, fontFamily: mono, fontSize: 12.5, color: C.text }}>
                      {log.tokens_used ?? 0}
                    </td>
                    <td style={{ padding: "12px 18px", borderBottom: `1px solid ${C.glassBorderSoft}`, fontSize: 12.5, color: C.textSecondary }}>
                      {log.latency_ms ? `${log.latency_ms} ms` : "-"}
                    </td>
                    <td style={{ padding: "12px 18px", borderBottom: `1px solid ${C.glassBorderSoft}` }}>
                      <StatusBadge status={log.status || "unknown"} />
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
