import React, { useState, useEffect } from "react";
import { Shield, UserCheck, RefreshCw, AlertCircle, CheckCircle2 } from "lucide-react";
import { getUsers } from "../api/endpoints";

import { UserListItem } from "../types/auth";
import { C, glass, sans, mono, PageHeader } from "../theme";

export const UsersManagement: React.FC = () => {
  const [users, setUsers] = useState<UserListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchUsers = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getUsers();
      setUsers(data);
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || "Failed to load users list.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUsers();
  }, []);

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto", fontFamily: sans }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <PageHeader
          title="Auditor & User Directory"
          description="Admin view of all registered auditors, administrators, and assigned access privileges."
        />
        <button
          onClick={fetchUsers}
          disabled={loading}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            padding: "8px 16px",
            borderRadius: 10,
            background: "rgba(255,255,255,0.6)",
            border: `1px solid ${C.glassBorderSoft}`,
            fontFamily: sans,
            fontSize: 13,
            fontWeight: 600,
            color: C.text,
            cursor: loading ? "not-allowed" : "pointer",
            transition: "all 0.2s ease",
          }}
        >
          <RefreshCw size={15} className={loading ? "spin" : ""} />
          <span>Refresh</span>
        </button>
      </div>

      {error && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "12px 16px",
            borderRadius: 12,
            background: C.dangerBg,
            border: `1px solid ${C.dangerBorder}`,
            color: C.danger,
            marginBottom: 20,
            fontSize: 13.5,
            fontWeight: 600,
          }}
        >
          <AlertCircle size={18} />
          <span>{error}</span>
        </div>
      )}

      <div
        style={{
          ...glass({
            padding: 0,
            overflow: "hidden",
            boxShadow: "0 10px 30px rgba(30,40,90,0.06)",
          }),
        }}
      >
        <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left", fontSize: 13.5 }}>
          <thead>
            <tr
              style={{
                background: "rgba(245,247,252,0.85)",
                borderBottom: `1px solid ${C.glassBorderSoft}`,
                color: C.textSecondary,
                fontSize: 12,
                fontWeight: 700,
                textTransform: "uppercase",
                letterSpacing: "0.04em",
              }}
            >
              <th style={{ padding: "14px 20px" }}>Auditor / User</th>
              <th style={{ padding: "14px 20px" }}>Email</th>
              <th style={{ padding: "14px 20px" }}>Assigned Role</th>
              <th style={{ padding: "14px 20px" }}>Status</th>
              <th style={{ padding: "14px 20px" }}>Data Scope</th>
            </tr>
          </thead>
          <tbody>
            {loading && users.length === 0 ? (
              <tr>
                <td colSpan={5} style={{ padding: "36px 20px", textAlign: "center", color: C.textSecondary }}>
                  Loading auditor accounts...
                </td>
              </tr>
            ) : users.length === 0 ? (
              <tr>
                <td colSpan={5} style={{ padding: "36px 20px", textAlign: "center", color: C.textSecondary }}>
                  No auditor accounts found.
                </td>
              </tr>
            ) : (
              users.map((u) => {
                const isAdmin = u.role.toLowerCase() === "admin";
                return (
                  <tr
                    key={u.user_id}
                    style={{
                      borderBottom: `1px solid ${C.glassBorderSoft}`,
                      transition: "background 0.15s ease",
                    }}
                  >
                    <td style={{ padding: "14px 20px", fontWeight: 700, color: C.text }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <div
                          style={{
                            width: 32,
                            height: 32,
                            borderRadius: 8,
                            background: isAdmin
                              ? "linear-gradient(135deg, #10B981, #059669)"
                              : `linear-gradient(135deg, ${C.primary}, ${C.accent})`,
                            color: "#fff",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            fontSize: 12,
                            fontWeight: 800,
                          }}
                        >
                          {isAdmin ? <Shield size={16} /> : <UserCheck size={16} />}
                        </div>
                        <span>{u.name}</span>
                      </div>
                    </td>
                    <td style={{ padding: "14px 20px", fontFamily: mono, color: C.textSecondary, fontSize: 13 }}>
                      {u.email}
                    </td>
                    <td style={{ padding: "14px 20px" }}>
                      <span
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 5,
                          fontSize: 11,
                          fontWeight: 800,
                          padding: "3px 9px",
                          borderRadius: 6,
                          textTransform: "uppercase",
                          letterSpacing: "0.04em",
                          background: isAdmin ? C.successBg : "rgba(91,99,232,0.10)",
                          color: isAdmin ? C.success : C.accent,
                          border: `1px solid ${isAdmin ? C.successBorder : "rgba(91,99,232,0.25)"}`,
                        }}
                      >
                        {isAdmin ? "Admin (Org-wide)" : "Auditor (Scoped)"}
                      </span>
                    </td>
                    <td style={{ padding: "14px 20px" }}>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 5, color: C.success, fontWeight: 600 }}>
                        <CheckCircle2 size={14} /> Active
                      </span>
                    </td>
                    <td style={{ padding: "14px 20px", color: C.textSecondary, fontSize: 12.5 }}>
                      {isAdmin ? "All Bundles & Supervised Workpapers" : "Own & Assigned Bundles Only"}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default UsersManagement;
