import React, { useState } from 'react';
import { FileText, CheckCircle2, AlertCircle, ArrowRight } from 'lucide-react';
import { DocType } from '../types';

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

  const slotConfigs: { key: DocType; title: string; subtitle: string }[] = [
    { key: 'purchase_order', title: 'Purchase Order', subtitle: 'PO PDF file (po_number, vendor, subtotal)' },
    { key: 'invoice', title: 'Invoice', subtitle: 'Vendor Invoice PDF (tax breakdown, totals)' },
    { key: 'grn', title: 'Goods Received Note', subtitle: 'GRN PDF (received quantities & pre-tax amount)' },
    { key: 'bank_statement', title: 'Bank Statement', subtitle: 'Bank Narration / Payment statement PDF' },
  ];

  const handleFileChange = (docType: DocType, file: File | null) => {
    setFiles((prev) => ({ ...prev, [docType]: file }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!txnRef.trim()) return;
    await onUploadSubmit(txnRef.trim(), files);
  };

  const selectedCount = Object.values(files).filter(Boolean).length;

  return (
    <form onSubmit={handleSubmit} className="card">
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ fontSize: '1.25rem', fontWeight: 700, marginBottom: 6 }}>
          Upload Audit Evidence Bundle
        </h2>
        <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
          Select transaction files for automatic multi-document extraction & state initialization.
        </p>
      </div>

      <div className="input-group">
        <label className="input-label">Transaction Reference Key</label>
        <input
          type="text"
          className="input-field"
          value={txnRef}
          onChange={(e) => setTxnRef(e.target.value)}
          placeholder="e.g. TXN-2026-001"
          required
        />
      </div>

      <div className="dropzone-grid">
        {slotConfigs.map(({ key, title, subtitle }) => {
          const selectedFile = files[key];
          return (
            <div
              key={key}
              className={`dropzone-slot ${selectedFile ? 'has-file' : ''}`}
              onClick={() => {
                const inputEl = document.getElementById(`file-input-${key}`) as HTMLInputElement;
                if (inputEl) inputEl.click();
              }}
            >
              <input
                type="file"
                id={`file-input-${key}`}
                accept=".pdf,.txt"
                style={{ display: 'none' }}
                onChange={(e) => {
                  if (e.target.files && e.target.files[0]) {
                    handleFileChange(key, e.target.files[0]);
                  }
                }}
              />
              <div className="slot-icon">
                {selectedFile ? <CheckCircle2 size={24} color="var(--accent-green)" /> : <FileText size={24} />}
              </div>
              <div className="slot-title">{title}</div>
              <div className="slot-desc">{subtitle}</div>

              {selectedFile ? (
                <div className="slot-file-info">
                  <FileText size={14} />
                  <span style={{ textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap', maxWidth: '180px' }}>
                    {selectedFile.name}
                  </span>
                </div>
              ) : (
                <div style={{ marginTop: 12, fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                  Click to attach PDF
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 24, paddingTop: 16, borderTop: '1px solid var(--border-color)' }}>
        <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
          {selectedCount > 0 ? (
            <span style={{ color: 'var(--accent-green)', fontWeight: 600 }}>
              ✓ {selectedCount} of 4 documents attached
            </span>
          ) : (
            <span style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--accent-amber)' }}>
              <AlertCircle size={16} /> Attach at least 1 document to process bundle
            </span>
          )}
        </div>

        <button
          type="submit"
          className="btn btn-primary"
          disabled={isLoading || selectedCount === 0 || !txnRef.trim()}
        >
          {isLoading ? (
            <>Processing Extraction Pipeline...</>
          ) : (
            <>
              Submit Bundle & Extract <ArrowRight size={18} />
            </>
          )}
        </button>
      </div>
    </form>
  );
};
