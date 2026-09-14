import React, { useState } from "react";
import { FileText, CheckCircle2, AlertTriangle, ArrowRight, X, Loader2 } from "lucide-react";
import { DocType } from "../types";
import { C, sans, mono, glass, glassSoft, PrimaryButton, PageHeader } from "../theme";

interface UploadDropzoneProps {
  onUploadSubmit: (txnRef: string, files: Record<DocType, File | null>) => Promise<void>;
  isLoading: boolean;
}

export const UploadDropzone: React.FC<UploadDropzoneProps> = ({ onUploadSubmit, isLoading }) => {
  const [txnRef, setTxnRef] = useState(`TXN-2026-${Math.floor(100 + Math.random() * 900)}`);
  const [files, setFiles] = useState<Record<DocType, File | null>>({
    purchase_order: null,
    invoice: null,
    grn: null,
    bank_statement: null,
  });

  const slotConfigs: { key: DocType; label: string; hint: string }[] = [
    { key: "purchase_order", label: "Purchase order", hint: "PO PDF — PO number, vendor, subtotal" },
    { key: "invoice", label: "Invoice", hint: "Vendor invoice PDF — tax breakdown, totals" },
    { key: "grn", label: "Goods received note", hint: "GRN PDF — received quantities, pre-tax amount" },
    { key: "bank_statement", label: "Bank statement", hint: "Bank narration or payment statement PDF" },
  ];

  const handleFileChange = (docType: DocType, file: File | null) => {
    setFiles((prev) => ({ ...prev, [docType]: file }));
  };

  const handleRemove = (docType: DocType, e: React.MouseEvent) => {
    e.stopPropagation();
    setFiles((prev) => ({ ...prev, [docType]: null }));
    const inputEl = document.getElementById(`file-input-${docType}`) as HTMLInputElement;
    if (inputEl) inputEl.value = "";
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!txnRef.trim()) return;
    await onUploadSubmit(txnRef.trim(), files);
  };

  const attachedCount = Object.values(files).filter(Boolean).length;
  const ready = attachedCount === 4;

  return (
    <div>
      <PageHeader
        eyebrow="EVIDENCE INTAKE"
        title="New upload"
        description="Attach the four documents required for a deterministic 4-way audit match."
      />

      <form onSubmit={handleSubmit} style={{ ...glass({ padding: 32 }), maxWidth: 960 }}>
        {/* Transaction Reference Input */}
        <div style={{ marginBottom: 24 }}>
          <label
            style={{
              fontSize: 13,
              fontWeight: 700,
              color: C.text,
              fontFamily: sans,
              display: "block",
              marginBottom: 8,
              textTransform: "uppercase",
              letterSpacing: "0.03em",
            }}
          >
            Transaction reference
          </label>
          <input
            value={txnRef}
            onChange={(e) => setTxnRef(e.target.value)}
            placeholder="e.g. TXN-2026-817"
            required
            style={{
              width: "100%",
              maxWidth: 340,
              padding: "11px 16px",
              borderRadius: 10,
              border: `1px solid ${C.glassBorder}`,
              background: "rgba(255,255,255,0.6)",
              fontFamily: mono,
              fontSize: 14,
              fontWeight: 700,
              color: C.text,
              outline: "none",
            }}
          />
        </div>

        {/* 4-Slot Grid */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
            gap: 14,
            marginBottom: 26,
          }}
        >
          {slotConfigs.map(({ key, label, hint }) => {
            const file = files[key];
            const attached = !!file;

            return (
              <div
                key={key}
                onClick={() => {
                  const inputEl = document.getElementById(`file-input-${key}`) as HTMLInputElement;
                  if (inputEl) inputEl.click();
                }}
                style={{
                  ...glassSoft({
                    padding: "20px 16px",
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    textAlign: "center",
                    gap: 6,
                    position: "relative",
                    cursor: "pointer",
                  }),
                  background: attached ? "rgba(20,150,110,0.1)" : "rgba(255,255,255,0.35)",
                  border: `1px solid ${attached ? C.successBorder : C.glassBorderSoft}`,
                  transition: "all 0.2s ease",
                }}
              >
                <input
                  type="file"
                  id={`file-input-${key}`}
                  accept=".pdf,.txt"
                  style={{ display: "none" }}
                  onChange={(e) => {
                    if (e.target.files && e.target.files[0]) {
                      handleFileChange(key, e.target.files[0]);
                    }
                  }}
                />

                {attached && (
                  <button
                    type="button"
                    onClick={(e) => handleRemove(key, e)}
                    style={{
                      position: "absolute",
                      top: 10,
                      right: 10,
                      background: "rgba(255,255,255,0.6)",
                      border: `1px solid ${C.glassBorderSoft}`,
                      borderRadius: "50%",
                      width: 22,
                      height: 22,
                      color: C.textTertiary,
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                    }}
                    title="Remove file"
                  >
                    <X size={12} />
                  </button>
                )}

                <div
                  style={{
                    width: 42,
                    height: 42,
                    borderRadius: 12,
                    background: "rgba(255,255,255,0.85)",
                    border: `1px solid ${attached ? C.successBorder : C.glassBorder}`,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    marginBottom: 4,
                  }}
                >
                  {attached ? (
                    <CheckCircle2 size={20} color={C.success} strokeWidth={2.4} />
                  ) : (
                    <FileText size={20} color={C.accent} />
                  )}
                </div>

                <div style={{ fontSize: 14, fontWeight: 700, color: C.text, fontFamily: sans }}>
                  {label}
                </div>

                <div
                  style={{
                    fontSize: 12,
                    color: C.textTertiary,
                    fontFamily: sans,
                    lineHeight: 1.4,
                    minHeight: 34,
                  }}
                >
                  {hint}
                </div>

                {attached ? (
                  <div style={{ marginTop: 4 }}>
                    <div
                      style={{
                        fontSize: 12,
                        fontFamily: mono,
                        color: C.success,
                        fontWeight: 700,
                        maxWidth: 170,
                        textOverflow: "ellipsis",
                        overflow: "hidden",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {file.name}
                    </div>
                    <div style={{ fontSize: 11, color: C.textTertiary, fontFamily: sans, marginTop: 2 }}>
                      Ready to extract
                    </div>
                  </div>
                ) : (
                  <span
                    style={{
                      marginTop: 4,
                      fontSize: 12.5,
                      fontWeight: 700,
                      color: C.accent,
                      fontFamily: sans,
                    }}
                  >
                    Attach PDF
                  </span>
                )}
              </div>
            );
          })}
        </div>

        {/* Footer actions */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            paddingTop: 18,
            borderTop: `1px solid ${C.glassBorderSoft}`,
            flexWrap: "wrap",
            gap: 14,
          }}
        >
          {ready ? (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                fontSize: 13.5,
                color: C.success,
                fontFamily: sans,
                fontWeight: 700,
              }}
            >
              <CheckCircle2 size={16} strokeWidth={2.4} /> All four documents attached
            </div>
          ) : attachedCount > 0 ? (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                fontSize: 13,
                color: C.warning,
                fontFamily: sans,
                fontWeight: 700,
              }}
            >
              <AlertTriangle size={16} strokeWidth={2.4} /> {4 - attachedCount} document
              {4 - attachedCount > 1 ? "s" : ""} still needed for a full 4-way match
            </div>
          ) : (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                fontSize: 13,
                color: C.textTertiary,
                fontFamily: sans,
              }}
            >
              Attach documents above to begin automated extraction.
            </div>
          )}

          <PrimaryButton
            id="submit-bundle-btn"
            onClick={handleSubmit}
            disabled={isLoading || attachedCount === 0 || !txnRef.trim()}
            icon={isLoading ? undefined : ArrowRight}
          >
            {isLoading ? (
              <>
                <Loader2 size={16} className="spin" /> Processing extraction pipeline...
              </>
            ) : (
              "Create audit bundle"
            )}
          </PrimaryButton>
        </div>
      </form>
    </div>
  );
};
