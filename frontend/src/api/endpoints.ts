import { apiClient } from './client';
import { AuditBundle, DocumentItem, AgentLog, VerificationSummary, VerificationRun } from '../types';

export const createBundle = async (formData: FormData): Promise<AuditBundle> => {
  const response = await apiClient.post<AuditBundle>('/bundles', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
  return response.data;
};

export const getBundles = async (): Promise<AuditBundle[]> => {
  const response = await apiClient.get<AuditBundle[]>('/bundles');
  return response.data;
};

export const getBundle = async (bundleId: string): Promise<AuditBundle> => {
  const response = await apiClient.get<AuditBundle>(`/bundles/${bundleId}`);
  return response.data;
};

export const getBundleStatus = async (bundleId: string): Promise<{ bundle_id: string; status: string }> => {
  const response = await apiClient.get<{ bundle_id: string; status: string }>(`/bundles/${bundleId}/status`);
  return response.data;
};

export const getDocumentDetail = async (documentId: string): Promise<DocumentItem> => {
  const response = await apiClient.get<DocumentItem>(`/documents/${documentId}`);
  return response.data;
};

export const getBundleTrace = async (bundleId: string): Promise<AgentLog[]> => {
  const response = await apiClient.get<AgentLog[]>(`/bundles/${bundleId}/trace`);
  return response.data;
};

// ── Verification API ───────────────────────────────────────────────────────────

export const triggerVerification = async (bundleId: string): Promise<VerificationSummary> => {
  const response = await apiClient.post<VerificationSummary>(`/verification/run/${bundleId}`);
  return response.data;
};

export const getLatestVerificationRun = async (bundleId: string): Promise<VerificationRun> => {
  const response = await apiClient.get<VerificationRun>(`/verification/bundle/${bundleId}/latest`);
  return response.data;
};

export const getVerificationRun = async (runId: string): Promise<VerificationRun> => {
  const response = await apiClient.get<VerificationRun>(`/verification/${runId}`);
  return response.data;
};

