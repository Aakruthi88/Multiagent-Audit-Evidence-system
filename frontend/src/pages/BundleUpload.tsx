import React, { useState } from 'react';
import { UploadDropzone } from '../components/UploadDropzone';
import { createBundle } from '../api/endpoints';
import { DocType } from '../types';

interface BundleUploadProps {
  onSuccess: (bundleId: string) => void;
}

export const BundleUpload: React.FC<BundleUploadProps> = ({ onSuccess }) => {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleUploadSubmit = async (txnRef: string, files: Record<DocType, File | null>) => {
    setIsLoading(true);
    setError(null);

    const formData = new FormData();
    formData.append('txn_reference', txnRef);

    Object.entries(files).forEach(([type, file]) => {
      if (file) {
        formData.append(type, file);
      }
    });

    try {
      const created = await createBundle(formData);
      setIsLoading(false);
      onSuccess(created.bundle_id);
    } catch (err: any) {
      setIsLoading(false);
      const msg = err.response?.data?.detail || err.message || 'Failed to upload audit bundle';
      setError(msg);
    }
  };

  return (
    <div>
      {error && (
        <div
          style={{
            background: 'rgba(239, 68, 68, 0.1)',
            border: '1px solid rgba(239, 68, 68, 0.3)',
            color: '#f87171',
            padding: 16,
            borderRadius: 'var(--radius-md)',
            marginBottom: 24,
            fontSize: '0.9rem',
          }}
        >
          <strong>Upload Error:</strong> {error}
        </div>
      )}
      <UploadDropzone onUploadSubmit={handleUploadSubmit} isLoading={isLoading} />
    </div>
  );
};
