export type DocType = 'purchase_order' | 'invoice' | 'grn' | 'bank_statement';

export interface DocumentItem {
  document_id: string;
  bundle_id: string;
  doc_type: DocType;
  file_path: string;
  file_hash: string;
  extraction_status: 'pending' | 'success' | 'low_confidence' | 'failed';
  extraction_confidence?: number;
  extraction_model?: string;
  uploaded_at: string;
  raw_text?: string;
  extracted_data?: Record<string, any>;
}

export interface AuditBundle {
  bundle_id: string;
  txn_reference: string;
  status: 'uploaded' | 'extracting' | 'extracted' | 'verifying' | 'investigating' | 'reported' | 'failed';
  created_at: string;
  updated_at: string;
  documents: DocumentItem[];
  extracted_summary?: Record<string, any>;
}

export interface AgentLog {
  log_id: string;
  run_id?: string;
  bundle_id?: string;
  agent_name: string;
  input_snapshot?: Record<string, any>;
  output_snapshot?: Record<string, any>;
  model_used?: string;
  tokens_used?: number;
  latency_ms?: number;
  status?: string;
  error_message?: string;
  created_at: string;
}

export type CheckStatus = 'pass' | 'warning' | 'fail' | 'not_applicable';
export type Severity = 'low' | 'medium' | 'high' | 'critical';
export type VerificationStatus = 'clean' | 'flagged' | 'critical' | 'incomplete';

export interface VerificationCheck {
  check_id: string;
  check_type: string;
  status: CheckStatus;
  expected_value?: string;
  actual_value?: string;
  variance?: string;
  severity?: Severity;
  explanation: string;
}

export interface Discrepancy {
  discrepancy_id: string;
  check_id?: string;
  category: string;
  severity: Severity;
  description: string;
  recommended_action?: string;
  resolved: boolean;
}

export interface VerificationRun {
  run_id: string;
  bundle_id: string;
  started_at: string;
  completed_at?: string;
  overall_status?: VerificationStatus;
  overall_risk_score?: string;
  rules_version: string;
  checks: VerificationCheck[];
  discrepancies: Discrepancy[];
}

export interface VerificationSummary {
  bundle_id: string;
  run_id?: string;
  overall_status?: VerificationStatus;
  overall_risk_score?: number;
  total_checks: number;
  total_discrepancies: number;
  critical_count: number;
  high_count: number;
  needs_investigation: boolean;
  message: string;
}

