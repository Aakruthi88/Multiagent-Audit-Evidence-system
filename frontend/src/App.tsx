import React, { useState } from "react";
import { Navbar, TabKey } from "./components/Navbar";
import { Home } from "./pages/Home";
import { Dashboard } from "./pages/Dashboard";
import { Bundles } from "./pages/Bundles";
import { BundleUpload } from "./pages/BundleUpload";
import { BundleDetail } from "./pages/BundleDetail";
import { AskQuery } from "./pages/AskQuery";
import { Backdrop, FontImport, sans } from "./theme";

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabKey>("home");
  const [selectedBundleId, setSelectedBundleId] = useState<string | undefined>(undefined);

  const handleUploadSuccess = (bundleId: string) => {
    setSelectedBundleId(bundleId);
    setActiveTab("detail");
  };

  const handleSelectBundle = (bundleId: string) => {
    setSelectedBundleId(bundleId);
    setActiveTab("detail");
  };

  return (
    <div style={{ position: "relative", minHeight: "100vh", fontFamily: sans }}>
      <FontImport />
      <Backdrop />
      <div style={{ position: "relative", zIndex: 1, padding: "16px 24px 48px", minHeight: "100vh" }}>
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

            {activeTab === "detail" && selectedBundleId && (
              <BundleDetail
                bundleId={selectedBundleId}
                onBack={() => setActiveTab("dashboard")}
              />
            )}
          </main>
        </div>
      </div>
    </div>
  );
};

export default App;