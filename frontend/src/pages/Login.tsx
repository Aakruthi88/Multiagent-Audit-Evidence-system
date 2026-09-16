import React, { useState } from "react";
import {
  ShieldCheck,
  Lock,
  Mail,
  ArrowRight,
  AlertCircle,
  Eye,
  EyeOff,
  UserPlus,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { C, glass, sans } from "../theme";

interface LoginProps {
  onLoginSuccess?: () => void;
  onNavigateToSignup?: () => void;
  successNotice?: string | null;
}

export const Login: React.FC<LoginProps> = ({
  onLoginSuccess,
  onNavigateToSignup,
  successNotice,
}) => {
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
          maxWidth: 440,
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

        {/* Success Notice if coming from Signup */}
        {successNotice && !activeError && (
          <div
            style={{
              display: "flex",
              alignItems: "flex-start",
              gap: 10,
              padding: "12px 14px",
              borderRadius: 12,
              background: C.successBg,
              border: `1px solid ${C.successBorder}`,
              marginBottom: 20,
            }}
          >
            <ShieldCheck size={18} color={C.success} style={{ flexShrink: 0, marginTop: 1 }} />
            <div style={{ fontSize: 13, color: C.success, fontWeight: 600, lineHeight: 1.4 }}>
              {successNotice}
            </div>
          </div>
        )}

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
                fontSize: 12,
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
                placeholder="name@audit.local"
                autoComplete="email"
                required
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
                fontSize: 12,
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
                required
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
                <span>Signing in...</span>
              </>
            ) : (
              <>
                <span>Sign In to Audit Workspace</span>
                <ArrowRight size={17} />
              </>
            )}
          </button>
        </form>

        {/* Signup Link */}
        {onNavigateToSignup && (
          <div
            style={{
              marginTop: 24,
              paddingTop: 18,
              borderTop: `1px solid ${C.glassBorderSoft}`,
              textAlign: "center",
            }}
          >
            <p style={{ fontSize: 13, color: C.textSecondary, marginBottom: 8, fontWeight: 500 }}>
              Don't have an account?
            </p>
            <button
              type="button"
              id="goto-signup-btn"
              onClick={onNavigateToSignup}
              style={{
                background: "none",
                border: "none",
                color: C.accent,
                fontSize: 13.5,
                fontWeight: 700,
                fontFamily: sans,
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "4px 8px",
                borderRadius: 8,
                transition: "all 0.15s ease",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = "rgba(91,99,232,0.08)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = "none";
              }}
            >
              <UserPlus size={15} />
              <span>Create an account</span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default Login;
