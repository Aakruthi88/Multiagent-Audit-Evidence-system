import React from "react";
import { ShieldCheck, UploadCloud, LayoutDashboard, MessageSquareText, Layers3, Home, FileText } from "lucide-react";
import { C, sans } from "../theme";

export type TabKey = "home" | "dashboard" | "upload" | "bundles" | "ask" | "detail";

interface NavbarProps {
  activeTab: TabKey;
  setActiveTab: (tab: TabKey) => void;
  selectedBundleId?: string;
}

export const Navbar: React.FC<NavbarProps> = ({ activeTab, setActiveTab, selectedBundleId }) => {
  const navItems: { key: TabKey; label: string; icon: any }[] = [
    { key: "home", label: "Home", icon: Home },
    { key: "dashboard", label: "Dashboard", icon: LayoutDashboard },
    { key: "upload", label: "New upload", icon: UploadCloud },
    { key: "bundles", label: "Bundles", icon: Layers3 },
    { key: "ask", label: "Ask documents", icon: MessageSquareText },
  ];

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

      {/* User Avatar */}
      <div
        style={{
          width: 32,
          height: 32,
          borderRadius: "50%",
          background: `linear-gradient(135deg, ${C.primary}, ${C.accent})`,
          color: "#fff",
          fontFamily: sans,
          fontSize: 12.5,
          fontWeight: 700,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
          boxShadow: "0 4px 10px rgba(91,99,232,0.25)",
        }}
        title="Audit Reviewer"
      >
        AK
      </div>
    </div>
  );
};