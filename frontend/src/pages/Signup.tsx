import React, { useState } from "react";
import {
  ShieldCheck,
  Lock,
  Mail,
  User,
  ArrowRight,
  AlertCircle,
  Eye,
  EyeOff,
  LogIn,
} from "lucide-react";

import { signupUser } from "../api/endpoints";
import { C, glass, sans } from "../theme";

interface SignupProps {
  onSignupSuccess: (email: string) => void;
  onNavigateToLogin: () => void;
}

export const Signup: React.FC<SignupProps> = ({ onSignupSuccess, onNavigateToLogin }) => {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);

    const cleanName = fullName.trim();
    const cleanEmail = email.trim().toLowerCase();

    if (!cleanName) {
      setFormError("Please enter your full name.");
      return;
    }

    if (!cleanEmail) {
      setFormError("Please enter your corporate audit email.");
      return;
    }

    const emailRegex = /^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$/;
    if (!emailRegex.test(cleanEmail)) {
      setFormError("Please enter a valid email address.");
      return;
    }

    if (!password) {
      setFormError("Please enter a password.");
      return;
    }

    if (password.length < 6) {
      setFormError("Password must be at least 6 characters long.");
      return;
    }

    if (password !== confirmPassword) {
      setFormError("Passwords do not match. Please check and retype.");
      return;
    }

    setIsSubmitting(true);
    try {
      await signupUser({
        name: cleanName,
        email: cleanEmail,
        password: password,
        confirm_password: confirmPassword,
      });
      setIsSubmitting(false);
      onSignupSuccess(cleanEmail);
    } catch (err: any) {
      setIsSubmitting(false);
      const detail = err.response?.data?.detail || err.message || "Failed to create account. Please try again.";
      setFormError(detail);
    }
  };

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
        <div style={{ textAlign: "center", marginBottom: 24 }}>
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
            Create Auditor Account
          </h1>
          <p style={{ fontSize: 13.5, color: C.textSecondary, fontWeight: 500, lineHeight: 1.4 }}>
            Join the Multi-Agent Audit Evidence System
          </p>
        </div>

        {/* Error Alert */}
        {formError && (
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
              {formError}
            </div>
          </div>
        )}

        {/* Signup Form */}
        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* Full Name field */}
          <div>
            <label
              htmlFor="signup-name-input"
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
              Full Name
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
                <User size={17} />
              </div>
              <input
                id="signup-name-input"
                type="text"
                value={fullName}
                onChange={(e) => {
                  setFullName(e.target.value);
                  if (formError) setFormError(null);
                }}
                placeholder="Jane Doe"
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

          {/* Email field */}
          <div>
            <label
              htmlFor="signup-email-input"
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
              Corporate Audit Email
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
                id="signup-email-input"
                type="email"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  if (formError) setFormError(null);
                }}
                placeholder="jane.doe@audit.deloitte.com"
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
              htmlFor="signup-password-input"
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
              Password (min. 6 characters)
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
                id="signup-password-input"
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  if (formError) setFormError(null);
                }}
                placeholder="••••••••••••"
                autoComplete="new-password"
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

          {/* Confirm Password field */}
          <div>
            <label
              htmlFor="signup-confirm-password-input"
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
              Confirm Password
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
                id="signup-confirm-password-input"
                type={showConfirmPassword ? "text" : "password"}
                value={confirmPassword}
                onChange={(e) => {
                  setConfirmPassword(e.target.value);
                  if (formError) setFormError(null);
                }}
                placeholder="••••••••••••"
                autoComplete="new-password"
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
                onClick={() => setShowConfirmPassword(!showConfirmPassword)}
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
                title={showConfirmPassword ? "Hide password" : "Show password"}
              >
                {showConfirmPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          {/* Submit Button */}
          <button
            type="submit"
            disabled={isSubmitting}
            id="audit-signup-btn"
            style={{
              marginTop: 8,
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
                <span>Creating account...</span>
              </>
            ) : (
              <>
                <span>Create Audit Account</span>
                <ArrowRight size={17} />
              </>
            )}
          </button>
        </form>

        {/* Back to Login Link */}
        <div
          style={{
            marginTop: 24,
            paddingTop: 18,
            borderTop: `1px solid ${C.glassBorderSoft}`,
            textAlign: "center",
          }}
        >
          <p style={{ fontSize: 13, color: C.textSecondary, marginBottom: 8, fontWeight: 500 }}>
            Already have an account?
          </p>
          <button
            type="button"
            id="goto-login-btn"
            onClick={onNavigateToLogin}
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
            <LogIn size={15} />
            <span>Sign in to existing account</span>
          </button>
        </div>
      </div>
    </div>
  );
};

export default Signup;
