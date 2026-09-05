import React, { useState } from 'react';
import {
  CheckCircle, XCircle, AlertTriangle, MinusCircle,
  ShieldCheck, ShieldAlert, AlertOctagon, FileWarning,
  Loader2, PlayCircle, ArrowRight, Info
} from 'lucide-react';
import {
  VerificationRun, VerificationCheck, Discrepancy,
  CheckStatus, Severity, VerificationStatus
} from '../types';
import { triggerVerification, getLatestVerificationRun } from '../api/endpoints';

// ── helpers ──────────────────────────────────────────────────────────────────

const STATUS_ICON: Record<CheckStatus, React.ReactNode> = {
  pass:           <CheckCircle size={18} className="check-status-pass" />,
  fail:           <XCircle size={18} className="check-status-fail" />,
  warning:        <AlertTriangle size={18} className="check-status-warning" />,
  not_applicable: <MinusCircle size={18} className="check-status-na" />,
};

const VERDICT_ICON: Record<VerificationStatus, React.ReactNode> = {
  clean:      <ShieldCheck size={22} />,
  flagged:    <AlertTriangle size={22} />,
  critical:   <AlertOctagon size={22} />,
  incomplete: <FileWarning size={22} />,
};

const VERDICT_LABEL: Record<VerificationStatus, string> = {
  clean:      '✅ 4-Way Match PASSED — All checks clean',
  flagged:    '⚠️  Bundle Flagged — Discrepancies detected',
  critical:   '🚨 CRITICAL — Do not approve payment',
  incomplete: '❌ Incomplete — Missing documents',
};

function SeverityBadge({ severity }: { severity?: Severity }) {
  if (!severity) return null;
  return <span className={`sev-badge sev-${severity}`}>{severity}</span>;
}

function RiskGauge({ score }: { score: number }) {
  const r = 46;
  const circ = 2 * Math.PI * r;
  const filled = circ - (score / 100) * circ;
  const color = score === 0 ? '#10b981' : score < 20 ? '#f59e0b' : score < 50 ? '#f97316' : '#ef4444';

  return (
    <div className="risk-gauge-wrap">
      <div className="risk-gauge-ring">
        <svg width="120" height="120" viewBox="0 0 120 120">
          {/* track */}
          <circle cx="60" cy="60" r={r} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="10" />
          {/* fill */}
          <circle
            cx="60" cy="60" r={r} fill="none"
            stroke={color} strokeWidth="10"
            strokeDasharray={circ}
            strokeDashoffset={filled}
            strokeLinecap="round"
            style={{ transition: 'stroke-dashoffset 0.8s cubic-bezier(0.4,0,0.2,1)' }}
          />
        </svg>
        <div className="risk-gauge-label">
          <span className="risk-gauge-score" style={{ color }}>{score}</span>
          <span className="risk-gauge-sub">/ 100</span>
        </div>
      </div>
      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600 }}>Risk Score</span>
    </div>
  );
}

function CheckRow({ check }: { check: VerificationCheck }) {
  const [expanded, setExpanded] = useState(false);
  const label = check.check_type.replace(/_/g, ' ');

  return (
    <div className={`check-row ${check.status}`} onClick={() => setExpanded(!expanded)} style={{ cursor: 'pointer' }}>
      <div style={{ paddingTop: 1 }}>{STATUS_ICON[check.status]}</div>
      <div>
        <div className="check-type-label">{label}</div>
        <div className="check-explanation">{check.explanation}</div>
        {expanded && (check.expected_value || check.actual_value) && (
          <div style={{
            marginTop: 10, padding: '10px 12px',
            background: 'rgba(0,0,0,0.25)', borderRadius: 6,
            fontSize: '0.8rem', fontFamily: 'var(--font-mono)',
            display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8
          }}>
            <div><span style={{ color: 'var(--text-muted)' }}>Expected: </span>{check.expected_value ?? '—'}</div>
            <div><span style={{ color: 'var(--text-muted)' }}>Actual: </span>{check.actual_value ?? '—'}</div>
            {check.variance && (
              <div style={{ gridColumn: '1/-1' }}>
                <span style={{ color: 'var(--text-muted)' }}>Variance: </span>
                <span style={{ color: '#f87171' }}>{check.variance}</span>
              </div>
            )}
          </div>
        )}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4, paddingTop: 2 }}>
        <SeverityBadge severity={check.severity} />
        {(check.expected_value || check.actual_value) && (
          <span style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>
            {expanded ? '▲ hide' : '▼ details'}
          </span>
        )}
      </div>
    </div>
  );
}

function DiscrepancyCard({ disc }: { disc: Discrepancy }) {
  return (
    <div className={`discrepancy-card ${disc.severity}`}>
      <div className="discrepancy-header">
        <SeverityBadge severity={disc.severity} />
        <span style={{
          fontSize: '0.75rem', fontWeight: 600,
          color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em'
        }}>
          {disc.category.replace(/_/g, ' ')}
        </span>
      </div>
      <div className="discrepancy-description">{disc.description}</div>
      {disc.recommended_action && (
        <div className="discrepancy-action">
          <ArrowRight size={13} />
          {disc.recommended_action}
        </div>
      )}
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

interface VerificationPanelProps {
  bundleId: string;
  /** If the bundle already has a verified run, pass the run here for initial display */
  initialRun?: VerificationRun | null;
}

type TabKey = 'discrepancies' | 'checks';

export const VerificationPanel: React.FC<VerificationPanelProps> = ({ bundleId, initialRun }) => {
  const [run, setRun] = useState<VerificationRun | null>(initialRun ?? null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>('discrepancies');

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
      setError(err?.response?.data?.detail ?? 'Verification failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const status = run?.overall_status;
  const riskScore = run?.overall_risk_score ? parseFloat(run.overall_risk_score) : 0;
  const discrepancies = run?.discrepancies ?? [];
  const checks = run?.checks ?? [];
  const failedChecks = checks.filter(c => c.status === 'fail');
  const warnChecks = checks.filter(c => c.status === 'warning');
  const passedChecks = checks.filter(c => c.status === 'pass');

  return (
    <div className="card" style={{ marginTop: 32 }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <ShieldAlert size={22} color="var(--accent-amber)" />
          <h3 style={{ fontSize: '1.1rem', fontWeight: 700 }}>
            4-Way Match Verification
          </h3>
        </div>

        <button
          className="btn btn-verify"
          onClick={handleVerify}
          disabled={loading}
          id="verify-bundle-btn"
          style={{ display: 'flex', alignItems: 'center', gap: 8 }}
        >
          {loading
            ? <><Loader2 size={16} className="spinner" /> Running checks…</>
            : <><PlayCircle size={16} /> {run ? 'Re-Verify' : 'Run Verification'}</>
          }
        </button>
      </div>

      {/* Error state */}
      {error && (
        <div className="status-banner critical" style={{ marginBottom: 16 }}>
          <AlertOctagon size={18} /> {error}
        </div>
      )}

      {/* Not yet run */}
      {!run && !loading && (
        <div style={{
          textAlign: 'center', padding: '40px 20px',
          color: 'var(--text-muted)', fontSize: '0.9rem'
        }}>
          <ShieldCheck size={40} style={{ margin: '0 auto 12px', display: 'block', opacity: 0.3 }} />
          <div>Click <strong>Run Verification</strong> to execute all deterministic 4-way match checks.</div>
          <div style={{ fontSize: '0.8rem', marginTop: 6, color: 'var(--text-dim)' }}>
            PO ↔ Invoice ↔ GRN ↔ Bank Statement — no LLM involved
          </div>
        </div>
      )}

      {/* Loading skeleton */}
      {loading && (
        <div style={{ textAlign: 'center', padding: '40px 20px', color: 'var(--text-muted)' }}>
          <Loader2 size={36} className="spinner" style={{ margin: '0 auto 12px', display: 'block', color: 'var(--accent-amber)' }} />
          <div style={{ fontWeight: 600 }}>Running deterministic checks…</div>
          <div style={{ fontSize: '0.8rem', marginTop: 4, color: 'var(--text-dim)' }}>
            Checking amounts, dates, quantities, vendor names…
          </div>
        </div>
      )}

      {/* Results */}
      {run && !loading && (
        <>
          {/* Status banner */}
          {status && (
            <div className={`status-banner ${status}`}>
              {VERDICT_ICON[status]}
              <span>{VERDICT_LABEL[status]}</span>
            </div>
          )}

          {/* Stats row */}
          <div style={{ display: 'flex', gap: 20, alignItems: 'center', marginBottom: 24, flexWrap: 'wrap' }}>
            <RiskGauge score={riskScore} />
            <div className="verify-stats-grid" style={{ flex: 1 }}>
              <div className="verify-stat">
                <div className="verify-stat-value" style={{ color: '#f87171' }}>{failedChecks.length}</div>
                <div className="verify-stat-label">Failed</div>
              </div>
              <div className="verify-stat">
                <div className="verify-stat-value" style={{ color: '#fbbf24' }}>{warnChecks.length}</div>
                <div className="verify-stat-label">Warnings</div>
              </div>
              <div className="verify-stat">
                <div className="verify-stat-value" style={{ color: '#34d399' }}>{passedChecks.length}</div>
                <div className="verify-stat-label">Passed</div>
              </div>
              <div className="verify-stat">
                <div className="verify-stat-value" style={{ color: '#f97316' }}>{discrepancies.filter(d=>d.severity==='critical'||d.severity==='high').length}</div>
                <div className="verify-stat-label">Issues</div>
              </div>
            </div>
          </div>

          {/* Tabs */}
          <div className="verify-tabs">
            <button
              className={`verify-tab ${tab === 'discrepancies' ? 'active' : ''}`}
              onClick={() => setTab('discrepancies')}
              id="tab-discrepancies"
            >
              <AlertOctagon size={14} />
              Discrepancies
              {discrepancies.length > 0 && (
                <span style={{
                  background: discrepancies.some(d=>d.severity==='critical') ? 'rgba(239,68,68,0.2)' : 'rgba(249,115,22,0.2)',
                  color: discrepancies.some(d=>d.severity==='critical') ? '#f87171' : '#fb923c',
                  borderRadius: 9999, padding: '1px 7px', fontSize: '0.72rem', fontWeight: 700
                }}>{discrepancies.length}</span>
              )}
            </button>
            <button
              className={`verify-tab ${tab === 'checks' ? 'active' : ''}`}
              onClick={() => setTab('checks')}
              id="tab-checks"
            >
              <CheckCircle size={14} />
              All Checks
              <span style={{
                background: 'rgba(255,255,255,0.06)',
                color: 'var(--text-muted)',
                borderRadius: 9999, padding: '1px 7px', fontSize: '0.72rem', fontWeight: 700
              }}>{checks.length}</span>
            </button>
          </div>

          {/* Tab content */}
          {tab === 'discrepancies' && (
            discrepancies.length === 0
              ? (
                <div style={{
                  textAlign: 'center', padding: '32px 16px',
                  color: '#34d399', fontSize: '0.95rem', fontWeight: 600
                }}>
                  <CheckCircle size={32} style={{ margin: '0 auto 10px', display: 'block' }} />
                  No discrepancies found — bundle is clean.
                </div>
              )
              : (
                <>
                  {/* Sort: critical first */}
                  {[...discrepancies]
                    .sort((a, b) => {
                      const w: Record<Severity, number> = { critical: 4, high: 3, medium: 2, low: 1 };
                      return (w[b.severity] ?? 0) - (w[a.severity] ?? 0);
                    })
                    .map(d => <DiscrepancyCard key={d.discrepancy_id} disc={d} />)
                  }
                </>
              )
          )}

          {tab === 'checks' && (
            <>
              {/* Show failed first, then warning, then pass, then N/A */}
              {[
                ...checks.filter(c => c.status === 'fail'),
                ...checks.filter(c => c.status === 'warning'),
                ...checks.filter(c => c.status === 'pass'),
                ...checks.filter(c => c.status === 'not_applicable'),
              ].map(c => <CheckRow key={c.check_id} check={c} />)}
            </>
          )}

          {/* Metadata footer */}
          <div style={{
            marginTop: 20, paddingTop: 14, borderTop: '1px solid var(--border-color)',
            display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8
          }}>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)', display: 'flex', alignItems: 'center', gap: 5 }}>
              <Info size={12} /> Rules v{run.rules_version} · All checks are deterministic Python — no LLM
            </span>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
              Run ID: {run.run_id.slice(0, 8)}…
            </span>
          </div>
        </>
      )}
    </div>
  );
};
