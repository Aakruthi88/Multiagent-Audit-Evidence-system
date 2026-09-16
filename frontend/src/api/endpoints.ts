import { apiClient } from './client';
import { AuditBundle, DocumentItem, AgentLog, VerificationSummary, VerificationRun } from '../types';
import { AuthUser, LoginCredentials, TokenResponse } from '../types/auth';

// ── Authentication API ─────────────────────────────────────────────────────────

export const loginUser = async (credentials: LoginCredentials): Promise<TokenResponse> => {
  const response = await apiClient.post<TokenResponse>('/auth/login', credentials);
  return response.data;
};

export const getCurrentUser = async (): Promise<AuthUser> => {
  const response = await apiClient.get<AuthUser>('/auth/me');
  return response.data;
};

// ── Bundles & Documents API ───────────────────────────────────────────────────

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

// ── NL Query via /run endpoint ─────────────────────────────────────────────────

export const runQuery = async (query: string, bundleId?: string): Promise<any> => {
  const response = await apiClient.post<any>('/run', { query, bundle_id: bundleId || undefined });
  return response.data;
};

export const runAction = async (bundleId: string, action: string): Promise<any> => {
  const response = await apiClient.post<any>('/run', { bundle_id: bundleId, action });
  return response.data;
};

// ── Phase 4: Audit Workpaper Export & Business Impact ──────────────────────────

export const exportWorkpaper = async (bundleId: string, txnRef?: string): Promise<void> => {
  const response = await apiClient.get(`/bundles/${bundleId}/export-workpaper`, {
    responseType: 'blob',
  });
  
  const blob = new Blob([response.data], { type: 'application/pdf' });
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.setAttribute('download', `audit_workpaper_${txnRef || bundleId}.pdf`);
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
};

export const getImpactMetrics = async (): Promise<any> => {
  const response = await apiClient.get<any>('/bundles/metrics/impact');
  return response.data;
};
