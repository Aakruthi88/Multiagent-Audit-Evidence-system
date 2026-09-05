import React, { useEffect, useState } from 'react';
import { getBundles } from '../api/endpoints';
import { AuditBundle } from '../types';
import { FileText, ArrowRight, RefreshCw, Layers } from 'lucide-react';

interface DashboardProps {
  onSelectBundle: (bundleId: string) => void;
}

export const Dashboard: React.FC<DashboardProps> = ({ onSelectBundle }) => {
  const [bundles, setBundles] = useState<AuditBundle[]>([]);
  const [loading, setLoading] = useState(true);

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

  useEffect(() => {
    fetchBundles();
  }, []);

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'extracted':
        return <span className="badge badge-extracted">Extracted</span>;
      case 'extracting':
        return <span className="badge badge-extracting">Extracting</span>;
      case 'uploaded':
        return <span className="badge badge-uploaded">Uploaded</span>;
      default:
        return <span className="badge badge-uploaded">{status}</span>;
    }
  };

  return (
    <div className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, marginBottom: 4 }}>
            Audit Evidence Bundles
          </h2>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
            List of all processed transaction packages and extraction statuses.
          </p>
        </div>

        <button className="nav-btn" onClick={fetchBundles} disabled={loading}>
          <RefreshCw size={16} className={loading ? 'spin' : ''} /> Refresh
        </button>
      </div>

      {loading ? (
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
          Loading audit bundles...
        </div>
      ) : bundles.length === 0 ? (
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
          <Layers size={40} style={{ margin: '0 auto 12px auto', opacity: 0.5 }} />
          <p>No audit bundles found. Upload your first transaction pack!</p>
        </div>
      ) : (
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Transaction Reference</th>
                <th>Status</th>
                <th>Documents</th>
                <th>Created At</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {bundles.map((bundle) => (
                <tr key={bundle.bundle_id}>
                  <td style={{ fontWeight: 600, fontFamily: 'var(--font-mono)' }}>
                    {bundle.txn_reference}
                  </td>
                  <td>{getStatusBadge(bundle.status)}</td>
                  <td>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                      <FileText size={14} color="var(--primary)" /> {bundle.documents?.length || 0} Docs
                    </span>
                  </td>
                  <td style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                    {new Date(bundle.created_at).toLocaleString()}
                  </td>
                  <td>
                    <button
                      className="btn btn-primary"
                      style={{ padding: '6px 12px', fontSize: '0.8rem' }}
                      onClick={() => onSelectBundle(bundle.bundle_id)}
                    >
                      View Details <ArrowRight size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
