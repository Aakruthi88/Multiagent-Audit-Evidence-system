import React, { useState } from "react";
import {
  ShieldCheck,
  Lock,
  Mail,
  ArrowRight,
  AlertCircle,
  Eye,
  EyeOff,
  UserCheck,
  Shield,
  KeyRound,
  CheckCircle2,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { C, glass, sans, mono } from "../theme";

interface LoginProps {
  onLoginSuccess?: () => void;
}

export const Login: React.FC<LoginProps> = ({ onLoginSuccess }) => {
  const { login, error, clearError } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    clearError();

    if (!email.trim()) {
      setFormError("Please enter your corporate audit email.");
      return;
    }

    if (!password) {
      setFormError("Please enter your password.");
      return;
    }

    setIsSubmitting(true);
    const result = await login(email, password);
    setIsSubmitting(false);

    if (result.success) {
      if (onLoginSuccess) {
        onLoginSuccess();
      }
    }
  };

  const handleSelectDemoAccount = (demoEmail: string, demoPass: string) => {
    setEmail(demoEmail);
    setPassword(demoPass);
    setFormError(null);
    clearError();
  };

  const activeError = formError || error;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "82vh",
        padding: "20px 16px",
        fontFamily: sans,
      }}
    >
      <div
        style={{
          width: "100%",
          maxWidth: 480,
          ...glass({
            padding: "36px 32px 32px",
            boxShadow: "0 20px 50px rgba(40,48,107,0.18), inset 0 1px 0 rgba(255,255,255,0.8)",
          }),
        }}
      >
        {/* Header & Branding */}
        <div style={{ textAlign: "center", marginBottom: 28 }}>
          <div
            style={{
              width: 56,
              height: 56,
              borderRadius: 16,
              background: `linear-gradient(135deg, ${C.primary}, ${C.accent})`,
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              marginBottom: 14,
              boxShadow: "0 8px 20px rgba(91,99,232,0.35)",
            }}
          >
            <ShieldCheck size={30} color="#fff" strokeWidth={2.4} />
          </div>
          <h1
            style={{
              fontSize: 24,
              fontWeight: 800,
              color: C.text,
              letterSpacing: "-0.02em",
              marginBottom: 6,
            }}
          >
            Audit Evidence System
          </h1>
          <p style={{ fontSize: 13.5, color: C.textSecondary, fontWeight: 500, lineHeight: 1.4 }}>
            Multi-Agent Cross-Reconciliation & Verification Platform
          </p>
        </div>

        {/* Error Alert */}
        {activeError && (
          <div
            style={{
              display: "flex",
              alignItems: "flex-start",
              gap: 10,
              padding: "12px 14px",
              borderRadius: 12,
              background: C.dangerBg,
              border: `1px solid ${C.dangerBorder}`,
              marginBottom: 20,
              animation: "fadeIn 0.2s ease-in-out",
            }}
          >
            <AlertCircle size={18} color={C.danger} style={{ flexShrink: 0, marginTop: 1 }} />
            <div style={{ fontSize: 13, color: C.danger, fontWeight: 600, lineHeight: 1.4 }}>
              {activeError}
            </div>
          </div>
        )}

        {/* Login Form */}
        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          {/* Email field */}
          <div>
            <label
              htmlFor="audit-email-input"
              style={{
                display: "block",
                fontSize: 12.5,
                fontWeight: 700,
                color: C.text,
                marginBottom: 6,
                textTransform: "uppercase",
                letterSpacing: "0.04em",
              }}
            >
              Auditor Email
            </label>
            <div style={{ position: "relative" }}>
              <div
                style={{
                  position: "absolute",
                  left: 12,
                  top: "50%",
                  transform: "translateY(-50%)",
                  color: C.textTertiary,
                  pointerEvents: "none",
                  display: "flex",
                  alignItems: "center",
                }}
              >
                <Mail size={17} />
              </div>
              <input
                id="audit-email-input"
                type="email"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  if (activeError) {
                    setFormError(null);
                    clearError();
                  }
                }}
                placeholder="auditor@audit.local"
                autoComplete="email"
                style={{
                  width: "100%",
                  padding: "11px 12px 11px 38px",
                  fontSize: 14,
                  fontFamily: sans,
                  color: C.text,
                  background: "rgba(255,255,255,0.7)",
                  border: `1.5px solid ${C.glassBorderSoft}`,
                  borderRadius: 12,
                  outline: "none",
                  transition: "all 0.2s ease",
                  boxShadow: "inset 0 1px 2px rgba(0,0,0,0.03)",
                }}
                onFocus={(e) => {
                  e.target.style.borderColor = C.accent;
                  e.target.style.background = "rgba(255,255,255,0.95)";
                  e.target.style.boxShadow = "0 0 0 3px rgba(91,99,232,0.18)";
                }}
                onBlur={(e) => {
                  e.target.style.borderColor = C.glassBorderSoft;
                  e.target.style.background = "rgba(255,255,255,0.7)";
                  e.target.style.boxShadow = "inset 0 1px 2px rgba(0,0,0,0.03)";
                }}
              />
            </div>
          </div>

          {/* Password field */}
          <div>
            <label
              htmlFor="audit-password-input"
              style={{
                display: "block",
                fontSize: 12.5,
                fontWeight: 700,
                color: C.text,
                marginBottom: 6,
                textTransform: "uppercase",
                letterSpacing: "0.04em",
              }}
            >
              Password
            </label>
            <div style={{ position: "relative" }}>
              <div
                style={{
                  position: "absolute",
                  left: 12,
                  top: "50%",
                  transform: "translateY(-50%)",
                  color: C.textTertiary,
                  pointerEvents: "none",
                  display: "flex",
                  alignItems: "center",
                }}
              >
                <Lock size={17} />
              </div>
              <input
                id="audit-password-input"
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  if (activeError) {
                    setFormError(null);
                    clearError();
                  }
                }}
                placeholder="••••••••••••"
                autoComplete="current-password"
                style={{
                  width: "100%",
                  padding: "11px 40px 11px 38px",
                  fontSize: 14,
                  fontFamily: sans,
                  color: C.text,
                  background: "rgba(255,255,255,0.7)",
                  border: `1.5px solid ${C.glassBorderSoft}`,
                  borderRadius: 12,
                  outline: "none",
                  transition: "all 0.2s ease",
                  boxShadow: "inset 0 1px 2px rgba(0,0,0,0.03)",
                }}
                onFocus={(e) => {
                  e.target.style.borderColor = C.accent;
                  e.target.style.background = "rgba(255,255,255,0.95)";
                  e.target.style.boxShadow = "0 0 0 3px rgba(91,99,232,0.18)";
                }}
                onBlur={(e) => {
                  e.target.style.borderColor = C.glassBorderSoft;
                  e.target.style.background = "rgba(255,255,255,0.7)";
                  e.target.style.boxShadow = "inset 0 1px 2px rgba(0,0,0,0.03)";
                }}
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                style={{
                  position: "absolute",
                  right: 12,
                  top: "50%",
                  transform: "translateY(-50%)",
                  background: "none",
                  border: "none",
                  color: C.textTertiary,
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  padding: 2,
                }}
                title={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          {/* Sign In Submit Button */}
          <button
            type="submit"
            disabled={isSubmitting}
            id="audit-signin-btn"
            style={{
              marginTop: 6,
              padding: "12px 20px",
              borderRadius: 12,
              background: `linear-gradient(135deg, ${C.primary}, ${C.accent})`,
              color: "#fff",
              border: "none",
              fontSize: 14.5,
              fontWeight: 700,
              fontFamily: sans,
              cursor: isSubmitting ? "not-allowed" : "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 8,
              boxShadow: "0 6px 18px rgba(91,99,232,0.32)",
              transition: "all 0.2s ease",
              opacity: isSubmitting ? 0.75 : 1,
            }}
            onMouseEnter={(e) => {
              if (!isSubmitting) {
                e.currentTarget.style.transform = "translateY(-1px)";
                e.currentTarget.style.boxShadow = "0 8px 24px rgba(91,99,232,0.4)";
              }
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.transform = "none";
              e.currentTarget.style.boxShadow = "0 6px 18px rgba(91,99,232,0.32)";
            }}
          >
            {isSubmitting ? (
              <>
                <div
                  style={{
                    width: 16,
                    height: 16,
                    border: "2.5px solid rgba(255,255,255,0.4)",
                    borderTopColor: "#fff",
                    borderRadius: "50%",
                    animation: "spin 0.8s linear infinite",
                  }}
                />
                <span>Verifying credentials...</span>
              </>
            ) : (
              <>
                <span>Sign In to Audit Workspace</span>
                <ArrowRight size={17} />
              </>
            )}
          </button>
        </form>

        {/* Demo Accounts Quick-Select */}
        <div style={{ marginTop: 28, paddingTop: 20, borderTop: `1px solid ${C.glassBorderSoft}` }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: 12,
            }}
          >
            <div
              style={{
                fontSize: 11.5,
                fontWeight: 800,
                color: C.textSecondary,
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                display: "flex",
                alignItems: "center",
                gap: 6,
              }}
            >
              <KeyRound size={13} color={C.accent} />
              Demo Roles & Accounts
            </div>
            <span style={{ fontSize: 11, color: C.textTertiary, fontWeight: 500 }}>
              Click to autofill
            </span>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {/* Demo Auditor */}
            <button
              type="button"
              id="demo-auditor-pill"
              onClick={() => handleSelectDemoAccount("auditor@audit.local", "auditor123")}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "9px 12px",
                borderRadius: 10,
                background:
                  email === "auditor@audit.local"
                    ? "rgba(91,99,232,0.12)"
                    : "rgba(255,255,255,0.45)",
                border:
                  email === "auditor@audit.local"
                    ? `1.5px solid ${C.accent}`
                    : `1px solid ${C.glassBorderSoft}`,
                cursor: "pointer",
                textAlign: "left",
                transition: "all 0.15s ease",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <div
                  style={{
                    width: 24,
                    height: 24,
                    borderRadius: 6,
                    background: "rgba(91,99,232,0.15)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: C.accent,
                  }}
                >
                  <UserCheck size={14} />
                </div>
                <div>
                  <div style={{ fontSize: 12.5, fontWeight: 700, color: C.text }}>
                    Demo Auditor
                  </div>
                  <div style={{ fontSize: 11, color: C.textSecondary, fontFamily: mono }}>
                    auditor@audit.local
                  </div>
                </div>
              </div>
              <span
                style={{
                  fontSize: 10.5,
                  fontWeight: 700,
                  color: C.accent,
                  background: "rgba(91,99,232,0.10)",
                  padding: "2px 7px",
                  borderRadius: 6,
                }}
              >
                Auditor Role
              </span>
            </button>

            {/* Demo Lead Auditor */}
            <button
              type="button"
              id="demo-lead-pill"
              onClick={() => handleSelectDemoAccount("lead@audit.local", "lead123")}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "9px 12px",
                borderRadius: 10,
                background:
                  email === "lead@audit.local"
                    ? "rgba(15,122,86,0.12)"
                    : "rgba(255,255,255,0.45)",
                border:
                  email === "lead@audit.local"
                    ? `1.5px solid ${C.success}`
                    : `1px solid ${C.glassBorderSoft}`,
                cursor: "pointer",
                textAlign: "left",
                transition: "all 0.15s ease",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <div
                  style={{
                    width: 24,
                    height: 24,
                    borderRadius: 6,
                    background: "rgba(15,122,86,0.15)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: C.success,
                  }}
                >
                  <Shield size={14} />
                </div>
                <div>
                  <div style={{ fontSize: 12.5, fontWeight: 700, color: C.text }}>
                    Demo Lead Auditor
                  </div>
                  <div style={{ fontSize: 11, color: C.textSecondary, fontFamily: mono }}>
                    lead@audit.local
                  </div>
                </div>
              </div>
              <span
                style={{
                  fontSize: 10.5,
                  fontWeight: 700,
                  color: C.success,
                  background: "rgba(15,122,86,0.10)",
                  padding: "2px 7px",
                  borderRadius: 6,
                }}
              >
                Lead Role (All Bundles)
              </span>
            </button>

            {/* Demo Second Auditor */}
            <button
              type="button"
              id="demo-auditor2-pill"
              onClick={() => handleSelectDemoAccount("auditor2@audit.local", "auditor123")}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "9px 12px",
                borderRadius: 10,
                background:
                  email === "auditor2@audit.local"
                    ? "rgba(168,91,11,0.12)"
                    : "rgba(255,255,255,0.45)",
                border:
                  email === "auditor2@audit.local"
                    ? `1.5px solid ${C.warning}`
                    : `1px solid ${C.glassBorderSoft}`,
                cursor: "pointer",
                textAlign: "left",
                transition: "all 0.15s ease",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <div
                  style={{
                    width: 24,
                    height: 24,
                    borderRadius: 6,
                    background: "rgba(168,91,11,0.15)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: C.warning,
                  }}
                >
                  <UserCheck size={14} />
                </div>
                <div>
                  <div style={{ fontSize: 12.5, fontWeight: 700, color: C.text }}>
                    Second Auditor
                  </div>
                  <div style={{ fontSize: 11, color: C.textSecondary, fontFamily: mono }}>
                    auditor2@audit.local
                  </div>
                </div>
              </div>
              <span
                style={{
                  fontSize: 10.5,
                  fontWeight: 700,
                  color: C.warning,
                  background: "rgba(168,91,11,0.10)",
                  padding: "2px 7px",
                  borderRadius: 6,
                }}
              >
                Tenant Isolation Scope
              </span>
            </button>
          </div>
        </div>

        {/* Security & Compliance Footer Note */}
        <div
          style={{
            marginTop: 22,
            padding: "10px 12px",
            borderRadius: 10,
            background: "rgba(40,48,107,0.04)",
            border: `1px solid ${C.glassBorderSoft}`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 12,
            fontSize: 11,
            color: C.textTertiary,
            fontWeight: 600,
          }}
        >
          <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
            <CheckCircle2 size={12} color={C.success} /> JWT HS256 Protected
          </span>
          <span>•</span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
            <CheckCircle2 size={12} color={C.success} /> RBAC Isolated
          </span>
          <span>•</span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
            <CheckCircle2 size={12} color={C.success} /> SHA-256 Verified
          </span>
        </div>
      </div>
    </div>
  );
};
