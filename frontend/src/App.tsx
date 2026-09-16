import React, { useState } from "react";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { Navbar, TabKey } from "./components/Navbar";
import { Login } from "./pages/Login";
import { Signup } from "./pages/Signup";
import { Home } from "./pages/Home";
import { Dashboard } from "./pages/Dashboard";
import { Bundles } from "./pages/Bundles";
import { BundleUpload } from "./pages/BundleUpload";
import { BundleDetail } from "./pages/BundleDetail";
import { AskQuery } from "./pages/AskQuery";
import { UsersManagement } from "./pages/UsersManagement";
import { Backdrop, FontImport, sans, C } from "./theme";

const AppContent: React.FC = () => {
  const { isAuthenticated, isLoading } = useAuth();
  const [authMode, setAuthMode] = useState<"login" | "signup">("login");

  const [signupSuccessNotice, setSignupSuccessNotice] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("dashboard");
  const [selectedBundleId, setSelectedBundleId] = useState<string | undefined>(undefined);

  const handleUploadSuccess = (bundleId: string) => {
    setSelectedBundleId(bundleId);
    setActiveTab("detail");
  };

  const handleSelectBundle = (bundleId: string) => {
    setSelectedBundleId(bundleId);
    setActiveTab("detail");
  };

  const handleSignupSuccess = (createdEmail: string) => {
    setSignupSuccessNotice(`Account created for ${createdEmail}! Please sign in with your password.`);
    setAuthMode("login");
  };

  // Loading spinner during initial token verification
  if (isLoading) {
    return (
      <div
        style={{
          minHeight: "100vh",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: sans,
          gap: 16,
        }}
      >
        <div
          style={{
            width: 36,
            height: 36,
            border: `3px solid rgba(91,99,232,0.25)`,
            borderTopColor: C.accent,
            borderRadius: "50%",
            animation: "spin 0.8s linear infinite",
          }}
        />
        <div style={{ fontSize: 14, fontWeight: 600, color: C.textSecondary }}>
          Authenticating secure audit session...
        </div>
      </div>
    );
  }

  // Route Protection: If not authenticated, render Login or Signup page only
  if (!isAuthenticated) {
    return (
      <div style={{ maxWidth: 1240, margin: "0 auto" }}>
        {authMode === "signup" ? (
          <Signup
            onSignupSuccess={handleSignupSuccess}
            onNavigateToLogin={() => {
              setSignupSuccessNotice(null);
              setAuthMode("login");
            }}
          />
        ) : (
          <Login
            onLoginSuccess={() => setActiveTab("dashboard")}
            onNavigateToSignup={() => {
              setSignupSuccessNotice(null);
              setAuthMode("signup");
            }}
            successNotice={signupSuccessNotice}
          />
        )}
      </div>
    );
  }

  // Authenticated Protected Audit Workspace
  return (
    <div style={{ maxWidth: 1240, margin: "0 auto" }}>
      <Navbar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        selectedBundleId={selectedBundleId}
      />

      <main style={{ paddingBottom: 40 }}>
        {activeTab === "home" && (
          <Home onNavigate={setActiveTab} />
        )}

        {activeTab === "dashboard" && (
          <Dashboard
            onSelectBundle={handleSelectBundle}
            onNewUpload={() => setActiveTab("upload")}
          />
        )}

        {activeTab === "upload" && (
          <BundleUpload onSuccess={handleUploadSuccess} />
        )}

        {activeTab === "bundles" && (
          <Bundles
            onSelectBundle={handleSelectBundle}
            onNewUpload={() => setActiveTab("upload")}
          />
        )}

        {activeTab === "ask" && (
          <AskQuery />
        )}

        {activeTab === "users" && (
          <UsersManagement />
        )}

        {activeTab === "detail" && selectedBundleId && (
          <BundleDetail
            bundleId={selectedBundleId}
            onBack={() => setActiveTab("dashboard")}
          />
        )}
      </main>
    </div>
  );
};

export const App: React.FC = () => {
  return (
    <AuthProvider>
      <div style={{ position: "relative", minHeight: "100vh", fontFamily: sans }}>
        <FontImport />
        <Backdrop />
        <div style={{ position: "relative", zIndex: 1, padding: "16px 24px 48px", minHeight: "100vh" }}>
          <AppContent />
        </div>
      </div>
    </AuthProvider>
  );
};

export default App;