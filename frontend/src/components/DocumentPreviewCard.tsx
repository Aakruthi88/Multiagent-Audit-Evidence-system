import React, { useState, useEffect } from "react";
import { FileText, ChevronDown, ChevronUp } from "lucide-react";
import { DocumentItem } from "../types";
import { getDocumentDetail } from "../api/endpoints";
import { C, sans, mono, glassSoft, StatusBadge } from "../theme";

interface DocumentPreviewCardProps {
  document: DocumentItem;
}

export const DocumentPreviewCard: React.FC<DocumentPreviewCardProps> = ({ document }) => {
  const [detail, setDetail] = useState<DocumentItem | null>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (expanded && !detail) {
      getDocumentDetail(document.document_id)
        .then(setDetail)
        .catch(console.error);
    }
  }, [expanded, document.document_id, detail]);

  const docTitleMap: Record<string, string> = {
    purchase_order: "Purchase Order (PO)",
    invoice: "Vendor Invoice",
    grn: "Goods Received Note (GRN)",
    bank_statement: "Bank Statement / Narration",
  };

  return (
    <div
      style={{
        ...glassSoft({
          padding: "16px 20px",
          marginBottom: 14,
          background: "rgba(255,255,255,0.35)",
        }),
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <div
            style={{
              width: 38,
              height: 38,
              borderRadius: 10,
              background: "rgba(255,255,255,0.75)",
              border: `1px solid ${C.glassBorder}`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
          >
            <FileText size={18} color={C.accent} />
          </div>
          <div>
            <div style={{ fontWeight: 800, fontSize: 14.5, color: C.text, fontFamily: sans }}>
              {docTitleMap[document.doc_type] || document.doc_type}
            </div>
            <div style={{ fontSize: 12, color: C.textTertiary, fontFamily: mono, marginTop: 2 }}>
              Hash: {document.file_hash ? document.file_hash.substring(0, 20) + "..." : "—"}
            </div>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <StatusBadge status={document.extraction_status} />
          <button
            onClick={() => setExpanded(!expanded)}
            style={{
              background: "rgba(255,255,255,0.5)",
              border: `1px solid ${C.glassBorderSoft}`,
              borderRadius: 8,
              padding: "5px 8px",
              cursor: "pointer",
              color: C.textSecondary,
              display: "flex",
              alignItems: "center",
              gap: 4,
              fontSize: 12,
              fontFamily: sans,
              fontWeight: 600,
            }}
          >
            {expanded ? (
              <>
                <ChevronUp size={15} /> Hide
              </>
            ) : (
              <>
                <ChevronDown size={15} /> View data
              </>
            )}
          </button>
        </div>
      </div>

      {expanded && (
        <div style={{ marginTop: 14, paddingTop: 14, borderTop: `1px solid ${C.glassBorderSoft}` }}>
          {detail ? (
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: C.textTertiary, fontFamily: sans, textTransform: "uppercase", letterSpacing: "0.03em" }}>
                  Extracted Structured JSON ({detail.extraction_model || "Deterministic Engine"}):
                </span>
              </div>
              <pre
                style={{
                  background: "rgba(255,255,255,0.5)",
                  border: `1px solid ${C.glassBorderSoft}`,
                  padding: 14,
                  borderRadius: 10,
                  fontSize: 12,
                  fontFamily: mono,
                  color: C.text,
                  overflowX: "auto",
                  maxHeight: 260,
                  lineHeight: 1.5,
                }}
              >
                {JSON.stringify(detail.extracted_data || {}, null, 2)}
              </pre>

              {detail.raw_text && (
                <div style={{ marginTop: 12 }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: C.textTertiary, fontFamily: sans, marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.03em" }}>
                    Raw Extracted Text Snippet:
                  </div>
                  <p
                    style={{
                      background: "rgba(255, 255, 255, 0.4)",
                      border: `1px solid ${C.glassBorderSoft}`,
                      padding: 12,
                      borderRadius: 10,
                      fontSize: 12,
                      fontFamily: mono,
                      color: C.textSecondary,
                      maxHeight: 140,
                      overflowY: "auto",
                      whiteSpace: "pre-wrap",
                      margin: 0,
                    }}
                  >
                    {detail.raw_text.substring(0, 600)}...
                  </p>
                </div>
              )}
            </div>
          ) : (
            <div style={{ fontSize: 13, color: C.textTertiary, fontFamily: sans, textAlign: "center", padding: 12 }}>
              Loading extraction details...
            </div>
          )}
        </div>
      )}
    </div>
  );
};
