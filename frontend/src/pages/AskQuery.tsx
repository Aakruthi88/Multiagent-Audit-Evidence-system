import React, { useState } from "react";
import {
  Search,
  FileText,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Loader2,
  Database,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  ShieldCheck,
  DollarSign,
  Layers,
  AlertCircle,
  Sparkles,
} from "lucide-react";
import {
  C,
  sans,
  mono,
  glass,
  glassSoft,
  PageHeader,
  PrimaryButton,
  StatusBadge,
  SeverityTag,
} from "../theme";
import { apiClient } from "../api/client";

interface BundleFile {

  filename: string;
  doc_type: string;
  label: string;
  size_bytes?: number;
  url: string;
}

const formatCurrency = (val: any) => {
  if (val === undefined || val === null || val === "" || val === "N/A") return "N/A";
  const num = typeof val === "number" ? val : parseFloat(String(val).replace(/[^0-9.-]+/g, ""));
  if (isNaN(num)) return String(val);
  return `₹${num.toLocaleString("en-IN", { minimumFractionDigits: num % 1 === 0 ? 0 : 2, maximumFractionDigits: 2 })}`;
};

/**
 * Lightweight inline Markdown formatter for rendering bold, italic, code, and links cleanly.
 */
const renderInlineMarkdown = (text: string): React.ReactNode[] => {
  if (!text) return [];

  // Match inline tokens: `code`, **bold**, *italic*
  const tokenRegex = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g;
  const parts = text.split(tokenRegex);

  return parts.map((part, idx) => {
    if (part.startsWith("`") && part.endsWith("`") && part.length > 1) {
      return (
        <code
          key={idx}
          style={{
            fontFamily: mono,
            fontSize: "0.9em",
            background: "rgba(91, 99, 232, 0.09)",
            color: C.primary,
            padding: "2px 6px",
            borderRadius: 5,
            border: "1px solid rgba(91, 99, 232, 0.18)",
          }}
        >
          {part.slice(1, -1)}
        </code>
      );
    }
    if (part.startsWith("**") && part.endsWith("**") && part.length > 3) {
      return (
        <strong key={idx} style={{ fontWeight: 700, color: C.text }}>
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
      return (
        <em key={idx} style={{ fontStyle: "italic", color: C.textSecondary }}>
          {part.slice(1, -1)}
        </em>
      );
    }
    return part;
  });
};

/**
 * Pure React Markdown renderer component that cleanly parses headings, bullet lists,
 * numbered lists, and paragraphs without showing raw markdown syntax (**Vendor:**, - item).
 */
export const MarkdownContent: React.FC<{ content: string }> = ({ content }) => {
  if (!content) return null;

  // Clean out any raw boilerplate headers if present from fallback strings
  const cleanedContent = content
    .replace(/^##\s+Verification Result\s*/im, "")
    .replace(/^###\s+Summary\s*/im, "")
    .replace(/^###\s+Verification Checks[\s\S]*$/im, "") // drop raw check dumps if already in text
    .trim();

  const lines = cleanedContent.split("\n");
  const elements: React.ReactNode[] = [];
  let currentListItems: string[] = [];
  let isNumberedList = false;

  const flushList = (keyPrefix: string) => {
    if (currentListItems.length === 0) return;
    if (isNumberedList) {
      elements.push(
        <ol
          key={`${keyPrefix}-ol`}
          style={{
            margin: "8px 0 12px 20px",
            padding: 0,
            display: "flex",
            flexDirection: "column",
            gap: 6,
            fontFamily: sans,
            fontSize: 14.5,
            color: C.text,
            lineHeight: 1.6,
          }}
        >
          {currentListItems.map((item, i) => (
            <li key={i}>{renderInlineMarkdown(item)}</li>
          ))}
        </ol>
      );
    } else {
      elements.push(
        <ul
          key={`${keyPrefix}-ul`}
          style={{
            margin: "8px 0 12px 20px",
            padding: 0,
            display: "flex",
            flexDirection: "column",
            gap: 6,
            fontFamily: sans,
            fontSize: 14.5,
            color: C.text,
            lineHeight: 1.6,
            listStyleType: "disc",
          }}
        >
          {currentListItems.map((item, i) => (
            <li key={i}>{renderInlineMarkdown(item)}</li>
          ))}
        </ul>
      );
    }
    currentListItems = [];
    isNumberedList = false;
  };

  lines.forEach((line, lineIdx) => {
    const trimmed = line.trim();

    if (!trimmed) {
      flushList(`line-${lineIdx}`);
      return;
    }

    // Check for headings
    if (trimmed.startsWith("### ") || trimmed.startsWith("## ") || trimmed.startsWith("# ")) {
      flushList(`line-${lineIdx}`);
      const headingText = trimmed.replace(/^#+\s*/, "");
      elements.push(
        <div
          key={`heading-${lineIdx}`}
          style={{
            fontWeight: 700,
            fontSize: 15,
            color: C.primary,
            fontFamily: sans,
            marginTop: elements.length > 0 ? 14 : 4,
            marginBottom: 6,
          }}
        >
          {renderInlineMarkdown(headingText)}
        </div>
      );
      return;
    }

    // Check for bullet list item (- item or * item)
    if (/^[-*•]\s+/.test(trimmed)) {
      if (isNumberedList) flushList(`line-${lineIdx}`);
      currentListItems.push(trimmed.replace(/^[-*•]\s+/, ""));
      return;
    }

    // Check for numbered list item (1. item)
    if (/^\d+\.\s+/.test(trimmed)) {
      if (!isNumberedList && currentListItems.length > 0) flushList(`line-${lineIdx}`);
      isNumberedList = true;
      currentListItems.push(trimmed.replace(/^\d+\.\s+/, ""));
      return;
    }

    // Regular paragraph line
    flushList(`line-${lineIdx}`);
    elements.push(
      <p
        key={`p-${lineIdx}`}
        style={{
          margin: "6px 0",
          fontSize: 14.5,
          color: C.text,
          lineHeight: 1.65,
          fontFamily: sans,
        }}
      >
        {renderInlineMarkdown(trimmed)}
      </p>
    );
  });

  flushList("end");

  return <div>{elements}</div>;
};

/**
 * Dedicated Primary AI Answer Card
 */
export const AiAnswerCard: React.FC<{
  answer: string;
  statusColor?: string;
  statusLabel?: string;
  metadata?: {
    vendor?: string;
    invoice_number?: string;
    po_number?: string;
    grn_number?: string;
  };
}> = ({ answer, statusColor = C.accent, statusLabel, metadata }) => {
  return (
    <div
      style={{
        ...glass({ padding: 22 }),
        borderLeft: `4px solid ${statusColor}`,
        background: "rgba(255, 255, 255, 0.72)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 12,
          marginBottom: 14,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: 28,
              height: 28,
              borderRadius: 8,
              background: "rgba(91, 99, 232, 0.12)",
            }}
          >
            <Sparkles size={16} color={C.accent} />
          </div>
          <span
            style={{
              fontSize: 15,
              fontWeight: 800,
              color: C.text,
              fontFamily: sans,
              letterSpacing: "0.01em",
            }}
          >
            AI Answer
          </span>
          {statusLabel && (
            <span
              style={{
                fontSize: 12,
                fontWeight: 700,
                color: statusColor,
                background:
                  statusColor === C.success
                    ? C.successBg
                    : statusColor === C.danger
                    ? C.dangerBg
                    : C.warningBg,
                border: `1px solid ${
                  statusColor === C.success
                    ? C.successBorder
                    : statusColor === C.danger
                    ? C.dangerBorder
                    : C.warningBorder
                }`,
                padding: "2px 8px",
                borderRadius: 6,
                fontFamily: mono,
                textTransform: "uppercase",
              }}
            >
              {statusLabel}
            </span>
          )}
        </div>

        {metadata && (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", fontSize: 12, fontFamily: mono }}>
            {metadata.vendor && (
              <span
                style={{
                  background: "rgba(255,255,255,0.75)",
                  border: `1px solid ${C.glassBorderSoft}`,
                  padding: "3px 9px",
                  borderRadius: 7,
                  color: C.text,
                }}
              >
                Vendor: <strong style={{ color: C.text }}>{metadata.vendor}</strong>
              </span>
            )}
            {metadata.invoice_number && (
              <span
                style={{
                  background: "rgba(255,255,255,0.75)",
                  border: `1px solid ${C.glassBorderSoft}`,
                  padding: "3px 9px",
                  borderRadius: 7,
                  color: C.textSecondary,
                }}
              >
                Inv: <strong style={{ color: C.accent }}>{metadata.invoice_number}</strong>
              </span>
            )}
            {metadata.po_number && (
              <span
                style={{
                  background: "rgba(255,255,255,0.75)",
                  border: `1px solid ${C.glassBorderSoft}`,
                  padding: "3px 9px",
                  borderRadius: 7,
                  color: C.textSecondary,
                }}
              >
                PO: <strong style={{ color: C.primary }}>{metadata.po_number}</strong>
              </span>
            )}
            {metadata.grn_number && (
              <span
                style={{
                  background: "rgba(255,255,255,0.75)",
                  border: `1px solid ${C.glassBorderSoft}`,
                  padding: "3px 9px",
                  borderRadius: 7,
                  color: C.textSecondary,
                }}
              >
                GRN: <strong style={{ color: C.success }}>{metadata.grn_number}</strong>
              </span>
            )}
          </div>
        )}
      </div>

      <MarkdownContent content={answer} />
    </div>
  );
};

const getAuthenticatedDocUrl = (url: string): string => {
  if (!url || url === "#") return "#";
  const baseUrl = url.startsWith("http") ? url : `http://localhost:8000${url.startsWith("/") ? "" : "/"}${url}`;
  const token = localStorage.getItem("audit_auth_token");
  if (!token) return baseUrl;
  const separator = baseUrl.includes("?") ? "&" : "?";
  return `${baseUrl}${separator}token=${encodeURIComponent(token)}`;
};

const SourceDocumentsSection: React.FC<{
  files: BundleFile[];
  requiredDocuments?: string[];
  expanded: boolean;
  onToggle: () => void;
}> = ({ files, expanded, onToggle }) => {
  if (!files || files.length === 0) return null;

  const displayFiles = files;
  if (displayFiles.length === 0) return null;

  return (
    <div
      style={{
        marginTop: "0.5rem",
        marginBottom: "0.5rem",
        ...glassSoft({ padding: 0 }),
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
          padding: "12px 18px",
          background: "rgba(255, 255, 255, 0.4)",
          border: "none",
          borderBottom: expanded ? `1px solid ${C.glassBorderSoft}` : "none",
          color: C.text,
          cursor: "pointer",
          fontSize: 13.5,
          fontWeight: 700,
          fontFamily: sans,
          textAlign: "left",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {expanded ? <ChevronDown size={16} color={C.accent} /> : <ChevronRight size={16} color={C.accent} />}
          <span>Relevant Source Documents ({displayFiles.length})</span>
        </div>
        <span style={{ fontSize: 12, color: C.textTertiary }}>
          {expanded ? "Click to collapse" : "Click to view documents"}
        </span>
      </button>

      {expanded && (
        <div
          style={{
            padding: 14,
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
            gap: 10,
          }}
        >
          {displayFiles.map((file, idx) => {
            const fileUrl = getAuthenticatedDocUrl(file.url);
            return (
              <a
                key={idx}
                href={fileUrl}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "10px 14px",
                  background: "rgba(255, 255, 255, 0.55)",
                  border: `1px solid ${C.glassBorderSoft}`,
                  borderRadius: 10,
                  textDecoration: "none",
                  color: C.text,
                  transition: "all 0.15s ease",
                  cursor: "pointer",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = "rgba(91, 99, 232, 0.12)";
                  e.currentTarget.style.borderColor = C.accent;
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = "rgba(255, 255, 255, 0.55)";
                  e.currentTarget.style.borderColor = C.glassBorderSoft;
                }}
              >
                <FileText size={18} color={C.accent} style={{ flexShrink: 0 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      fontWeight: 700,
                      fontSize: 13,
                      color: C.text,
                      display: "flex",
                      alignItems: "center",
                      gap: 4,
                    }}
                  >
                    <span>{file.label}</span>
                    <ExternalLink size={12} color={C.textTertiary} />
                  </div>
                  <div
                    style={{
                      fontSize: 11.5,
                      color: C.textTertiary,
                      fontFamily: mono,
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

const VerificationResultView: React.FC<{
  summary: any;
  llmAnswer?: string;
  bundleFiles: BundleFile[];
  requiredDocuments?: string[];
  filesExpanded: boolean;
  onToggleFiles: () => void;
}> = ({ summary, llmAnswer, bundleFiles, requiredDocuments, filesExpanded, onToggleFiles }) => {
  const [checksExpanded, setChecksExpanded] = useState(false);

  const status = summary.overall_status || "VERIFIED";
  const isVerified = status === "VERIFIED" || status === "clean";
  const isFailed = status === "FAILED" || status === "critical";

  const statusColor = isVerified ? C.success : isFailed ? C.danger : C.warning;

  const fin = summary.financials || {};
  const docMatches = summary.document_matches || [];
  const findings = summary.findings || [];
  const checks = summary.formatted_checks || [];
  const primaryExplanation = llmAnswer || summary.llm_answer || summary.explanation;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      {/* 1. PRIMARY LLM AUDIT ANSWER */}
      <AiAnswerCard
        answer={primaryExplanation}
        statusColor={statusColor}
        statusLabel={status}
        metadata={{
          vendor: summary.vendor_name,
          invoice_number: summary.invoice_number,
          po_number: summary.po_number,
          grn_number: summary.grn_number,
        }}
      />

      {/* 2. SUMMARY STAT CHIPS */}
      <div>
        <div
          style={{
            fontSize: 12,
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: "0.04em",
            color: C.textTertiary,
            fontFamily: sans,
            marginBottom: 8,
          }}
        >
          Verification Summary
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 10 }}>
          <div style={{ ...glassSoft({ padding: "12px 16px" }) }}>
            <div style={{ fontSize: 11.5, color: C.textTertiary, textTransform: "uppercase", fontFamily: sans, fontWeight: 700 }}>
              Checks Passed
            </div>
            <div style={{ fontSize: 20, fontWeight: 800, color: C.success, marginTop: 2, fontFamily: sans }}>
              {summary.checks_passed ?? 0}
            </div>
          </div>
          <div style={{ ...glassSoft({ padding: "12px 16px" }) }}>
            <div style={{ fontSize: 11.5, color: C.textTertiary, textTransform: "uppercase", fontFamily: sans, fontWeight: 700 }}>
              Checks Failed
            </div>
            <div
              style={{
                fontSize: 20,
                fontWeight: 800,
                color: (summary.checks_failed ?? 0) > 0 ? C.danger : C.textTertiary,
                marginTop: 2,
                fontFamily: sans,
              }}
            >
              {summary.checks_failed ?? 0}
            </div>
          </div>
          <div style={{ ...glassSoft({ padding: "12px 16px" }) }}>
            <div style={{ fontSize: 11.5, color: C.textTertiary, textTransform: "uppercase", fontFamily: sans, fontWeight: 700 }}>
              Warnings
            </div>
            <div
              style={{
                fontSize: 20,
                fontWeight: 800,
                color: (summary.warnings_count ?? 0) > 0 ? C.warning : C.textTertiary,
                marginTop: 2,
                fontFamily: sans,
              }}
            >
              {summary.warnings_count ?? 0}
            </div>
          </div>
          <div style={{ ...glassSoft({ padding: "12px 16px" }) }}>
            <div style={{ fontSize: 11.5, color: C.textTertiary, textTransform: "uppercase", fontFamily: sans, fontWeight: 700 }}>
              Discrepancies
            </div>
            <div
              style={{
                fontSize: 20,
                fontWeight: 800,
                color: (summary.discrepancies_count ?? 0) > 0 ? C.danger : C.success,
                marginTop: 2,
                fontFamily: sans,
              }}
            >
              {summary.discrepancies_count ?? 0}
            </div>
          </div>
          <div style={{ ...glassSoft({ padding: "12px 16px" }) }}>
            <div style={{ fontSize: 11.5, color: C.textTertiary, textTransform: "uppercase", fontFamily: sans, fontWeight: 700 }}>
              Risk Score
            </div>
            <div
              style={{
                fontSize: 20,
                fontWeight: 800,
                color:
                  (summary.risk_score ?? 0) > 50
                    ? C.danger
                    : (summary.risk_score ?? 0) > 20
                    ? C.warning
                    : C.success,
                marginTop: 2,
                fontFamily: mono,
              }}
            >
              {summary.risk_score ?? 0}/100
            </div>
          </div>
        </div>
      </div>

      {/* 3. FINANCIAL SUMMARY */}
      <div style={{ ...glass({ padding: 18 }) }}>
        <div
          style={{
            fontSize: 12,
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: "0.04em",
            color: C.textTertiary,
            fontFamily: sans,
            marginBottom: 12,
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <DollarSign size={14} color={C.accent} />
          Financial Summary
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 14 }}>
          <div>
            <div style={{ fontSize: 12, color: C.textTertiary, fontFamily: sans }}>PO Total</div>
            <div style={{ fontSize: 16, fontWeight: 800, color: C.text, fontFamily: mono, marginTop: 2 }}>
              {formatCurrency(fin.po_total)}
            </div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: C.textTertiary, fontFamily: sans }}>Invoice Total</div>
            <div style={{ fontSize: 16, fontWeight: 800, color: C.warning, fontFamily: mono, marginTop: 2 }}>
              {formatCurrency(fin.invoice_total)}
            </div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: C.textTertiary, fontFamily: sans }}>GRN Value (Pre-Tax)</div>
            <div style={{ fontSize: 16, fontWeight: 800, color: C.success, fontFamily: mono, marginTop: 2 }}>
              {formatCurrency(fin.grn_total)}
            </div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: C.textTertiary, fontFamily: sans }}>Paid Amount</div>
            <div
              style={{
                fontSize: 16,
                fontWeight: 800,
                color: fin.paid_amount ? C.accent : C.textTertiary,
                fontFamily: mono,
                marginTop: 2,
              }}
            >
              {formatCurrency(fin.paid_amount)}
            </div>
          </div>
        </div>
      </div>

      {/* 4. DOCUMENT MATCH RELATIONSHIPS */}
      <div>
        <div
          style={{
            fontSize: 12,
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: "0.04em",
            color: C.textTertiary,
            fontFamily: sans,
            marginBottom: 8,
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <Layers size={14} color={C.accent} />
          Document Match Status
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 10 }}>
          {docMatches.map((dm: any, i: number) => {
            const isPass = dm.status === "pass";
            const isFail = dm.status === "fail";
            const isWarn = dm.status === "warning";
            const color = isPass ? C.success : isFail ? C.danger : isWarn ? C.warning : C.textTertiary;
            const bg = isPass ? C.successBg : isFail ? C.dangerBg : isWarn ? C.warningBg : "rgba(120,125,145,0.12)";
            const border = isPass ? C.successBorder : isFail ? C.dangerBorder : isWarn ? C.warningBorder : "rgba(120,125,145,0.22)";

            return (
              <div
                key={i}
                style={{
                  background: bg,
                  border: `1px solid ${border}`,
                  borderRadius: 8,
                  padding: "10px 14px",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 8,
                  fontFamily: sans,
                }}
              >
                <div style={{ fontWeight: 700, fontSize: 13, color: C.text }}>{dm.label}</div>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ fontSize: 11.5, fontWeight: 800, color: color, letterSpacing: "0.03em" }}>
                    {isPass ? "✓ MATCH" : isFail ? "✕ MISMATCH" : isWarn ? "⚠ VARIANCE" : "— N/A"}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* 5. FINDINGS / EXCEPTIONS */}
      <div>
        <div
          style={{
            fontSize: 12,
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: "0.04em",
            color: C.textTertiary,
            fontFamily: sans,
            marginBottom: 8,
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <AlertCircle size={14} color={findings.length > 0 ? C.danger : C.success} />
          Findings & Exceptions
        </div>
        {findings.length === 0 ? (
          <div
            style={{
              background: C.successBg,
              border: `1px solid ${C.successBorder}`,
              borderRadius: 10,
              padding: "14px 18px",
              color: C.success,
              fontSize: 13.5,
              fontFamily: sans,
              fontWeight: 600,
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            <CheckCircle2 size={18} color={C.success} />
            <span>No discrepancies or exceptions identified. All deterministic verification checks passed successfully.</span>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {findings.map((f: any, i: number) => {
              const isCrit = f.severity === "CRITICAL" || f.status === "fail";
              return (
                <div
                  key={i}
                  style={{
                    background: isCrit ? C.dangerBg : C.warningBg,
                    border: `1px solid ${isCrit ? C.dangerBorder : C.warningBorder}`,
                    borderLeft: `4px solid ${isCrit ? C.danger : C.warning}`,
                    borderRadius: 10,
                    padding: "12px 16px",
                    fontFamily: sans,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
                    <div style={{ fontWeight: 800, color: C.text, fontSize: 14 }}>{f.check_name}</div>
                    {f.severity && <SeverityTag level={f.severity} />}
                  </div>
                  <div style={{ fontSize: 13, color: C.textSecondary, lineHeight: 1.5 }}>
                    {f.explanation}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* 6. CONCLUSION */}
      <div
        style={{
          background: "rgba(91,99,232,0.08)",
          border: `1px solid rgba(91,99,232,0.22)`,
          borderLeft: `4px solid ${C.accent}`,
          borderRadius: 10,
          padding: "14px 18px",
        }}
      >
        <div
          style={{
            fontSize: 12,
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: "0.04em",
            color: C.accent,
            marginBottom: 4,
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <ShieldCheck size={14} color={C.accent} />
          Audit Conclusion
        </div>
        <div style={{ fontSize: 14, color: C.text, lineHeight: 1.6, fontFamily: sans }}>
          {summary.conclusion}
        </div>
      </div>

      {/* 7. DETAILED VERIFICATION CHECKS (Collapsible) */}
      {checks.length > 0 && (
        <div
          style={{
            ...glassSoft({ padding: 0 }),
            overflow: "hidden",
          }}
        >
          <button
            type="button"
            onClick={() => setChecksExpanded(!checksExpanded)}
            style={{
              width: "100%",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "12px 18px",
              background: "rgba(255, 255, 255, 0.4)",
              border: "none",
              borderBottom: checksExpanded ? `1px solid ${C.glassBorderSoft}` : "none",
              color: C.text,
              cursor: "pointer",
              fontSize: 13.5,
              fontWeight: 700,
              fontFamily: sans,
              textAlign: "left",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              {checksExpanded ? <ChevronDown size={16} color={C.accent} /> : <ChevronRight size={16} color={C.accent} />}
              <span>Detailed Verification Checks ({checks.length})</span>
            </div>
            <span style={{ fontSize: 12, color: C.textTertiary }}>
              {checksExpanded ? "Click to collapse" : "Click to view all checks"}
            </span>
          </button>

          {checksExpanded && (
            <div style={{ padding: 14, display: "flex", flexDirection: "column", gap: 8 }}>
              {checks.map((chk: any, idx: number) => {
                const isPass = chk.status === "pass";
                const isWarn = chk.status === "warning";
                const badgeColor = isPass ? C.success : isWarn ? C.warning : C.danger;
                const badgeBg = isPass ? C.successBg : isWarn ? C.warningBg : C.dangerBg;
                const badgeBorder = isPass ? C.successBorder : isWarn ? C.warningBorder : C.dangerBorder;

                return (
                  <div
                    key={idx}
                    style={{
                      ...glassSoft({
                        padding: "11px 16px",
                        background: "rgba(255, 255, 255, 0.45)",
                      }),
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: 14,
                      fontFamily: sans,
                    }}
                  >
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: 700, fontSize: 13.5, color: C.text }}>{chk.title}</div>
                      {chk.explanation && (
                        <div style={{ fontSize: 12.5, color: C.textSecondary, marginTop: 2 }}>
                          {chk.explanation}
                        </div>
                      )}
                    </div>
                    <div style={{ flexShrink: 0 }}>
                      <span
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 5,
                          fontSize: 11.5,
                          fontWeight: 700,
                          fontFamily: mono,
                          color: badgeColor,
                          background: badgeBg,
                          border: `1px solid ${badgeBorder}`,
                          borderRadius: 6,
                          padding: "3px 8px",
                          letterSpacing: "0.03em",
                        }}
                      >
                        {isPass ? (
                          <CheckCircle2 size={12} strokeWidth={2.4} />
                        ) : isWarn ? (
                          <AlertTriangle size={12} strokeWidth={2.4} />
                        ) : (
                          <XCircle size={12} strokeWidth={2.4} />
                        )}
                        {isPass ? "PASS" : isWarn ? "WARNING" : "FAIL"}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* 8. EVIDENCE (Source Documents) */}
      <SourceDocumentsSection
        files={bundleFiles}
        requiredDocuments={requiredDocuments}
        expanded={filesExpanded}
        onToggle={onToggleFiles}
      />
    </div>
  );
};

const AuditReportView: React.FC<{
  report: any;
  bundleFiles: BundleFile[];
  requiredDocuments?: string[];
  filesExpanded: boolean;
  onToggleFiles: () => void;
}> = ({ report, bundleFiles, requiredDocuments, filesExpanded, onToggleFiles }) => {
  const [checksExpanded, setChecksExpanded] = useState(false);

  const verdict = report.verdict || "clean";
  const isClean = verdict === "clean" || verdict === "verified";
  const isAnomaly = verdict === "anomaly" || verdict === "critical" || verdict === "flagged";
  const statusColor = isClean ? C.success : isAnomaly ? C.danger : C.warning;

  const execSummary =
    report.executive_summary ||
    report.note ||
    report.explanation ||
    report.answer ||
    "Audit report generated successfully.";

  const checks: any[] = report.verification_checks || [];
  const failedChecks: any[] =
    report.failed_checks ||
    checks.filter(
      (c) =>
        (c.status || "").toLowerCase() === "fail" ||
        (c.status || "").toLowerCase() === "warning"
    );
  const discrepancies: any[] = report.discrepancies || [];

  const passedCount =
    report.checks_passed ??
    checks.filter((c) => (c.status || "").toLowerCase() === "pass").length;
  const failedCount = checks.filter((c) => (c.status || "").toLowerCase() === "fail").length;
  const warningCount = checks.filter((c) => (c.status || "").toLowerCase() === "warning").length;
  const discCount =
    report.discrepancies_count ?? (discrepancies.length || failedCount + warningCount);
  const riskScore = report.risk_score ?? 0;

  const evidence = report.evidence || {};
  const inv = evidence.invoice || {};
  const po = evidence.purchase_order || {};
  const grn = evidence.grn || {};
  const bank = evidence.bank_statement || {};
  const vendorName = evidence.vendor || inv.vendor_name || po.vendor_name || "";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* 1. PRIMARY AI AUDIT EXPLANATION */}
      <AiAnswerCard
        answer={execSummary}
        statusColor={statusColor}
        statusLabel={verdict}
        metadata={{
          vendor: vendorName,
          invoice_number: inv.invoice_number,
          po_number: po.po_number,
          grn_number: grn.grn_number,
        }}
      />

      {/* 2. VERIFICATION OVERVIEW & AUDIT VERDICT */}
      <div>
        <div
          style={{
            fontSize: 12,
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: "0.04em",
            color: C.textTertiary,
            fontFamily: sans,
            marginBottom: 8,
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <ShieldCheck size={14} color={C.accent} />
          Verification Overview
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 10 }}>
          <div style={{ ...glassSoft({ padding: "12px 16px" }) }}>
            <div style={{ fontSize: 11.5, color: C.textTertiary, textTransform: "uppercase", fontFamily: sans, fontWeight: 700 }}>
              Audit Verdict
            </div>
            <div style={{ marginTop: 4 }}>
              <StatusBadge status={verdict} />
            </div>
          </div>
          <div style={{ ...glassSoft({ padding: "12px 16px" }) }}>
            <div style={{ fontSize: 11.5, color: C.textTertiary, textTransform: "uppercase", fontFamily: sans, fontWeight: 700 }}>
              Checks Passed
            </div>
            <div style={{ fontSize: 20, fontWeight: 800, color: C.success, marginTop: 2, fontFamily: sans }}>
              {passedCount}
            </div>
          </div>
          <div style={{ ...glassSoft({ padding: "12px 16px" }) }}>
            <div style={{ fontSize: 11.5, color: C.textTertiary, textTransform: "uppercase", fontFamily: sans, fontWeight: 700 }}>
              Checks Failed
            </div>
            <div style={{ fontSize: 20, fontWeight: 800, color: failedCount > 0 ? C.danger : C.textTertiary, marginTop: 2, fontFamily: sans }}>
              {failedCount}
            </div>
          </div>
          <div style={{ ...glassSoft({ padding: "12px 16px" }) }}>
            <div style={{ fontSize: 11.5, color: C.textTertiary, textTransform: "uppercase", fontFamily: sans, fontWeight: 700 }}>
              Warnings
            </div>
            <div style={{ fontSize: 20, fontWeight: 800, color: warningCount > 0 ? C.warning : C.textTertiary, marginTop: 2, fontFamily: sans }}>
              {warningCount}
            </div>
          </div>
          <div style={{ ...glassSoft({ padding: "12px 16px" }) }}>
            <div style={{ fontSize: 11.5, color: C.textTertiary, textTransform: "uppercase", fontFamily: sans, fontWeight: 700 }}>
              Discrepancies
            </div>
            <div style={{ fontSize: 20, fontWeight: 800, color: discCount > 0 ? C.danger : C.success, marginTop: 2, fontFamily: sans }}>
              {discCount}
            </div>
          </div>
          <div style={{ ...glassSoft({ padding: "12px 16px" }) }}>
            <div style={{ fontSize: 11.5, color: C.textTertiary, textTransform: "uppercase", fontFamily: sans, fontWeight: 700 }}>
              Risk Score
            </div>
            <div
              style={{
                fontSize: 20,
                fontWeight: 800,
                color: riskScore > 50 ? C.danger : riskScore > 20 ? C.warning : C.success,
                marginTop: 2,
                fontFamily: mono,
              }}
            >
              {riskScore}/100
            </div>
          </div>
        </div>
      </div>

      {/* 3. DISCREPANCIES / FINDINGS */}
      <div>
        <div
          style={{
            fontSize: 12,
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: "0.04em",
            color: C.textTertiary,
            fontFamily: sans,
            marginBottom: 8,
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <AlertCircle size={14} color={discrepancies.length > 0 || failedChecks.length > 0 ? C.danger : C.success} />
          Discrepancies & Exceptions
        </div>
        {discrepancies.length === 0 && failedChecks.length === 0 ? (
          <div
            style={{
              background: C.successBg,
              border: `1px solid ${C.successBorder}`,
              borderRadius: 10,
              padding: "14px 18px",
              color: C.success,
              fontSize: 13.5,
              fontFamily: sans,
              fontWeight: 600,
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            <CheckCircle2 size={18} color={C.success} />
            <span>No discrepancies identified. All deterministic verification checks passed successfully.</span>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {discrepancies.map((d: any, i: number) => {
              const isCrit =
                (d.severity || "").toLowerCase() === "critical" ||
                (d.severity || "").toLowerCase() === "high";
              return (
                <div
                  key={`disc-${i}`}
                  style={{
                    background: isCrit ? C.dangerBg : C.warningBg,
                    border: `1px solid ${isCrit ? C.dangerBorder : C.warningBorder}`,
                    borderLeft: `4px solid ${isCrit ? C.danger : C.warning}`,
                    borderRadius: 10,
                    padding: "12px 16px",
                    fontFamily: sans,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
                    <div style={{ fontWeight: 800, color: C.text, fontSize: 14 }}>
                      {d.category ? d.category.replace(/_/g, " ").toUpperCase() : "DISCREPANCY"}
                    </div>
                    {d.severity && <SeverityTag level={d.severity} />}
                  </div>
                  <div style={{ fontSize: 13, color: C.textSecondary, lineHeight: 1.5 }}>
                    {d.description}
                  </div>
                  {d.recommended_action && (
                    <div style={{ fontSize: 12.5, color: C.text, fontWeight: 600, marginTop: 6 }}>
                      Action: {d.recommended_action}
                    </div>
                  )}
                </div>
              );
            })}

            {failedChecks.map((f: any, i: number) => {
              const title = f.check_type || f.check_name || "Verification Check";
              const isCrit =
                (f.severity || "").toLowerCase() === "critical" ||
                (f.status || "").toLowerCase() === "fail";
              return (
                <div
                  key={`fail-${i}`}
                  style={{
                    background: isCrit ? C.dangerBg : C.warningBg,
                    border: `1px solid ${isCrit ? C.dangerBorder : C.warningBorder}`,
                    borderLeft: `4px solid ${isCrit ? C.danger : C.warning}`,
                    borderRadius: 10,
                    padding: "12px 16px",
                    fontFamily: sans,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
                    <div style={{ fontWeight: 800, color: C.text, fontSize: 14 }}>{title}</div>
                    {f.severity && <SeverityTag level={f.severity} />}
                  </div>
                  <div style={{ fontSize: 13, color: C.textSecondary, lineHeight: 1.5 }}>
                    {f.explanation || `Check evaluated with status: ${f.status}`}
                  </div>
                  {(f.expected || f.actual) && (
                    <div style={{ fontSize: 12, fontFamily: mono, color: C.textTertiary, marginTop: 4 }}>
                      Expected: {f.expected} | Actual: {f.actual} {f.variance ? `| Variance: ${f.variance}` : ""}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* 4. DETAILED VERIFICATION CHECKS (Collapsible) */}
      {checks.length > 0 && (
        <div style={{ ...glassSoft({ padding: 0 }), overflow: "hidden" }}>
          <button
            type="button"
            onClick={() => setChecksExpanded(!checksExpanded)}
            style={{
              width: "100%",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "12px 18px",
              background: "rgba(255, 255, 255, 0.4)",
              border: "none",
              borderBottom: checksExpanded ? `1px solid ${C.glassBorderSoft}` : "none",
              color: C.text,
              cursor: "pointer",
              fontSize: 13.5,
              fontWeight: 700,
              fontFamily: sans,
              textAlign: "left",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              {checksExpanded ? <ChevronDown size={16} color={C.accent} /> : <ChevronRight size={16} color={C.accent} />}
              <span>Detailed Verification Checks ({checks.length})</span>
            </div>
            <span style={{ fontSize: 12, color: C.textTertiary }}>
              {checksExpanded ? "Click to collapse" : "Click to view all checks"}
            </span>
          </button>

          {checksExpanded && (
            <div style={{ padding: 14, display: "flex", flexDirection: "column", gap: 8 }}>
              {checks.map((chk: any, idx: number) => {
                const isPass = (chk.status || "").toLowerCase() === "pass";
                const isWarn = (chk.status || "").toLowerCase() === "warning";
                const badgeColor = isPass ? C.success : isWarn ? C.warning : C.danger;
                const badgeBg = isPass ? C.successBg : isWarn ? C.warningBg : C.dangerBg;
                const badgeBorder = isPass ? C.successBorder : isWarn ? C.warningBorder : C.dangerBorder;
                const title = chk.check_name || chk.check_type || `Check ${idx + 1}`;

                return (
                  <div
                    key={idx}
                    style={{
                      ...glassSoft({
                        padding: "11px 16px",
                        background: "rgba(255, 255, 255, 0.45)",
                      }),
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: 14,
                      fontFamily: sans,
                    }}
                  >
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: 700, fontSize: 13.5, color: C.text }}>{title}</div>
                      {chk.explanation && (
                        <div style={{ fontSize: 12.5, color: C.textSecondary, marginTop: 2 }}>
                          {chk.explanation}
                        </div>
                      )}
                    </div>
                    <div style={{ flexShrink: 0 }}>
                      <span
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 5,
                          fontSize: 11.5,
                          fontWeight: 700,
                          fontFamily: mono,
                          color: badgeColor,
                          background: badgeBg,
                          border: `1px solid ${badgeBorder}`,
                          borderRadius: 6,
                          padding: "3px 8px",
                          letterSpacing: "0.03em",
                        }}
                      >
                        {isPass ? (
                          <CheckCircle2 size={12} strokeWidth={2.4} />
                        ) : isWarn ? (
                          <AlertTriangle size={12} strokeWidth={2.4} />
                        ) : (
                          <XCircle size={12} strokeWidth={2.4} />
                        )}
                        {isPass ? "PASS" : isWarn ? "WARNING" : "FAIL"}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* 5. SOURCE EVIDENCE */}
      {(inv.invoice_number ||
        po.po_number ||
        grn.grn_number ||
        bank.payment_status ||
        (bundleFiles && bundleFiles.length > 0)) && (
        <div>
          <div
            style={{
              fontSize: 12,
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "0.04em",
              color: C.textTertiary,
              fontFamily: sans,
              marginBottom: 8,
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            <FileText size={14} color={C.accent} />
            Source Evidence Documents
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 10 }}>
            {inv.invoice_number && (
              <div style={{ ...glassSoft({ padding: 14 }) }}>
                <div style={{ fontWeight: 700, fontSize: 13.5, color: C.text, display: "flex", alignItems: "center", gap: 6 }}>
                  <FileText size={15} color={C.accent} />
                  <span>Invoice {inv.invoice_number}</span>
                </div>
                <div style={{ fontSize: 12, color: C.textSecondary, marginTop: 4 }}>
                  Amount: <strong>{formatCurrency(inv.total_amount)}</strong>
                </div>
                {inv.invoice_date && (
                  <div style={{ fontSize: 11.5, color: C.textTertiary, marginTop: 2 }}>
                    Date: {inv.invoice_date}
                  </div>
                )}
              </div>
            )}
            {po.po_number && (
              <div style={{ ...glassSoft({ padding: 14 }) }}>
                <div style={{ fontWeight: 700, fontSize: 13.5, color: C.primary, display: "flex", alignItems: "center", gap: 6 }}>
                  <FileText size={15} color={C.primary} />
                  <span>Purchase Order {po.po_number}</span>
                </div>
                <div style={{ fontSize: 12, color: C.textSecondary, marginTop: 4 }}>
                  Total: <strong>{formatCurrency(po.total_amount)}</strong>
                </div>
                {po.po_date && (
                  <div style={{ fontSize: 11.5, color: C.textTertiary, marginTop: 2 }}>
                    Date: {po.po_date}
                  </div>
                )}
              </div>
            )}
            {grn.grn_number && (
              <div style={{ ...glassSoft({ padding: 14 }) }}>
                <div style={{ fontWeight: 700, fontSize: 13.5, color: C.success, display: "flex", alignItems: "center", gap: 6 }}>
                  <FileText size={15} color={C.success} />
                  <span>GRN {grn.grn_number}</span>
                </div>
                <div style={{ fontSize: 12, color: C.textSecondary, marginTop: 4 }}>
                  Date: {grn.grn_date || "Recorded"}
                </div>
              </div>
            )}
            {bank.payment_status && (
              <div style={{ ...glassSoft({ padding: 14 }) }}>
                <div style={{ fontWeight: 700, fontSize: 13.5, color: C.text, display: "flex", alignItems: "center", gap: 6 }}>
                  <DollarSign size={15} color={C.accent} />
                  <span>Bank Statement</span>
                </div>
                <div style={{ fontSize: 12, color: C.textSecondary, marginTop: 4 }}>
                  Status: <strong>{bank.payment_status}</strong>
                </div>
                {bank.payment_amount && (
                  <div style={{ fontSize: 12, color: C.textSecondary, marginTop: 2 }}>
                    Paid: <strong>{formatCurrency(bank.payment_amount)}</strong>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* 6. BUNDLE FILES */}
      <SourceDocumentsSection
        files={bundleFiles}
        requiredDocuments={requiredDocuments}
        expanded={filesExpanded}
        onToggle={onToggleFiles}
      />
    </div>
  );
};

export const AskQuery: React.FC = () => {
  const [query, setQuery] = useState("");
  const [bundleId, setBundleId] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [bundleFiles, setBundleFiles] = useState<BundleFile[]>([]);
  const [filesExpanded, setFilesExpanded] = useState<boolean>(false);

  const askExamples = [
    "Verify invoice 200005 against PO 100005 and GRN-2026-0005",
    "Why was TXN-2026-817 flagged?",
    "What is the total of Invoice 200005?",
    "Does the invoice match the GRN?",
    "Was the invoice fully paid?",
    "Show me all amount mismatches",
    "Generate an audit report for invoice 200005",
  ];

  const handleQuery = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setResult(null);
    setError(null);
    setBundleFiles([]);
    try {
      const payload: any = { query: query.trim() };
      if (bundleId.trim()) payload.bundle_id = bundleId.trim();
      
      const res = await apiClient.post("/run", payload);
      const data = res.data;
      setResult(data);

      const backendSourceDocs =
        data?.report?.source_documents ||
        data?.report?.verification_summary?.source_documents ||
        data?.source_documents;

      const activeBundleId =
        data?.report?.verification_summary?.bundle_id ||
        data?.report?.bundle_id ||
        data?.bundle_id;

      if (Array.isArray(backendSourceDocs) && backendSourceDocs.length > 0) {
        const formattedDocs = backendSourceDocs.map((doc: any) => ({
          filename: doc.filename || `${doc.doc_type || doc.type || "document"}.pdf`,
          doc_type: doc.doc_type || doc.type || "unknown",
          label: doc.label || doc.filename || "Document",
          url: doc.url
            ? (doc.url.startsWith("http") ? doc.url : `http://localhost:8000${doc.url.startsWith("/") ? "" : "/"}${doc.url}`)
            : (activeBundleId ? `http://localhost:8000/api/v1/bundles/${activeBundleId}/files/${doc.filename}` : "#"),
        }));
        setBundleFiles(formattedDocs);
      } else if (activeBundleId) {
        try {
          const filesRes = await apiClient.get(`/bundles/${activeBundleId}/files`);
          setBundleFiles(filesRes.data.files || []);
        } catch {
          setBundleFiles([]);
        }
      } else {
        setBundleFiles([]);
      }

      setFilesExpanded(false);
    } catch (err: any) {
      const detail = err.response?.data?.detail || err.message || "Unknown error occurred";
      setError(detail);
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

  const verifSummary = result?.report?.verification_summary;
  const isVerificationResponse = Boolean(
    verifSummary &&
      (result?.report?.query_type === "comparison" ||
        result?.report?.query_type === "verification" ||
        result?.report?.query_type === "full_audit" ||
        result?.report?.answer_type === "comparison" ||
        result?.report?.answer_type === "verification" ||
        result?.action === "reverify" ||
        result?.retrieval_plan?.verification_required === true ||
        result?.report?.retrieval_plan?.verification_required === true)
  );

  const isAuditReport = Boolean(
    result?.report &&
      (result?.report?.report_type === "detailed" ||
        result?.report?.report_type === "summary" ||
        result?.report?.report_type === "full_audit" ||
        result?.retrieval_plan?.report_required === true ||
        result?.report?.retrieval_plan?.report_required === true) &&
      !isVerificationResponse
  );

  const FIELD_LOOKUP_TYPES = new Set(["field_lookup", "lookup", "payment_lookup"]);
  const isFieldLookup = Boolean(
    !isVerificationResponse &&
      !isAuditReport &&
      (FIELD_LOOKUP_TYPES.has(result?.report?.query_type) ||
        FIELD_LOOKUP_TYPES.has(result?.report?.answer_type) ||
        FIELD_LOOKUP_TYPES.has(result?.action) ||
        FIELD_LOOKUP_TYPES.has(result?.retrieval_plan?.intent) ||
        result?.retrieval_plan?.verification_required === false ||
        result?.report?.retrieval_plan?.verification_required === false ||
        (result?.report?.answer && !result?.report?.bundles && result?.report?.query_type !== "status_query"))
  );

  const bundles: any[] = result?.report?.bundles ?? [];
  const isStatusQuery =
    !isVerificationResponse &&
    !isAuditReport &&
    (result?.report?.query_type === "status_query" ||
      result?.action === "status_query" ||
      bundles.length > 0);

  const requiredDocuments: string[] | undefined =
    result?.required_documents ||
    result?.retrieval_plan?.required_documents ||
    result?.report?.required_documents;

  // Extract primary answer for universal fallback display
  const primaryAiAnswer =
    result?.report?.answer ||
    result?.answer ||
    result?.report?.executive_summary ||
    result?.report?.note ||
    verifSummary?.llm_answer ||
    verifSummary?.explanation ||
    result?.report?.message ||
    "Query processed successfully.";

  const lookupResult = result?.report?.result;

  return (
    <div>
      <PageHeader
        eyebrow="AUDIT INTELLIGENCE"
        title="Ask documents"
        description="Ask questions about your evidence bundles and get answers grounded in extracted, verified data."
      />

      {/* Query Input Card */}
      <div style={{ ...glass({ padding: 24 }), marginBottom: 24 }}>
        <textarea
          id="query-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="e.g. 'Why was TXN-2026-817 flagged?' or 'Verify invoice 200005 against PO 100005'"
          rows={2}
          style={{
            width: "100%",
            border: `1px solid ${C.glassBorder}`,
            background: "rgba(255,255,255,0.6)",
            borderRadius: 12,
            padding: "12px 16px",
            fontSize: 14,
            fontFamily: sans,
            color: C.text,
            resize: "vertical",
            outline: "none",
          }}
        />

        {/* Quick Example Chips */}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "14px 0" }}>
          {askExamples.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => setQuery(ex)}
              style={{
                fontSize: 12.5,
                color: C.textSecondary,
                background: "rgba(255,255,255,0.5)",
                border: `1px solid ${C.glassBorderSoft}`,
                borderRadius: 8,
                padding: "6px 12px",
                fontFamily: sans,
                cursor: "pointer",
                transition: "all 0.15s ease",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = "rgba(91,99,232,0.12)";
                e.currentTarget.style.color = C.primary;
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = "rgba(255,255,255,0.5)";
                e.currentTarget.style.color = C.textSecondary;
              }}
            >
              {ex}
            </button>
          ))}
        </div>

        {/* Action Row */}
        <div style={{ display: "flex", gap: 10, alignItems: "center", justifyContent: "space-between", flexWrap: "wrap" }}>
          <input
            id="bundle-id-input"
            value={bundleId}
            onChange={(e) => setBundleId(e.target.value)}
            placeholder="Bundle ID (optional)"
            style={{
              background: "rgba(255,255,255,0.6)",
              border: `1px solid ${C.glassBorder}`,
              borderRadius: 10,
              padding: "10px 14px",
              color: C.text,
              fontFamily: mono,
              fontSize: 13,
              outline: "none",
              width: "100%",
              maxWidth: 320,
            }}
          />

          <PrimaryButton
            id="run-query-btn"
            onClick={handleQuery}
            disabled={loading || !query.trim()}
            icon={loading ? undefined : Search}
          >
            {loading ? (
              <>
                <Loader2 size={16} className="spin" /> Running...
              </>
            ) : (
              "Run query"
            )}
          </PrimaryButton>
        </div>
      </div>

      {/* Loading Banner */}
      {loading && (
        <div
          style={{
            ...glass({ padding: 36 }),
            textAlign: "center",
            color: C.accent,
            fontFamily: sans,
            marginBottom: 20,
          }}
        >
          <Loader2 size={32} className="spin" style={{ margin: "0 auto 12px", display: "block" }} />
          <div style={{ fontSize: 16, fontWeight: 700, color: C.text }}>Running agent pipeline...</div>
          <div style={{ fontSize: 13, color: C.textTertiary, marginTop: 4 }}>
            Routing query, analyzing documents, and verifying evidence...
          </div>
        </div>
      )}

      {/* Error Banner */}
      {!loading && error && (
        <div
          style={{
            ...glass({
              background: C.dangerBg,
              borderColor: C.dangerBorder,
              padding: 20,
              color: C.danger,
              marginBottom: 20,
            }),
            display: "flex",
            gap: 12,
            alignItems: "flex-start",
            fontFamily: sans,
          }}
        >
          <AlertTriangle size={20} color={C.danger} style={{ flexShrink: 0, marginTop: 2 }} />
          <div>
            <div style={{ fontWeight: 800, fontSize: 14.5, marginBottom: 4 }}>Query Failed</div>
            <div style={{ fontSize: 13.5 }}>{error}</div>
          </div>
        </div>
      )}

      {/* Result Container */}
      {!loading && result && (
        <div style={glass({ padding: 24 })}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              marginBottom: 20,
              paddingBottom: 14,
              borderBottom: `1px solid ${C.glassBorderSoft}`,
              flexWrap: "wrap",
            }}
          >
            {isFieldLookup ? (
              <CheckCircle2 size={20} color={C.success} />
            ) : isStatusQuery ? (
              <Database size={20} color={C.accent} />
            ) : (
              <Sparkles size={20} color={C.accent} />
            )}
            <span style={{ fontWeight: 800, fontSize: 16, color: C.text, fontFamily: sans }}>
              {isVerificationResponse
                ? "Audit Verification Result"
                : isAuditReport
                ? "Audit Report"
                : isFieldLookup
                ? "Audit Verification Result"
                : isStatusQuery
                ? "System Status & Bundle Search Results"
                : "Audit Intelligence Response"}
            </span>
            {(result?.report?.query_type || result?.report?.report_type || result.action) && (
              <span
                style={{
                  marginLeft: "auto",
                  fontSize: 11.5,
                  background: "rgba(91,99,232,0.14)",
                  color: C.primary,
                  border: `1px solid rgba(91,99,232,0.25)`,
                  padding: "3px 10px",
                  borderRadius: 20,
                  fontFamily: mono,
                  fontWeight: 700,
                }}
              >
                {result?.report?.report_type || result?.report?.query_type || result.action}
              </span>
            )}
          </div>

          {/* 1. Structured Verification Result */}
          {isVerificationResponse ? (
            <VerificationResultView
              summary={verifSummary}
              llmAnswer={primaryAiAnswer}
              bundleFiles={bundleFiles}
              requiredDocuments={requiredDocuments}
              filesExpanded={filesExpanded}
              onToggleFiles={() => setFilesExpanded(!filesExpanded)}
            />
          ) : isAuditReport ? (
            /* 2. Structured Audit Report */
            <AuditReportView
              report={result.report}
              bundleFiles={bundleFiles}
              requiredDocuments={requiredDocuments}
              filesExpanded={filesExpanded}
              onToggleFiles={() => setFilesExpanded(!filesExpanded)}
            />
          ) : isFieldLookup ? (
            /* 3. Simple Field Lookup QA View with primary AI Answer */
            <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
              <AiAnswerCard
                answer={primaryAiAnswer}
                statusColor={lookupResult?.found !== false ? C.success : C.danger}
                statusLabel={lookupResult?.status || (lookupResult?.found !== false ? "VERIFIED" : "NOT FOUND")}
                metadata={
                  lookupResult
                    ? {
                        vendor: lookupResult.vendor_name,
                        invoice_number: lookupResult.invoice_number,
                        po_number: lookupResult.po_number,
                        grn_number: lookupResult.grn_number,
                      }
                    : undefined
                }
              />

              {lookupResult && lookupResult.found && !lookupResult.ambiguous && (
                <div>
                  <div
                    style={{
                      fontSize: 12,
                      fontWeight: 700,
                      textTransform: "uppercase",
                      letterSpacing: "0.04em",
                      color: C.textTertiary,
                      fontFamily: sans,
                      marginBottom: 8,
                    }}
                  >
                    Extracted Record Details
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(160px,1fr))", gap: 10 }}>
                    {lookupResult.vendor_name && (
                      <div style={{ ...glassSoft({ padding: 12 }) }}>
                        <div style={{ fontSize: 11.5, color: C.textTertiary, textTransform: "uppercase", marginBottom: 2 }}>
                          Vendor
                        </div>
                        <div style={{ fontWeight: 800, color: C.text, fontSize: 14 }}>
                          {lookupResult.vendor_name}
                        </div>
                      </div>
                    )}
                    {lookupResult.invoice_number && (
                      <div style={{ ...glassSoft({ padding: 12 }) }}>
                        <div style={{ fontSize: 11.5, color: C.textTertiary, textTransform: "uppercase", marginBottom: 2 }}>
                          Invoice #
                        </div>
                        <div style={{ fontWeight: 800, color: C.accent, fontFamily: mono, fontSize: 14 }}>
                          {lookupResult.invoice_number}
                        </div>
                      </div>
                    )}
                    {lookupResult.total_amount !== undefined && lookupResult.total_amount !== null && (
                      <div style={{ ...glassSoft({ padding: 12 }) }}>
                        <div style={{ fontSize: 11.5, color: C.textTertiary, textTransform: "uppercase", marginBottom: 2 }}>
                          Total Amount
                        </div>
                        <div style={{ fontWeight: 800, color: C.success, fontFamily: mono, fontSize: 15 }}>
                          {formatCurrency(lookupResult.total_amount)}
                        </div>
                      </div>
                    )}
                    {lookupResult.po_number && (
                      <div style={{ ...glassSoft({ padding: 12 }) }}>
                        <div style={{ fontSize: 11.5, color: C.textTertiary, textTransform: "uppercase", marginBottom: 2 }}>
                          PO #
                        </div>
                        <div style={{ fontWeight: 800, color: C.primary, fontFamily: mono, fontSize: 14 }}>
                          {lookupResult.po_number}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}

              <SourceDocumentsSection
                files={bundleFiles}
                requiredDocuments={requiredDocuments}
                expanded={filesExpanded}
                onToggle={() => setFilesExpanded(!filesExpanded)}
              />
            </div>
          ) : isStatusQuery && bundles.length > 0 ? (
            /* 4. Bundle Table View with leading AI Answer */
            <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
              <AiAnswerCard
                answer={primaryAiAnswer}
                statusColor={C.accent}
                statusLabel="Status Query"
              />

              <div style={{ ...glassSoft({ padding: 0 }), overflow: "hidden" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: sans }}>
                  <thead>
                    <tr>
                      <th
                        style={{
                          textAlign: "left",
                          fontSize: 12,
                          color: C.textTertiary,
                          fontWeight: 700,
                          padding: "10px 18px",
                          borderBottom: `1px solid ${C.glassBorderSoft}`,
                        }}
                      >
                        Transaction Ref
                      </th>
                      <th
                        style={{
                          textAlign: "left",
                          fontSize: 12,
                          color: C.textTertiary,
                          fontWeight: 700,
                          padding: "10px 18px",
                          borderBottom: `1px solid ${C.glassBorderSoft}`,
                        }}
                      >
                        Status
                      </th>
                      <th
                        style={{
                          textAlign: "left",
                          fontSize: 12,
                          color: C.textTertiary,
                          fontWeight: 700,
                          padding: "10px 18px",
                          borderBottom: `1px solid ${C.glassBorderSoft}`,
                        }}
                      >
                        Risk Score
                      </th>
                      <th
                        style={{
                          textAlign: "left",
                          fontSize: 12,
                          color: C.textTertiary,
                          fontWeight: 700,
                          padding: "10px 18px",
                          borderBottom: `1px solid ${C.glassBorderSoft}`,
                        }}
                      >
                        Failed Checks
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {bundles.map((b: any) => (
                      <tr key={b.bundle_id}>
                        <td
                          style={{
                            padding: "12px 18px",
                            borderBottom: `1px solid ${C.glassBorderSoft}`,
                            fontFamily: mono,
                            fontWeight: 700,
                            color: C.text,
                          }}
                        >
                          {b.txn_reference || b.bundle_id?.slice(0, 8) + "..."}
                        </td>
                        <td style={{ padding: "12px 18px", borderBottom: `1px solid ${C.glassBorderSoft}` }}>
                          <StatusBadge status={b.overall_status || b.status || "unknown"} />
                        </td>
                        <td
                          style={{
                            padding: "12px 18px",
                            borderBottom: `1px solid ${C.glassBorderSoft}`,
                            fontFamily: mono,
                            fontWeight: 700,
                            color:
                              (b.risk_score || 0) < 30
                                ? C.success
                                : (b.risk_score || 0) < 60
                                ? C.warning
                                : C.danger,
                          }}
                        >
                          {b.risk_score ?? "—"}
                        </td>
                        <td
                          style={{
                            padding: "12px 18px",
                            borderBottom: `1px solid ${C.glassBorderSoft}`,
                            fontSize: 12.5,
                            color: C.textSecondary,
                          }}
                        >
                          {b.failed_checks?.length > 0 ? b.failed_checks.join(", ") : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            /* 5. Fallback Response View with primary AI Answer */
            <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
              <AiAnswerCard
                answer={primaryAiAnswer}
                statusColor={C.accent}
              />

              <SourceDocumentsSection
                files={bundleFiles}
                requiredDocuments={requiredDocuments}
                expanded={filesExpanded}
                onToggle={() => setFilesExpanded(!filesExpanded)}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
};
