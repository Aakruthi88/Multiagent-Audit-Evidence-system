import React from "react";
import {
  UploadCloud,
  FileStack,
  MessageSquareText,
  ArrowRight,
  ShieldCheck,
  Sparkles,
  GitBranch,
  Users2,
  FileText,
  LayoutDashboard,
} from "lucide-react";
import {
  C,
  sans,
  glass,
  glassSoft,
  PrimaryButton,
  SecondaryButton,
} from "../theme";

interface HomeProps {
  onNavigate: (tab: "home" | "dashboard" | "upload" | "bundles" | "ask") => void;
}

const homeFeatures = [
  {
    icon: FileText,
    title: "Automated Evidence Matching",
    body: "Matches PO, Invoice, GRN and Bank Statements with deterministic logic and AI insights.",
  },
  {
    icon: Sparkles,
    title: "Saves Time",
    body: "Reduces manual verification time by up to 70%, enabling faster audit cycles.",
  },
  {
    icon: ShieldCheck,
    title: "Improves Accuracy",
    body: "Detects discrepancies, missing documents and anomalies to reduce audit risk.",
  },
  {
    icon: Users2,
    title: "Audit-Ready Reports",
    body: "Organized bundles with clear verification status, explanations and traceable evidence.",
  },
];

const homeSteps = [
  { icon: UploadCloud, title: "Upload Documents", body: "Add PO, Invoice, GRN, Bank statements, etc." },
  { icon: FileStack, title: "Automatic Extraction", body: "Extract key fields using OCR and AI." },
  { icon: GitBranch, title: "Intelligent Matching", body: "Match documents with business rules and LLM." },
  { icon: ShieldCheck, title: "Get Insights", body: "View verification results, discrepancies and summaries." },
];

const homeImpact = [
  { label: "Faster audit cycles", value: "70%" },
  { label: "Matching accuracy", value: "90%+" },
  { label: "Reduction in manual effort", value: "50%" },
  { label: "Traceable and audit-ready", value: "100%" },
];

const homeAudience = [
  { icon: Users2, label: "Internal Audit Teams" },
  { icon: LayoutDashboard, label: "Finance & Accounts" },
  { icon: ShieldCheck, label: "Compliance Teams" },
  { icon: FileStack, label: "External Auditors" },
];

export const Home: React.FC<HomeProps> = ({ onNavigate }) => {
  return (
    <div>
      {/* Hero Banner */}
      <div
        style={{
          ...glass({
            position: "relative",
            padding: "48px 46px",
            marginBottom: 26,
            overflow: "hidden",
          }),
        }}
      >
        <div
          style={{
            position: "absolute",
            top: -80,
            right: -60,
            width: 280,
            height: 280,
            borderRadius: "50%",
            background: "radial-gradient(circle, rgba(91,99,232,0.22), transparent 70%)",
            pointerEvents: "none",
          }}
        />
        <div
          style={{
            position: "absolute",
            bottom: -100,
            left: "30%",
            width: 220,
            height: 220,
            borderRadius: "50%",
            background: "radial-gradient(circle, rgba(255,180,150,0.2), transparent 70%)",
            pointerEvents: "none",
          }}
        />
        <div style={{ position: "relative", zIndex: 1, maxWidth: 680 }}>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              fontSize: 12.5,
              fontWeight: 700,
              color: C.primary,
              fontFamily: sans,
              marginBottom: 14,
              background: "rgba(255,255,255,0.6)",
              border: `1px solid ${C.glassBorder}`,
              borderRadius: 20,
              padding: "5px 12px",
            }}
          >
            <Sparkles size={13} color={C.accent} /> Audit Evidence Assistant
          </div>
          <h1
            style={{
              fontSize: 34,
              fontWeight: 800,
              color: C.text,
              fontFamily: sans,
              margin: "0 0 14px",
              lineHeight: 1.25,
            }}
          >
            Transforming Audit Evidence into <span style={{ color: C.accent }}>Clarity</span>
          </h1>
          <p
            style={{
              fontSize: 15,
              color: C.textSecondary,
              fontFamily: sans,
              lineHeight: 1.65,
              margin: "0 0 22px",
            }}
          >
            Upload your source documents, let AI intelligently verify, match, and analyze evidence across
            Purchase Orders, Invoices, GRNs, and Bank Statements — so your audits are faster, smarter, and
            more reliable.
          </p>
          <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
            <PrimaryButton icon={ArrowRight} onClick={() => onNavigate("upload")}>
              Upload Documents
            </PrimaryButton>
            <SecondaryButton icon={MessageSquareText} onClick={() => onNavigate("ask")}>
              Ask a Question
            </SecondaryButton>
          </div>
          <div style={{ fontSize: 12.5, color: C.textTertiary, fontFamily: sans }}>
            Trusted by audit and finance teams to reduce effort, save time, and improve accuracy.
          </div>
        </div>
      </div>

      {/* 4 Features Row */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          gap: 14,
          marginBottom: 26,
        }}
      >
        {homeFeatures.map((f) => {
          const Icon = f.icon;
          return (
            <div key={f.title} style={glass({ padding: "20px 18px" })}>
              <div
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: 10,
                  background: "rgba(255,255,255,0.75)",
                  border: `1px solid ${C.glassBorder}`,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  marginBottom: 12,
                }}
              >
                <Icon size={18} color={C.primary} />
              </div>
              <div style={{ fontSize: 14.5, fontWeight: 800, color: C.text, fontFamily: sans, marginBottom: 6 }}>
                {f.title}
              </div>
              <div style={{ fontSize: 12.5, color: C.textSecondary, fontFamily: sans, lineHeight: 1.45 }}>
                {f.body}
              </div>
            </div>
          );
        })}
      </div>

      {/* How It Works & Real Impact Grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "2fr 1fr",
          gap: 20,
          marginBottom: 26,
        }}
      >
        {/* How it works */}
        <div style={glass({ padding: 24 })}>
          <div style={{ fontSize: 16, fontWeight: 800, color: C.text, fontFamily: sans, marginBottom: 4 }}>
            How It Works
          </div>
          <div style={{ fontSize: 13, color: C.textSecondary, fontFamily: sans, marginBottom: 20 }}>
            From upload to audit-ready insights in a few simple steps.
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 14 }}>
            {homeSteps.map((s, i) => {
              const Icon = s.icon;
              return (
                <div key={s.title}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                    <div
                      style={{
                        width: 22,
                        height: 22,
                        borderRadius: "50%",
                        background: C.primary,
                        color: "#fff",
                        fontSize: 11,
                        fontWeight: 700,
                        fontFamily: sans,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                      }}
                    >
                      {i + 1}
                    </div>
                    <div
                      style={{
                        width: 26,
                        height: 26,
                        borderRadius: 8,
                        background: "rgba(91,99,232,0.14)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                      }}
                    >
                      <Icon size={14} color={C.accent} />
                    </div>
                  </div>
                  <div style={{ fontSize: 13.5, fontWeight: 700, color: C.text, fontFamily: sans, marginBottom: 4 }}>
                    {s.title}
                  </div>
                  <div style={{ fontSize: 12, color: C.textSecondary, fontFamily: sans, lineHeight: 1.45 }}>
                    {s.body}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Real impact */}
        <div style={glass({ padding: 24 })}>
          <div style={{ fontSize: 16, fontWeight: 800, color: C.text, fontFamily: sans, marginBottom: 16 }}>
            Real Impact
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            {homeImpact.map((m) => (
              <div key={m.label}>
                <div style={{ fontSize: 24, fontWeight: 800, color: C.text, fontFamily: sans }}>{m.value}</div>
                <div style={{ fontSize: 12, color: C.textSecondary, fontFamily: sans, lineHeight: 1.4, marginTop: 2 }}>
                  {m.label}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Who It Helps & Mission */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        {/* Who it helps */}
        <div style={glass({ padding: 24 })}>
          <div style={{ fontSize: 16, fontWeight: 800, color: C.text, fontFamily: sans, marginBottom: 4 }}>
            Who It Helps
          </div>
          <div style={{ fontSize: 13, color: C.textSecondary, fontFamily: sans, marginBottom: 16 }}>
            Designed for auditors, finance teams, and compliance professionals.
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            {homeAudience.map((a) => {
              const Icon = a.icon;
              return (
                <div
                  key={a.label}
                  style={{
                    ...glassSoft({
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      padding: "11px 14px",
                      background: "rgba(255,255,255,0.4)",
                    }),
                  }}
                >
                  <Icon size={15} color={C.primary} />
                  <span style={{ fontSize: 12.5, fontWeight: 700, color: C.text, fontFamily: sans }}>
                    {a.label}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Our mission */}
        <div
          style={glass({
            padding: 24,
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
          })}
        >
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
              <div
                style={{
                  width: 30,
                  height: 30,
                  borderRadius: 9,
                  background: "rgba(255,255,255,0.75)",
                  border: `1px solid ${C.glassBorder}`,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                }}
              >
                <GitBranch size={15} color={C.primary} />
              </div>
              <div style={{ fontSize: 16, fontWeight: 800, color: C.text, fontFamily: sans }}>
                Our Mission
              </div>
            </div>
            <div style={{ fontSize: 13, color: C.textSecondary, fontFamily: sans, lineHeight: 1.6 }}>
              To make audit evidence verification faster, fairer and more transparent using the power of AI
              and deterministic automation.
            </div>
          </div>
          <div style={{ marginTop: 16, paddingTop: 16, borderTop: `1px solid ${C.glassBorderSoft}` }}>
            <div style={{ fontSize: 15, fontStyle: "italic", fontWeight: 700, color: C.text, fontFamily: sans, lineHeight: 1.4 }}>
              "Smarter audits. Stronger businesses."
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
