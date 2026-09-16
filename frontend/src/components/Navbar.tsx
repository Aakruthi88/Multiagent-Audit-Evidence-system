import React from "react";
import {
  ShieldCheck,
  UploadCloud,
  LayoutDashboard,
  MessageSquareText,
  Layers3,
  Home,
  FileText,
  LogOut,
  Users,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { C, sans, mono } from "../theme";

export type TabKey = "home" | "dashboard" | "upload" | "bundles" | "ask" | "detail" | "users";

interface NavbarProps {
  activeTab: TabKey;
  setActiveTab: (tab: TabKey) => void;
  selectedBundleId?: string;
}

export const Navbar: React.FC<NavbarProps> = ({ activeTab, setActiveTab, selectedBundleId }) => {
  const { user, logout } = useAuth();

  const isAdmin = (user?.role || "").toLowerCase() === "admin" || (user?.role || "").toLowerCase() === "lead";

  const navItems: { key: TabKey; label: string; icon: any }[] = [
    { key: "home", label: "Home", icon: Home },
    { key: "dashboard", label: "Dashboard", icon: LayoutDashboard },
    { key: "upload", label: "New upload", icon: UploadCloud },
    { key: "bundles", label: "Bundles", icon: Layers3 },
    { key: "ask", label: "Ask documents", icon: MessageSquareText },
  ];

  if (isAdmin) {
    navItems.push({ key: "users", label: "Auditors", icon: Users });
  }


  // Derive initials from user name or email
  const getInitials = () => {
    if (!user) return "AU";
    if (user.name) {
      const parts = user.name.trim().split(" ");
      if (parts.length >= 2) {
        return (parts[0][0] + parts[1][0]).toUpperCase();
      }
      return parts[0].substring(0, 2).toUpperCase();
    }
    return user.email.substring(0, 2).toUpperCase();
  };

  return (

    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 20,
        padding: "8px 4px",
        marginBottom: 28,
        fontFamily: sans,
        position: "relative",
      }}
    >
      {/* Brand */}
      <div
        style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer", flexShrink: 0 }}
        onClick={() => setActiveTab("home")}
      >
        <div
          style={{
            width: 34,
            height: 34,
            borderRadius: 10,
            background: `linear-gradient(135deg, ${C.primary}, ${C.accent})`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
            boxShadow: "0 6px 14px rgba(91,99,232,0.3)",
          }}
        >
          <ShieldCheck size={18} color="#fff" strokeWidth={2.4} />
        </div>
        <div style={{ fontSize: 16, fontWeight: 800, color: C.text, lineHeight: 1.1, whiteSpace: "nowrap" }}>
          Audit Evidence
        </div>
      </div>

      {/* Nav Links */}
      <nav
        style={{
          display: "flex",
          alignItems: "center",
          gap: 32,
          overflowX: "auto",
        }}
      >
        {navItems.map(({ key, label }) => {
          const active = activeTab === key;
          return (
            <button
              key={key}
              onClick={() => setActiveTab(key)}
              style={{
                border: "none",
                background: "none",
                padding: "6px 2px",
                color: active ? C.primary : C.textSecondary,
                fontFamily: sans,
                fontSize: 14.5,
                fontWeight: active ? 700 : 500,
                cursor: "pointer",
                whiteSpace: "nowrap",
                display: "inline-flex",
                alignItems: "center",
                borderBottom: active ? `2px solid ${C.accent}` : "2px solid transparent",
                transition: "all 0.2s ease",
              }}
            >
              {label}
            </button>
          );
        })}

        {selectedBundleId && (
          <button
            onClick={() => setActiveTab("detail")}
            style={{
              border: "none",
              background: "none",
              padding: "6px 2px",
              color: activeTab === "detail" ? C.primary : C.textSecondary,
              fontFamily: sans,
              fontSize: 14.5,
              fontWeight: activeTab === "detail" ? 700 : 500,
              cursor: "pointer",
              whiteSpace: "nowrap",
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              borderBottom: activeTab === "detail" ? `2px solid ${C.accent}` : "2px solid transparent",
              transition: "all 0.2s ease",
            }}
          >
            <FileText size={15} color={activeTab === "detail" ? C.accent : C.textSecondary} />
            Bundle detail
          </button>
        )}
      </nav>

      {/* User Profile & Logout Area */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexShrink: 0 }}>
        {/* User Pill / Badge */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "5px 10px 5px 6px",
            borderRadius: 24,
            background: "rgba(255,255,255,0.45)",
            border: `1px solid ${C.glassBorderSoft}`,
            boxShadow: "0 2px 8px rgba(30,40,90,0.06)",
          }}
        >
          {/* Avatar */}
          <div
            style={{
              width: 30,
              height: 30,
              borderRadius: "50%",
              background: isAdmin
                ? `linear-gradient(135deg, ${C.success}, #18A979)`
                : `linear-gradient(135deg, ${C.primary}, ${C.accent})`,
              color: "#fff",
              fontFamily: sans,
              fontSize: 12,
              fontWeight: 700,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
              boxShadow: isAdmin
                ? "0 3px 8px rgba(15,122,86,0.28)"
                : "0 3px 8px rgba(91,99,232,0.28)",
            }}
          >
            {getInitials()}
          </div>

          {/* User Details */}
          <div style={{ display: "flex", flexDirection: "column", minWidth: 0, textAlign: "left" }}>
            <div
              style={{
                fontSize: 12.5,
                fontWeight: 700,
                color: C.text,
                lineHeight: 1.2,
                display: "flex",
                alignItems: "center",
                gap: 5,
              }}
            >
              <span style={{ maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {user?.name || (isAdmin ? "Admin" : "Auditor")}
              </span>
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 800,
                  padding: "1.5px 6px",
                  borderRadius: 6,
                  textTransform: "uppercase",
                  letterSpacing: "0.04em",
                  background: isAdmin ? C.successBg : "rgba(91,99,232,0.12)",
                  color: isAdmin ? C.success : C.accent,
                  border: `1px solid ${isAdmin ? C.successBorder : "rgba(91,99,232,0.25)"}`,
                }}
              >
                {isAdmin ? "Admin" : "Auditor"}
              </span>
            </div>
            <span
              style={{
                fontSize: 11,
                color: C.textTertiary,
                fontFamily: mono,
                maxWidth: 160,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
              title={user?.email}
            >
              {user?.email || (isAdmin ? "admin@audit.local" : "auditor@audit.local")}
            </span>
          </div>


          {/* Logout Button */}
          <button
            type="button"
            id="auth-logout-btn"
            onClick={logout}
            title="Sign out of Audit Session"
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: 28,
              height: 28,
              borderRadius: 8,
              background: "rgba(200,50,35,0.08)",
              border: `1px solid ${C.dangerBorder}`,
              color: C.danger,
              cursor: "pointer",
              marginLeft: 4,
              transition: "all 0.15s ease",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = C.danger;
              e.currentTarget.style.color = "#fff";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "rgba(200,50,35,0.08)";
              e.currentTarget.style.color = C.danger;
            }}
          >
            <LogOut size={13} />
          </button>
        </div>
      </div>
    </div>
  );
};