import React from "react";
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Clock,
  FileText,
  ShieldCheck,
  GitBranch,
} from "lucide-react";

export const C = {
  text: "#1B1E2B",
  textSecondary: "#5B5F72",
  textTertiary: "#8B8FA3",
  primary: "#28306B",
  accent: "#5B63E8",
  success: "#0F7A56",
  successBg: "rgba(20,150,110,0.14)",
  successBorder: "rgba(20,150,110,0.28)",
  warning: "#A85B0B",
  warningBg: "rgba(200,130,20,0.14)",
  warningBorder: "rgba(200,130,20,0.28)",
  danger: "#B7291F",
  dangerBg: "rgba(200,50,35,0.13)",
  dangerBorder: "rgba(200,50,35,0.26)",
  glassBorder: "rgba(255,255,255,0.5)",
  glassBorderSoft: "rgba(255,255,255,0.35)",
};

export const sans = "'Inter', -apple-system, BlinkMacSystemFont, sans-serif";
export const mono = "'IBM Plex Mono', 'SFMono-Regular', Menlo, monospace";

export const glass = (extra: React.CSSProperties = {}): React.CSSProperties => ({
  background: "rgba(255,255,255,0.38)",
  backdropFilter: "blur(28px) saturate(160%)",
  WebkitBackdropFilter: "blur(28px) saturate(160%)",
  border: `1px solid ${C.glassBorder}`,
  borderRadius: 20,
  boxShadow: "0 10px 40px rgba(30,40,90,0.12), inset 0 1px 0 rgba(255,255,255,0.7), inset 0 0 0 1px rgba(255,255,255,0.08)",
  ...extra,
});

export const glassSoft = (extra: React.CSSProperties = {}): React.CSSProperties => ({
  background: "rgba(255,255,255,0.28)",
  backdropFilter: "blur(20px) saturate(150%)",
  WebkitBackdropFilter: "blur(20px) saturate(150%)",
  border: `1px solid ${C.glassBorderSoft}`,
  borderRadius: 14,
  ...extra,
});

export const FontImport: React.FC = () => (
  <style>{`
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap');
    * { box-sizing: border-box; }
    ::-webkit-scrollbar { width: 8px; height: 8px; }
    ::-webkit-scrollbar-thumb { background: rgba(40,48,107,0.18); border-radius: 8px; }
    ::-webkit-scrollbar-thumb:hover { background: rgba(40,48,107,0.3); }
  `}</style>
);

export const Backdrop: React.FC = () => (
  <div style={{ position: "fixed", inset: 0, zIndex: 0, overflow: "hidden", pointerEvents: "none" }}>
    {/* Full-resolution, crisp background image from /image.png */}
    <div
      style={{
        position: "absolute",
        inset: 0,
        backgroundImage: "url(/image.png)",
        backgroundSize: "cover",
        backgroundPosition: "center",
      }}
    />

    {/* Soft translucent diagonal wash of light blue / lavender tones (0.28 - 0.40 opacity) */}
    <div
      style={{
        position: "absolute",
        inset: 0,
        background:
          "linear-gradient(150deg, rgba(238,240,251,0.38) 0%, rgba(231,235,251,0.28) 40%, rgba(243,236,246,0.32) 70%, rgba(239,241,250,0.40) 100%)",
      }}
    />

    {/* Ambient glowing color accents */}
    <div
      style={{
        position: "absolute",
        top: -160,
        left: -120,
        width: 560,
        height: 560,
        borderRadius: "50%",
        background: "radial-gradient(circle, rgba(91,99,232,0.20), transparent 70%)",
        filter: "blur(20px)",
      }}
    />
    <div
      style={{
        position: "absolute",
        bottom: -200,
        right: -140,
        width: 620,
        height: 620,
        borderRadius: "50%",
        background: "radial-gradient(circle, rgba(255,180,150,0.18), transparent 70%)",
        filter: "blur(20px)",
      }}
    />
    <div
      style={{
        position: "absolute",
        top: "30%",
        right: "18%",
        width: 320,
        height: 320,
        borderRadius: "50%",
        background: "radial-gradient(circle, rgba(150,200,255,0.18), transparent 70%)",
        filter: "blur(16px)",
      }}
    />

    {/* Subtle audit-themed watermark motifs */}
    <FileText
      size={220}
      color={C.primary}
      style={{ position: "absolute", top: "8%", left: "6%", opacity: 0.05, transform: "rotate(-14deg)" }}
      strokeWidth={1}
    />
    <CheckCircle2
      size={170}
      color={C.success}
      style={{ position: "absolute", bottom: "14%", left: "12%", opacity: 0.06, transform: "rotate(8deg)" }}
      strokeWidth={1}
    />
    <ShieldCheck
      size={260}
      color={C.accent}
      style={{ position: "absolute", top: "18%", right: "8%", opacity: 0.05, transform: "rotate(10deg)" }}
      strokeWidth={1}
    />
    <GitBranch
      size={180}
      color={C.primary}
      style={{ position: "absolute", bottom: "8%", right: "16%", opacity: 0.05, transform: "rotate(-6deg)" }}
      strokeWidth={1}
    />
  </div>
);

export function StatusBadge({ status }: { status: string }) {
  const norm = (status || "").toLowerCase().replace(/_/g, "");
  let cfg = {
    label: status ? status.replace(/_/g, " ") : "Unknown",
    fg: C.textSecondary,
    bg: "rgba(120,125,145,0.12)",
    bd: "rgba(120,125,145,0.22)",
    Icon: AlertTriangle,
  };

  if (norm.includes("verifi") || norm === "clean" || norm === "success" || norm === "extracted" || norm === "reported") {
    cfg = { label: "Verified", fg: C.success, bg: C.successBg, bd: C.successBorder, Icon: CheckCircle2 };
  } else if (norm.includes("review") || norm.includes("warn") || norm === "needsreview") {
    cfg = { label: "Requires review", fg: C.warning, bg: C.warningBg, bd: C.warningBorder, Icon: AlertTriangle };
  } else if (norm.includes("fail") || norm.includes("flag") || norm.includes("crit")) {
    cfg = { label: "Failed", fg: C.danger, bg: C.dangerBg, bd: C.dangerBorder, Icon: XCircle };
  } else if (norm.includes("extract") || norm.includes("process") || norm === "pending") {
    cfg = { label: "Processing", fg: C.accent, bg: "rgba(91,99,232,0.14)", bd: "rgba(91,99,232,0.28)", Icon: Clock };
  } else if (norm.includes("incomplet") || norm === "uploaded") {
    cfg = { label: "Incomplete", fg: C.textSecondary, bg: "rgba(120,125,145,0.12)", bd: "rgba(120,125,145,0.22)", Icon: AlertTriangle };
  }

  const Icon = cfg.Icon;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "4px 10px",
        borderRadius: 8,
        background: cfg.bg,
        border: `1px solid ${cfg.bd}`,
        color: cfg.fg,
        fontSize: 12.5,
        fontWeight: 600,
        fontFamily: sans,
        whiteSpace: "nowrap",
      }}
    >
      <Icon size={13} strokeWidth={2.4} />
      {cfg.label}
    </span>
  );
}

export function SeverityTag({ level }: { level?: string }) {
  const norm = (level || "low").toLowerCase();
  const map: Record<string, { label: string; fg: string; bg: string; bd: string }> = {
    critical: { label: "CRITICAL", fg: C.danger, bg: C.dangerBg, bd: C.dangerBorder },
    high: { label: "HIGH", fg: C.danger, bg: C.dangerBg, bd: C.dangerBorder },
    medium: { label: "MEDIUM", fg: C.warning, bg: C.warningBg, bd: C.warningBorder },
    low: { label: "LOW", fg: C.textSecondary, bg: "rgba(120,125,145,0.12)", bd: "rgba(120,125,145,0.22)" },
  };
  const s = map[norm] || map.low;
  return (
    <span
      style={{
        fontSize: 11.5,
        fontWeight: 700,
        letterSpacing: 0.3,
        color: s.fg,
        background: s.bg,
        border: `1px solid ${s.bd}`,
        borderRadius: 6,
        padding: "3px 8px",
        fontFamily: sans,
        display: "inline-block",
      }}
    >
      {s.label}
    </span>
  );
}

export function MetricCard({
  label,
  value,
  sub,
  tone,
  icon: Icon,
}: {
  label: string;
  value: string | number;
  sub?: string;
  tone?: "success" | "warning" | "danger" | "neutral";
  icon?: any;
}) {
  const toneColor =
    tone === "success" ? C.success : tone === "warning" ? C.warning : tone === "danger" ? C.danger : C.text;
  return (
    <div style={glass({ padding: "18px 20px", flex: 1, minWidth: 0 })}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
        {Icon && (
          <div
            style={{
              width: 34,
              height: 34,
              borderRadius: "50%",
              background: "rgba(255,255,255,0.75)",
              border: `1px solid ${C.glassBorder}`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
          >
            <Icon size={16} color={C.primary} />
          </div>
        )}
        <div style={{ fontSize: 13, color: C.textSecondary, fontFamily: sans }}>{label}</div>
      </div>
      <div style={{ fontSize: 26, fontWeight: 800, color: toneColor, fontFamily: sans, lineHeight: 1.1 }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: 12.5, color: C.textTertiary, marginTop: 6, fontFamily: sans }}>{sub}</div>}
    </div>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-end",
        justifyContent: "space-between",
        marginBottom: 26,
        gap: 16,
        flexWrap: "wrap",
      }}
    >
      <div>
        {eyebrow && (
          <div style={{ fontSize: 13, color: C.accent, fontFamily: sans, fontWeight: 700, marginBottom: 6 }}>
            {eyebrow}
          </div>
        )}
        <h1 style={{ fontSize: 30, fontWeight: 800, color: C.text, fontFamily: sans, margin: 0 }}>{title}</h1>
        {description && (
          <p style={{ fontSize: 14.5, color: C.textSecondary, fontFamily: sans, margin: "8px 0 0", maxWidth: 620 }}>
            {description}
          </p>
        )}
      </div>
      {action}
    </div>
  );
}

export function PrimaryButton({
  children,
  onClick,
  icon: Icon,
  disabled,
  style,
  id,
}: {
  children: React.ReactNode;
  onClick?: (e?: any) => void;
  icon?: any;
  disabled?: boolean;
  style?: React.CSSProperties;
  id?: string;
}) {
  return (
    <button
      id={id}
      type="button"
      disabled={disabled}
      onClick={onClick}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 8,
        background: disabled
          ? "rgba(120,125,145,0.3)"
          : `linear-gradient(135deg, ${C.primary}, ${C.accent})`,
        color: "#fff",
        border: "none",
        borderRadius: 12,
        padding: "11px 18px",
        fontSize: 14,
        fontWeight: 700,
        fontFamily: sans,
        cursor: disabled ? "not-allowed" : "pointer",
        boxShadow: disabled ? "none" : "0 8px 20px rgba(91,99,232,0.35)",
        transition: "all 0.2s ease",
        ...style,
      }}
    >
      {Icon && <Icon size={15} />}
      {children}
    </button>
  );
}

export function SecondaryButton({
  children,
  onClick,
  icon: Icon,
  disabled,
  style,
  id,
}: {
  children: React.ReactNode;
  onClick?: (e?: any) => void;
  icon?: any;
  disabled?: boolean;
  style?: React.CSSProperties;
  id?: string;
}) {
  return (
    <button
      id={id}
      type="button"
      disabled={disabled}
      onClick={onClick}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 8,
        background: "rgba(255,255,255,0.6)",
        backdropFilter: "blur(10px)",
        color: C.text,
        border: `1px solid ${C.glassBorder}`,
        borderRadius: 10,
        padding: "10px 16px",
        fontSize: 13.5,
        fontWeight: 600,
        fontFamily: sans,
        cursor: disabled ? "not-allowed" : "pointer",
        transition: "all 0.2s ease",
        ...style,
      }}
    >
      {Icon && <Icon size={14} />}
      {children}
    </button>
  );
}

export function RiskGauge({ score }: { score: number }) {
  const safeScore = Math.max(0, Math.min(100, Math.round(score)));
  const color = safeScore < 30 ? C.success : safeScore < 60 ? C.warning : C.danger;
  const r = 46;
  const cc = 2 * Math.PI * r;
  const offset = cc - (safeScore / 100) * cc;
  return (
    <div style={{ position: "relative", width: 116, height: 116, flexShrink: 0 }}>
      <svg width="116" height="116" viewBox="0 0 116 116">
        <circle cx="58" cy="58" r={r} fill="none" stroke="rgba(120,125,160,0.18)" strokeWidth="10" />
        <circle
          cx="58"
          cy="58"
          r={r}
          fill="none"
          stroke={color}
          strokeWidth="10"
          strokeDasharray={cc}
          strokeDashoffset={offset}
          strokeLinecap="round"
          transform="rotate(-90 58 58)"
          style={{ transition: "stroke-dashoffset 0.8s cubic-bezier(0.4,0,0.2,1)" }}
        />
      </svg>
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div style={{ fontSize: 26, fontWeight: 800, color: C.text, fontFamily: sans, lineHeight: 1 }}>
          {safeScore}
        </div>
        <div style={{ fontSize: 11, color: C.textTertiary, fontFamily: sans, marginTop: 2 }}>risk / 100</div>
      </div>
    </div>
  );
}
