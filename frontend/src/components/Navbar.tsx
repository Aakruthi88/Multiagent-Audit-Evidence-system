import React from 'react';
import { ShieldCheck, Upload, LayoutDashboard, FileText, MessageSquare } from 'lucide-react';

interface NavbarProps {
  activeTab: 'upload' | 'dashboard' | 'detail' | 'ask';
  setActiveTab: (tab: 'upload' | 'dashboard' | 'detail' | 'ask') => void;
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
          <div className="brand-subtitle">Deloitte Capstone Agentic Engine</div>
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

        <button
          className={`nav-btn ${activeTab === 'ask' ? 'active' : ''}`}
          onClick={() => setActiveTab('ask')}
          style={{
            background: activeTab === 'ask' ? 'rgba(59, 130, 246, 0.25)' : undefined,
            border: activeTab === 'ask' ? '1px solid #3b82f6' : undefined
          }}
        >
          <MessageSquare size={18} />
          Ask Documents
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