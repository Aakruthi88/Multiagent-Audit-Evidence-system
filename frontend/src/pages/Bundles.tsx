import React, { useEffect, useState } from "react";
import { getBundles } from "../api/endpoints";
import { AuditBundle } from "../types";
import {
  FileText,
  ArrowRight,
  RefreshCw,
  Plus,
  Loader,
  Layers3,
} from "lucide-react";
import {
  C,
  sans,
  mono,
  glass,
  PageHeader,
  PrimaryButton,
  SecondaryButton,
  StatusBadge,
} from "../theme";

interface BundlesProps {
  onSelectBundle: (bundleId: string) => void;
  onNewUpload?: () => void;
}

export const Bundles: React.FC<BundlesProps> = ({ onSelectBundle, onNewUpload }) => {
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

  return (
    <div>
      <PageHeader
        eyebrow="EVIDENCE PACKAGES"
        title="Bundles"
        description="All processed transaction packages and their verification status."
        action={
          onNewUpload && (
            <PrimaryButton icon={Plus} onClick={onNewUpload} id="bundles-new-upload-btn">
              New upload
            </PrimaryButton>
          )
        }
      />

      <div style={glass({ padding: 0, overflow: "hidden" })}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "18px 24px",
            borderBottom: `1px solid ${C.glassBorderSoft}`,
          }}
        >
          <div style={{ fontSize: 16, fontWeight: 800, color: C.text, fontFamily: sans }}>
            All Evidence Packages ({bundles.length})
          </div>
          <SecondaryButton onClick={fetchBundles} disabled={loading} icon={RefreshCw} id="refresh-all-bundles-btn">
            Refresh
          </SecondaryButton>
        </div>

        {loading ? (
          <div style={{ padding: 48, textAlign: "center", color: C.textSecondary, fontFamily: sans }}>
            <Loader size={24} className="spin" style={{ margin: "0 auto 10px", display: "block", color: C.accent }} />
            Loading audit bundles...
          </div>
        ) : bundles.length === 0 ? (
          <div style={{ padding: 48, textAlign: "center", color: C.textSecondary, fontFamily: sans }}>
            <Layers3 size={40} style={{ margin: "0 auto 12px", opacity: 0.4, color: C.textTertiary }} />
            <p style={{ margin: 0, fontSize: 14.5, fontWeight: 600 }}>No audit bundles found.</p>
            <p style={{ margin: "4px 0 16px", fontSize: 13, color: C.textTertiary }}>
              Upload your first 4-way transaction package to start.
            </p>
            {onNewUpload && (
              <PrimaryButton icon={Plus} onClick={onNewUpload}>
                New upload
              </PrimaryButton>
            )}
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: sans }}>
            <thead>
              <tr>
                {["Transaction reference", "Vendor", "Documents", "Status", "Last updated", ""].map((h) => (
                  <th
                    key={h}
                    style={{
                      textAlign: "left",
                      fontSize: 12,
                      color: C.textTertiary,
                      fontWeight: 700,
                      padding: "12px 24px",
                      borderBottom: `1px solid ${C.glassBorderSoft}`,
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {bundles.map((b) => (
                <tr
                  key={b.bundle_id}
                  style={{ cursor: "pointer", transition: "background 0.15s ease" }}
                  onClick={() => onSelectBundle(b.bundle_id)}
                  onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.4)")}
                  onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                >
                  <td
                    style={{
                      padding: "14px 24px",
                      borderBottom: `1px solid ${C.glassBorderSoft}`,
                      fontFamily: mono,
                      fontSize: 13.5,
                      fontWeight: 700,
                      color: C.text,
                    }}
                  >
                    {b.txn_reference}
                  </td>
                  <td
                    style={{
                      padding: "14px 24px",
                      borderBottom: `1px solid ${C.glassBorderSoft}`,
                      fontSize: 13.5,
                      color: C.textSecondary,
                    }}
                  >
                    {b.extracted_summary?.vendor_name || "—"}
                  </td>
                  <td
                    style={{
                      padding: "14px 24px",
                      borderBottom: `1px solid ${C.glassBorderSoft}`,
                      fontSize: 13.5,
                      color: C.textSecondary,
                    }}
                  >
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                      <FileText size={15} color={C.accent} /> {b.documents?.length || 0} docs
                    </span>
                  </td>
                  <td style={{ padding: "14px 24px", borderBottom: `1px solid ${C.glassBorderSoft}` }}>
                    <StatusBadge status={b.status} />
                  </td>
                  <td
                    style={{
                      padding: "14px 24px",
                      borderBottom: `1px solid ${C.glassBorderSoft}`,
                      fontSize: 13,
                      color: C.textTertiary,
                    }}
                  >
                    {new Date(b.created_at).toLocaleString()}
                  </td>
                  <td
                    style={{
                      padding: "14px 24px",
                      borderBottom: `1px solid ${C.glassBorderSoft}`,
                      textAlign: "right",
                    }}
                  >
                    <SecondaryButton
                      onClick={(e) => {
                        e?.stopPropagation?.();
                        onSelectBundle(b.bundle_id);
                      }}
                      icon={ArrowRight}
                      style={{ padding: "6px 12px", fontSize: 12.5 }}
                    >
                      View details
                    </SecondaryButton>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
