import React, { useState } from "react";
import {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  MinusCircle,
  ShieldCheck,
  ShieldAlert,
  AlertOctagon,
  FileWarning,
  Loader2,
  PlayCircle,
  ArrowRight,
  Info,
} from "lucide-react";
import {
  VerificationRun,
  VerificationCheck,
  Discrepancy,
  CheckStatus,
  Severity,
  VerificationStatus,
} from "../types";
import { triggerVerification, getLatestVerificationRun } from "../api/endpoints";
import {
  C,
  sans,
  mono,
  glass,
  glassSoft,
  RiskGauge,
  SeverityTag,
  PrimaryButton,
} from "../theme";

const STATUS_ICON: Record<CheckStatus, React.ReactNode> = {
  pass: <CheckCircle2 size={18} color={C.success} />,
  fail: <XCircle size={18} color={C.danger} />,
  warning: <AlertTriangle size={18} color={C.warning} />,
  not_applicable: <MinusCircle size={18} color={C.textTertiary} />,
};

const VERDICT_ICON: Record<VerificationStatus, React.ReactNode> = {
  clean: <CheckCircle2 size={22} color={C.success} />,
  flagged: <AlertTriangle size={22} color={C.warning} />,
  critical: <AlertOctagon size={22} color={C.danger} />,
  incomplete: <FileWarning size={22} color={C.textSecondary} />,
};

const VERDICT_LABEL: Record<VerificationStatus, string> = {
  clean: "4-Way Match PASSED — All checks clean",
  flagged: "Bundle Flagged — Discrepancies detected",
  critical: "CRITICAL — Do not approve payment",
  incomplete: "Incomplete — Missing documents",
};

function CheckRow({ check }: { check: VerificationCheck }) {
  const [expanded, setExpanded] = useState(false);
  const label = check.check_type.replace(/_/g, " ");

  return (
    <div
      onClick={() => setExpanded(!expanded)}
      style={{
        ...glassSoft({
          padding: "14px 16px",
          marginBottom: 10,
          cursor: "pointer",
          background: "rgba(255,255,255,0.35)",
        }),
        display: "grid",
        gridTemplateColumns: "26px 1fr auto",
        gap: 12,
        alignItems: "flex-start",
        transition: "all 0.15s ease",
      }}
    >
      <div style={{ paddingTop: 2 }}>{STATUS_ICON[check.status]}</div>
      <div>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, fontFamily: sans, textTransform: "capitalize" }}>
          {label}
        </div>
        <div style={{ fontSize: 13, color: C.textSecondary, fontFamily: sans, marginTop: 2, lineHeight: 1.45 }}>
          {check.explanation}
        </div>
        {expanded && (check.expected_value || check.actual_value) && (
          <div
            style={{
              marginTop: 10,
              padding: "10px 14px",
              background: "rgba(255,255,255,0.6)",
              border: `1px solid ${C.glassBorderSoft}`,
              borderRadius: 8,
              fontSize: 12.5,
              fontFamily: mono,
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 8,
            }}
          >
            <div>
              <span style={{ color: C.textTertiary }}>Expected: </span>
              <strong style={{ color: C.text }}>{check.expected_value ?? "—"}</strong>
            </div>
            <div>
              <span style={{ color: C.textTertiary }}>Actual: </span>
              <strong style={{ color: C.text }}>{check.actual_value ?? "—"}</strong>
            </div>
            {check.variance && (
              <div style={{ gridColumn: "1/-1" }}>
                <span style={{ color: C.textTertiary }}>Variance: </span>
                <span style={{ color: C.danger, fontWeight: 700 }}>{check.variance}</span>
              </div>
            )}
          </div>
        )}
      </div>

      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 }}>
        <SeverityTag level={check.severity} />
        {(check.expected_value || check.actual_value) && (
          <span style={{ fontSize: 11, color: C.accent, fontWeight: 600, fontFamily: sans }}>
            {expanded ? "Hide" : "Details"}
          </span>
        )}
      </div>
    </div>
  );
}

function DiscrepancyCard({ disc }: { disc: Discrepancy }) {
  return (
    <div
      style={{
        ...glass({
          padding: 18,
          marginBottom: 12,
        }),
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
        <SeverityTag level={disc.severity} />
        <span
          style={{
            fontSize: 12,
            fontWeight: 700,
            color: C.textTertiary,
            fontFamily: sans,
            textTransform: "uppercase",
            letterSpacing: "0.04em",
          }}
        >
          {disc.category.replace(/_/g, " ")}
        </span>
      </div>
      <p style={{ fontSize: 13.5, color: C.text, fontFamily: sans, lineHeight: 1.55, margin: "0 0 10px" }}>
        {disc.description}
      </p>
      {disc.recommended_action && (
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: 8,
            background: "rgba(255,255,255,0.5)",
            border: `1px solid ${C.glassBorderSoft}`,
            borderRadius: 9,
            padding: "9px 12px",
          }}
        >
          <ArrowRight size={14} color={C.accent} style={{ marginTop: 2, flexShrink: 0 }} />
          <span style={{ fontSize: 12.5, color: C.text, fontFamily: sans, fontWeight: 600 }}>
            {disc.recommended_action}
          </span>
        </div>
      )}
    </div>
  );
}

interface VerificationPanelProps {
  bundleId: string;
  initialRun?: VerificationRun | null;
}

type TabKey = "discrepancies" | "checks";

export const VerificationPanel: React.FC<VerificationPanelProps> = ({ bundleId, initialRun }) => {
  const [run, setRun] = useState<VerificationRun | null>(initialRun ?? null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>("discrepancies");

  const handleVerify = async () => {
    setLoading(true);
    setError(null);
    try {
      const s = await triggerVerification(bundleId);
      if (s.run_id) {
        const r = await getLatestVerificationRun(bundleId);
        setRun(r);
      }
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "Verification failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const status = run?.overall_status;
  const riskScore = run?.overall_risk_score ? parseFloat(run.overall_risk_score) : 0;
  const discrepancies = run?.discrepancies ?? [];
  const checks = run?.checks ?? [];
  const failedChecks = checks.filter((c) => c.status === "fail");
  const warnChecks = checks.filter((c) => c.status === "warning");
  const passedChecks = checks.filter((c) => c.status === "pass");

  return (
    <div style={{ ...glass({ padding: 24 }), marginTop: 24 }}>
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 20,
          flexWrap: "wrap",
          gap: 14,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div
            style={{
              width: 34,
              height: 34,
              borderRadius: 10,
              background: "rgba(91,99,232,0.14)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <ShieldAlert size={18} color={C.accent} />
          </div>
          <div>
            <h3 style={{ fontSize: 17, fontWeight: 800, color: C.text, fontFamily: sans, margin: 0 }}>
              4-Way Match Verification
            </h3>
            <div style={{ fontSize: 12.5, color: C.textSecondary, fontFamily: sans }}>
              Deterministic cross-verification against PO, Invoice, GRN & Bank Statement
            </div>
          </div>
        </div>

        <PrimaryButton
          onClick={handleVerify}
          disabled={loading}
          id="verify-bundle-btn"
          icon={loading ? undefined : PlayCircle}
        >
          {loading ? (
            <>
              <Loader2 size={16} className="spin" /> Running checks...
            </>
          ) : run ? (
            "Re-verify"
          ) : (
            "Run verification"
          )}
        </PrimaryButton>
      </div>

      {/* Error state */}
      {error && (
        <div
          style={{
            ...glassSoft({
              background: C.dangerBg,
              borderColor: C.dangerBorder,
              padding: "12px 16px",
              marginBottom: 16,
              color: C.danger,
              fontSize: 13,
              fontFamily: sans,
              fontWeight: 600,
              display: "flex",
              alignItems: "center",
              gap: 8,
            }),
          }}
        >
          <AlertOctagon size={16} /> {error}
        </div>
      )}

      {/* Not yet run */}
      {!run && !loading && (
        <div
          style={{
            textAlign: "center",
            padding: "36px 20px",
            color: C.textSecondary,
            fontFamily: sans,
          }}
        >
          <ShieldCheck size={40} style={{ margin: "0 auto 12px", display: "block", color: C.textTertiary }} />
          <div style={{ fontSize: 14.5, fontWeight: 700, color: C.text }}>
            Click <strong>Run verification</strong> to execute all deterministic 4-way match checks.
          </div>
          <div style={{ fontSize: 12.5, marginTop: 4, color: C.textTertiary }}>
            PO + Invoice + GRN + Bank Statement — 100% deterministic rules
          </div>
        </div>
      )}

      {/* Loading skeleton */}
      {loading && (
        <div style={{ textAlign: "center", padding: "40px 20px", color: C.textSecondary, fontFamily: sans }}>
          <Loader2 size={36} className="spin" style={{ margin: "0 auto 12px", display: "block", color: C.accent }} />
          <div style={{ fontWeight: 700, color: C.text, fontSize: 15 }}>Running deterministic checks...</div>
          <div style={{ fontSize: 12.5, marginTop: 4, color: C.textTertiary }}>
            Verifying amounts, item quantities, vendor entity, and dates...
          </div>
        </div>
      )}

      {/* Results */}
      {run && !loading && (
        <>
          {/* Status banner */}
          {status && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "14px 18px",
                borderRadius: 12,
                marginBottom: 20,
                fontFamily: sans,
                fontWeight: 800,
                fontSize: 14.5,
                background:
                  status === "clean"
                    ? C.successBg
                    : status === "flagged"
                    ? C.warningBg
                    : status === "critical"
                    ? C.dangerBg
                    : "rgba(120,125,145,0.12)",
                border: `1px solid ${
                  status === "clean"
                    ? C.successBorder
                    : status === "flagged"
                    ? C.warningBorder
                    : status === "critical"
                    ? C.dangerBorder
                    : "rgba(120,125,145,0.22)"
                }`,
                color:
                  status === "clean"
                    ? C.success
                    : status === "flagged"
                    ? C.warning
                    : status === "critical"
                    ? C.danger
                    : C.textSecondary,
              }}
            >
              {VERDICT_ICON[status]}
              <span>{VERDICT_LABEL[status]}</span>
            </div>
          )}

          {/* Stats row & Risk Gauge */}
          <div
            style={{
              display: "flex",
              gap: 20,
              alignItems: "center",
              marginBottom: 24,
              flexWrap: "wrap",
            }}
          >
            <RiskGauge score={riskScore} />
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(4, 1fr)",
                gap: 10,
                flex: 1,
                minWidth: 280,
              }}
            >
              {[
                { label: "Failed", value: failedChecks.length, color: C.danger },
                { label: "Warnings", value: warnChecks.length, color: C.warning },
                { label: "Passed", value: passedChecks.length, color: C.success },
                {
                  label: "Issues",
                  value: discrepancies.filter((d) => d.severity === "critical" || d.severity === "high").length,
                  color: C.accent,
                },
              ].map((st) => (
                <div
                  key={st.label}
                  style={{
                    ...glassSoft({
                      padding: "14px 10px",
                      textAlign: "center",
                      background: "rgba(255,255,255,0.35)",
                    }),
                  }}
                >
                  <div style={{ fontSize: 24, fontWeight: 800, color: st.color, fontFamily: sans, lineHeight: 1 }}>
                    {st.value}
                  </div>
                  <div style={{ fontSize: 12, color: C.textTertiary, fontFamily: sans, marginTop: 4 }}>
                    {st.label}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Tabs */}
          <div
            style={{
              display: "flex",
              gap: 12,
              borderBottom: `1px solid ${C.glassBorderSoft}`,
              marginBottom: 16,
              paddingBottom: 6,
            }}
          >
            <button
              onClick={() => setTab("discrepancies")}
              id="tab-discrepancies"
              style={{
                background: tab === "discrepancies" ? "rgba(91,99,232,0.14)" : "none",
                border: "none",
                padding: "8px 14px",
                borderRadius: 8,
                fontSize: 13.5,
                fontWeight: tab === "discrepancies" ? 700 : 500,
                color: tab === "discrepancies" ? C.primary : C.textSecondary,
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: 8,
                fontFamily: sans,
              }}
            >
              <AlertOctagon size={14} />
              Discrepancies
              {discrepancies.length > 0 && (
                <span
                  style={{
                    background: discrepancies.some((d) => d.severity === "critical" || d.severity === "high")
                      ? C.dangerBg
                      : C.warningBg,
                    color: discrepancies.some((d) => d.severity === "critical" || d.severity === "high")
                      ? C.danger
                      : C.warning,
                    border: `1px solid ${
                      discrepancies.some((d) => d.severity === "critical" || d.severity === "high")
                        ? C.dangerBorder
                        : C.warningBorder
                    }`,
                    borderRadius: 20,
                    padding: "1px 7px",
                    fontSize: 11.5,
                    fontWeight: 700,
                  }}
                >
                  {discrepancies.length}
                </span>
              )}
            </button>
            <button
              onClick={() => setTab("checks")}
              id="tab-checks"
              style={{
                background: tab === "checks" ? "rgba(91,99,232,0.14)" : "none",
                border: "none",
                padding: "8px 14px",
                borderRadius: 8,
                fontSize: 13.5,
                fontWeight: tab === "checks" ? 700 : 500,
                color: tab === "checks" ? C.primary : C.textSecondary,
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: 8,
                fontFamily: sans,
              }}
            >
              <CheckCircle2 size={14} />
              All Checks
              <span
                style={{
                  background: "rgba(120,125,145,0.12)",
                  color: C.textSecondary,
                  borderRadius: 20,
                  padding: "1px 7px",
                  fontSize: 11.5,
                  fontWeight: 700,
                }}
              >
                {checks.length}
              </span>
            </button>
          </div>

          {/* Tab content */}
          {tab === "discrepancies" && (
            discrepancies.length === 0 ? (
              <div
                style={{
                  textAlign: "center",
                  padding: "36px 16px",
                  color: C.success,
                  fontSize: 14.5,
                  fontWeight: 700,
                  fontFamily: sans,
                }}
              >
                <CheckCircle2 size={32} style={{ margin: "0 auto 10px", display: "block" }} />
                No discrepancies found — bundle is clean.
              </div>
            ) : (
              <div>
                {[...discrepancies]
                  .sort((a, b) => {
                    const w: Record<Severity, number> = { critical: 4, high: 3, medium: 2, low: 1 };
                    return (w[b.severity] ?? 0) - (w[a.severity] ?? 0);
                  })
                  .map((d) => (
                    <DiscrepancyCard key={d.discrepancy_id} disc={d} />
                  ))}
              </div>
            )
          )}

          {tab === "checks" && (
            <div>
              {[
                ...checks.filter((c) => c.status === "fail"),
                ...checks.filter((c) => c.status === "warning"),
                ...checks.filter((c) => c.status === "pass"),
                ...checks.filter((c) => c.status === "not_applicable"),
              ].map((c) => (
                <CheckRow key={c.check_id} check={c} />
              ))}
            </div>
          )}

          {/* Metadata footer */}
          <div
            style={{
              marginTop: 20,
              paddingTop: 14,
              borderTop: `1px solid ${C.glassBorderSoft}`,
              display: "flex",
              justifyContent: "space-between",
              flexWrap: "wrap",
              gap: 8,
              fontFamily: sans,
            }}
          >
            <span style={{ fontSize: 12, color: C.textTertiary, display: "flex", alignItems: "center", gap: 5 }}>
              <Info size={13} /> Rules v{run.rules_version} • All checks are deterministic Python
            </span>
            <span style={{ fontSize: 12, color: C.textTertiary, fontFamily: mono }}>
              Run ID: {run.run_id.slice(0, 8)}...
            </span>
          </div>
        </>
      )}
    </div>
  );
};
