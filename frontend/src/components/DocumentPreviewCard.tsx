import React, { useState, useEffect } from 'react';
import { FileText, CheckCircle, AlertTriangle, Clock, ChevronDown, ChevronUp } from 'lucide-react';
import { DocumentItem } from '../types';
import { getDocumentDetail } from '../api/endpoints';

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
    purchase_order: 'Purchase Order (PO)',
    invoice: 'Vendor Invoice',
    grn: 'Goods Received Note (GRN)',
    bank_statement: 'Bank Statement / Narration',
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'success':
        return <span className="badge badge-extracted"><CheckCircle size={12} /> Extracted</span>;
      case 'pending':
        return <span className="badge badge-extracting"><Clock size={12} /> Extracting</span>;
      case 'failed':
        return <span className="badge badge-failed"><AlertTriangle size={12} /> Failed</span>;
      default:
        return <span className="badge badge-uploaded">{status}</span>;
    }
  };

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div className="slot-icon" style={{ margin: 0, width: 36, height: 36 }}>
            <FileText size={20} />
          </div>
          <div>
            <div style={{ fontWeight: 600, fontSize: '0.95rem' }}>
              {docTitleMap[document.doc_type] || document.doc_type}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
              Hash: {document.file_hash.substring(0, 16)}...
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {getStatusBadge(document.extraction_status)}
          <button
            onClick={() => setExpanded(!expanded)}
            className="nav-btn"
            style={{ padding: '4px 8px' }}
          >
            {expanded ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
          </button>
        </div>
      </div>

      {expanded && (
        <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid var(--border-color)' }}>
          {detail ? (
            <div>
              <h4 style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginBottom: 8 }}>
                Extracted Structured JSON ({detail.extraction_model || 'Standard Model'}):
              </h4>
              <pre
                style={{
                  background: 'rgba(0, 0, 0, 0.4)',
                  padding: 12,
                  borderRadius: 'var(--radius-sm)',
                  fontSize: '0.8rem',
                  color: '#a7f3d0',
                  overflowX: 'auto',
                  maxHeight: 240,
                }}
              >
                {JSON.stringify(detail.extracted_data || {}, null, 2)}
              </pre>

              {detail.raw_text && (
                <div style={{ marginTop: 12 }}>
                  <h4 style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginBottom: 8 }}>
                    Raw Extracted Text Snippet:
                  </h4>
                  <p
                    style={{
                      background: 'rgba(255, 255, 255, 0.02)',
                      padding: 10,
                      borderRadius: 'var(--radius-sm)',
                      fontSize: '0.8rem',
                      color: 'var(--text-muted)',
                      maxHeight: 120,
                      overflowY: 'auto',
                      whiteSpace: 'pre-wrap',
                    }}
                  >
                    {detail.raw_text.substring(0, 500)}...
                  </p>
                </div>
              )}
            </div>
          ) : (
            <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Loading extraction details...</div>
          )}
        </div>
      )}
    </div>
  );
};
