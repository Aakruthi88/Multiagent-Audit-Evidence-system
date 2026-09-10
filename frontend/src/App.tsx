import React, { useState } from 'react';
import { Navbar } from './components/Navbar';
import { BundleUpload } from './pages/BundleUpload';
import { Dashboard } from './pages/Dashboard';
import { BundleDetail } from './pages/BundleDetail';
import { AskQuery } from './pages/AskQuery';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'upload' | 'dashboard' | 'detail' | 'ask'>('dashboard');
  const [selectedBundleId, setSelectedBundleId] = useState<string | undefined>(undefined);

  const handleUploadSuccess = (bundleId: string) => {
    setSelectedBundleId(bundleId);
    setActiveTab('detail');
  };

  const handleSelectBundle = (bundleId: string) => {
    setSelectedBundleId(bundleId);
    setActiveTab('detail');
  };

  return (
    <div className="app-container">
      <Navbar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        selectedBundleId={selectedBundleId}
      />

      <main>
        {activeTab === 'upload' && (
          <BundleUpload onSuccess={handleUploadSuccess} />
        )}

        {activeTab === 'dashboard' && (
          <Dashboard onSelectBundle={handleSelectBundle} />
        )}

        {activeTab === 'ask' && (
          <AskQuery />
        )}

        {activeTab === 'detail' && selectedBundleId && (
          <BundleDetail
            bundleId={selectedBundleId}
            onBack={() => setActiveTab('dashboard')}
          />
        )}
      </main>
    </div>
  );
};

export default App;