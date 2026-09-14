import React, { useState } from "react";
import { UploadDropzone } from "../components/UploadDropzone";
import { createBundle } from "../api/endpoints";
import { DocType } from "../types";
import { C, sans, glass } from "../theme";
import { AlertOctagon } from "lucide-react";

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
    formData.append("txn_reference", txnRef);

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
      const msg = err.response?.data?.detail || err.message || "Failed to upload audit bundle";
      setError(msg);
    }
  };

  return (
    <div>
      {error && (
        <div
          style={{
            ...glass({
              background: C.dangerBg,
              borderColor: C.dangerBorder,
              padding: "16px 20px",
              marginBottom: 20,
              display: "flex",
              alignItems: "center",
              gap: 12,
              color: C.danger,
              fontSize: 14,
              fontFamily: sans,
              fontWeight: 600,
            }),
          }}
        >
          <AlertOctagon size={18} color={C.danger} />
          <div>
            <strong>Upload Error:</strong> {error}
          </div>
        </div>
      )}
      <UploadDropzone onUploadSubmit={handleUploadSubmit} isLoading={isLoading} />
    </div>
  );
};
