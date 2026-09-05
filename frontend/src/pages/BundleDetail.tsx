import React, { useEffect, useState, useCallback } from 'react';
import { getBundle, getBundleTrace, getLatestVerificationRun } from '../api/endpoints';
import { AuditBundle, AgentLog, VerificationRun } from '../types';
import { DocumentPreviewCard } from '../components/DocumentPreviewCard';
import { VerificationPanel } from '../components/VerificationPanel';
import { RefreshCw, ArrowLeft, Cpu } from 'lucide-react';

interface BundleDetailProps {
  bundleId: string;
  onBack: () => void;
}

const STATUS_CLASS: Record<string, string> = {
  uploaded: 'badge-uploaded',
  extracting: 'badge-extracting',
  extracted: 'badge-extracted',
  verifying: 'badge-extracting',
  verified: 'badge-extracted',
  flagged: 'badge-failed',
  critical: 'badge-failed',
  incomplete: 'badge-uploaded',
  reported: 'badge-extracted',
  failed: 'badge-failed',
};

export const BundleDetail: React.FC<BundleDetailProps> = ({ bundleId, onBack }) => {
  const [bundle, setBundle] = useState<AuditBundle | null>(null);
  const [logs, setLogs] = useState<AgentLog[]>([]);
  const [existingRun, setExistingRun] = useState<VerificationRun | null>(null);
  const [loading, setLoading] = useState(true);

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
        // 404 is expected when no run exists yet — ignore
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
      <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
        Loading bundle details…
      </div>
    );
  }

  if (!bundle) {
    return <div style={{ padding: 40, textAlign: 'center' }}>Bundle not found.</div>;
  }

  const extractedDocs = bundle.documents?.filter(d => d.extraction_status === 'success') ?? [];
  const canVerify = extractedDocs.length > 0;

  return (
    <div>
      {/* Back Button */}
      <button className="nav-btn" onClick={onBack} style={{ marginBottom: 16 }} id="back-to-dashboard">
        <ArrowLeft size={16} /> Back to Dashboard
      </button>

      {/* Bundle Header Card */}
      <div className="card" style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 16 }}>
          <div>
            <div style={{ fontSize: '0.8rem', color: 'var(--accent-green)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Transaction Reference
            </div>
            <h2 style={{ fontSize: '1.6rem', fontWeight: 800, fontFamily: 'var(--font-mono)', margin: '4px 0 8px 0', letterSpacing: '-0.02em' }}>
              {bundle.txn_reference}
            </h2>
            <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>
              Bundle ID: <span style={{ fontFamily: 'var(--font-mono)' }}>{bundle.bundle_id}</span>
            </div>
            <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginTop: 2 }}>
              Created: {new Date(bundle.created_at).toLocaleString()}
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 10 }}>
            <span className={`badge ${STATUS_CLASS[bundle.status] ?? 'badge-uploaded'}`} style={{ fontSize: '0.85rem' }}>
              {bundle.status.toUpperCase()}
            </span>
            <button className="nav-btn" onClick={loadData} id="sync-status-btn">
              <RefreshCw size={14} /> Sync Status
            </button>
          </div>
        </div>

        {/* Document coverage bar */}
        <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid var(--border-color)' }}>
          <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: 8, fontWeight: 600 }}>
            DOCUMENT COVERAGE — {extractedDocs.length} / {bundle.documents?.length ?? 0} extracted
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {(['purchase_order', 'invoice', 'grn', 'bank_statement'] as const).map(dt => {
              const doc = bundle.documents?.find(d => d.doc_type === dt);
              const ok = doc?.extraction_status === 'success';
              const pending = doc && doc.extraction_status !== 'success';
              return (
                <span key={dt} style={{
                  padding: '3px 10px', borderRadius: 4, fontSize: '0.72rem', fontWeight: 700,
                  textTransform: 'uppercase', letterSpacing: '0.04em',
                  background: ok ? 'rgba(16,185,129,0.12)' : pending ? 'rgba(245,158,11,0.12)' : 'rgba(255,255,255,0.04)',
                  color: ok ? '#34d399' : pending ? '#fbbf24' : '#6b7280',
                  border: `1px solid ${ok ? 'rgba(16,185,129,0.25)' : pending ? 'rgba(245,158,11,0.25)' : 'rgba(255,255,255,0.08)'}`,
                }}>
                  {ok ? '✓' : pending ? '⋯' : '—'} {dt.replace(/_/g, ' ')}
                </span>
              );
            })}
          </div>
          {!canVerify && (
            <div style={{ marginTop: 10, fontSize: '0.8rem', color: 'var(--accent-amber)' }}>
              ⚠ Upload and extract documents before running verification.
            </div>
          )}
        </div>
      </div>

      {/* Documents Section */}
      <h3 style={{ fontSize: '1.05rem', fontWeight: 700, marginBottom: 14, display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ width: 4, height: 18, background: 'var(--primary)', borderRadius: 2, display: 'inline-block' }} />
        Attached Documents ({bundle.documents?.length || 0})
      </h3>
      {bundle.documents?.map((doc) => (
        <DocumentPreviewCard key={doc.document_id} document={doc} />
      ))}

      {/* ── Verification Panel ─────────────────────────────────────────────── */}
      <VerificationPanel bundleId={bundleId} initialRun={existingRun} />

      {/* Agent Execution Trace */}
      <div className="card" style={{ marginTop: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
          <Cpu size={20} color="var(--primary)" />
          <h3 style={{ fontSize: '1.05rem', fontWeight: 700 }}>
            LangGraph Agent Trace
            <span style={{
              marginLeft: 8, fontSize: '0.75rem', fontWeight: 600,
              padding: '2px 8px', borderRadius: 9999,
              background: 'rgba(255,255,255,0.06)', color: 'var(--text-muted)'
            }}>{logs.length} entries</span>
          </h3>
        </div>

        {logs.length === 0 ? (
          <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', fontStyle: 'italic' }}>
            No execution trace entries logged yet.
          </div>
        ) : (
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>Agent</th>
                  <th>Model</th>
                  <th>Tokens</th>
                  <th>Latency</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log) => (
                  <tr key={log.log_id}>
                    <td style={{ fontWeight: 600 }}>{log.agent_name}</td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                      {log.model_used || 'N/A'}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)' }}>{log.tokens_used ?? 0}</td>
                    <td>{log.latency_ms ? `${log.latency_ms} ms` : '—'}</td>
                    <td>
                      <span className={`badge ${log.status === 'success' ? 'badge-extracted' : 'badge-failed'}`}>
                        {log.status}
                      </span>
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
