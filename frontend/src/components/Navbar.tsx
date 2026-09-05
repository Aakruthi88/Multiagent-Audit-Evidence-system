import React from 'react';
import { ShieldCheck, Upload, LayoutDashboard, FileText } from 'lucide-react';

interface NavbarProps {
  activeTab: 'upload' | 'dashboard' | 'detail';
  setActiveTab: (tab: 'upload' | 'dashboard' | 'detail') => void;
  selectedBundleId?: string;
}

export const Navbar: React.FC<NavbarProps> = ({ activeTab, setActiveTab, selectedBundleId }) => {
  return (
    <nav className="navbar">
      <div className="brand">
        <div className="brand-icon">
          <ShieldCheck size={24} />
        </div>
        <div>
          <div className="brand-title">Audit Evidence Assistant</div>
          <div className="brand-subtitle">Deloitte Capstone · Day 1 Engine</div>
        </div>
      </div>

      <div className="nav-links">
        <button
          className={`nav-btn ${activeTab === 'upload' ? 'active' : ''}`}
          onClick={() => setActiveTab('upload')}
        >
          <Upload size={18} />
          New Upload
        </button>

        <button
          className={`nav-btn ${activeTab === 'dashboard' ? 'active' : ''}`}
          onClick={() => setActiveTab('dashboard')}
        >
          <LayoutDashboard size={18} />
          Dashboard
        </button>

        {selectedBundleId && (
          <button
            className={`nav-btn ${activeTab === 'detail' ? 'active' : ''}`}
            onClick={() => setActiveTab('detail')}
          >
            <FileText size={18} />
            Bundle Detail
          </button>
        )}
      </div>
    </nav>
  );
};
