const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export interface User {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  is_superuser: boolean;
}

export interface Tenant {
  id: string;
  name: string;
  slug: string;
  default_currency: string;
  settlement_cutoff_time: string;
  fee_overcharge_tolerance: string;
  max_knapsack_bound: number;
  is_active: boolean;
}

export interface TenantMembership {
  id: string;
  tenant_id: string;
  user_id: string;
  role: "ADMIN" | "FINANCE_MANAGER" | "AUDITOR";
  is_default: boolean;
  created_at?: string;
  tenant?: Tenant;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
  active_tenant_id?: string;
  active_role?: string;
  memberships: TenantMembership[];
}

// ---------------------------------------------------------------------------
// Dashboard Interfaces
// ---------------------------------------------------------------------------

export interface FlowStageSummary {
  total_count: number;
  total_amount: string | number;
  matched_count: number;
  matched_amount: string | number;
  unmatched_count: number;
  unmatched_amount: string | number;
}

export interface ThreeWayFlowOverview {
  shopify_orders: FlowStageSummary;
  razorpay_payments: FlowStageSummary;
  gateway_settlements: FlowStageSummary;
  hdfc_bank_credits: FlowStageSummary;
}

export interface LeakageTrendItem {
  date: string;
  reconciled_amount: string | number;
  unmatched_amount: string | number;
}

export interface CategoryLeakageSummary {
  category: string;
  display_name: string;
  count: number;
  total_amount: string | number;
}

export interface SeverityLeakageSummary {
  severity: "HIGH" | "MEDIUM" | "LOW";
  count: number;
  total_amount: string | number;
}

export interface DashboardOverview {
  tenant_id: string;
  tenant_name: string;
  currency: string;
  total_orders_count: number;
  total_orders_amount: string | number;
  total_captured_count: number;
  total_captured_amount: string | number;
  total_settlements_count: number;
  total_settled_amount: string | number;
  total_bank_credits_count: number;
  total_bank_credited_amount: string | number;
  reconciled_amount: string | number;
  unmatched_amount: string | number;
  reconciliation_accuracy_percentage: string | number;
  total_detected_leakage: string | number;
  leakage_findings_count: number;
  pending_review_count: number;
  latest_run_id?: string;
  latest_run_number?: number;
  latest_run_status?: string;
  latest_run_timestamp?: string;
  flow: ThreeWayFlowOverview;
  trends: LeakageTrendItem[];
  leakage_by_category: CategoryLeakageSummary[];
  leakage_by_severity: SeverityLeakageSummary[];
}

export interface LeakageFinding {
  id: string;
  finding_id: string;
  category: "MISSING_SETTLEMENT" | "UNCREDITED_SETTLEMENT" | "FEE_OVERCHARGE" | "DUPLICATE_OR_EXCESS_REFUND";
  title: string;
  expected_amount: string | number;
  actual_amount: string | number;
  difference: string | number;
  severity: "HIGH" | "MEDIUM" | "LOW";
  detection_date: string;
  evidence_references: Record<string, any>;
  review_status: string;
  match_id?: string;
  entity_type?: string;
  entity_id?: string;
}

export interface LeakageFindingsResponse {
  total_findings: number;
  total_leakage_amount: string | number;
  high_severity_count: number;
  medium_severity_count: number;
  low_severity_count: number;
  findings: LeakageFinding[];
}

export interface ReviewQueueCandidate {
  id: string;
  reference: string;
  amount: string | number;
  date?: string;
  score?: string | number;
}

export interface ReviewQueueItem {
  match_id: string;
  run_id: string;
  run_number: number;
  match_type: string;
  classification: string;
  pass_number: number;
  confidence_score: string | number;
  source_amount: string | number;
  target_amount: string | number;
  allocated_amount: string | number;
  discrepancy_amount: string | number;
  fee_discrepancy: string | number;
  explanation: string;
  evidence_metadata?: Record<string, any>;
  review_status: string;
  reviewed_by_user_id?: string;
  reviewed_at?: string;
  review_action?: string;
  review_notes?: string;
  created_at: string;
  candidates: ReviewQueueCandidate[];
}

export interface ReviewQueueResponse {
  total_pending: number;
  items: ReviewQueueItem[];
}

export interface FeeInstrumentTier {
  instrument_type: string;
  percentage_rate: string | number;
  fixed_fee_per_txn: string | number;
  transactions_evaluated: number;
  gross_volume: string | number;
  actual_gateway_fees: string | number;
  contractual_expected_fees: string | number;
  variance: string | number;
}

export interface FeeAnalyticsResponse {
  active_contract?: any;
  contract_version: number;
  gst_rate: string | number;
  total_gross_volume: string | number;
  total_reported_fees: string | number;
  total_contractual_fees: string | number;
  total_fee_drift: string | number;
  total_fee_overcharges: string | number;
  tiers: FeeInstrumentTier[];
}

export interface AIInvestigationStatus {
  provider: string;
  status: string;
  is_configured: boolean;
  model_version: string;
  investigations_count: number;
  message: string;
  recent_investigations: any[];
}

export interface AuditLogItem {
  id: string;
  action: string;
  target_entity_type: string;
  target_entity_id?: string;
  user_email?: string;
  user_rationale?: string;
  ip_address?: string;
  performed_at: string;
}

export interface AuditLogsResponse {
  total_logs: number;
  logs: AuditLogItem[];
}

export interface ReconciliationRun {
  id: string;
  tenant_id: string;
  run_number: number;
  status: string;
  is_active: boolean;
  total_orders_evaluated: number;
  total_payments_evaluated: number;
  total_settlements_evaluated: number;
  total_bank_transactions_evaluated: number;
  matched_orders_count: number;
  matched_payments_count: number;
  matched_settlements_count: number;
  matched_bank_txs_count: number;
  unmatched_orders_count: number;
  unmatched_payments_count: number;
  unmatched_settlements_count: number;
  unmatched_bank_txs_count: number;
  ambiguous_matches_count: number;
  unresolved_count: number;
  total_order_amount: string | number;
  total_captured_amount: string | number;
  total_settled_amount: string | number;
  total_matched_bank_amount: string | number;
  total_discrepancy_amount: string | number;
  total_fee_drift_amount: string | number;
  duration_ms?: number;
  error_message?: string;
  created_at: string;
  completed_at?: string;
}

export class ApiClient {
  private static getToken(): string | null {
    if (typeof window === "undefined") return null;
    return localStorage.getItem("finora_access_token");
  }

  private static getActiveTenantId(): string | null {
    if (typeof window === "undefined") return null;
    return localStorage.getItem("finora_active_tenant_id");
  }

  public static setSession(tokenResp: TokenResponse): void {
    if (typeof window === "undefined") return;
    localStorage.setItem("finora_access_token", tokenResp.access_token);
    if (tokenResp.active_tenant_id) {
      localStorage.setItem("finora_active_tenant_id", tokenResp.active_tenant_id);
    }
    if (tokenResp.active_role) {
      localStorage.setItem("finora_active_role", tokenResp.active_role);
    }
    localStorage.setItem("finora_user", JSON.stringify(tokenResp.user));
  }

  public static clearSession(): void {
    if (typeof window === "undefined") return;
    localStorage.removeItem("finora_access_token");
    localStorage.removeItem("finora_active_tenant_id");
    localStorage.removeItem("finora_active_role");
    localStorage.removeItem("finora_user");
  }

  private static async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const token = this.getToken();
    const activeTenantId = this.getActiveTenantId();

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(options.headers as Record<string, string>),
    };

    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
    if (activeTenantId) {
      headers["X-Tenant-ID"] = activeTenantId;
    }

    const res = await fetch(`${API_BASE_URL}${endpoint}`, {
      ...options,
      headers,
    });

    if (!res.ok) {
      let errorMsg = `API Error (${res.status})`;
      try {
        const errorData = await res.json();
        errorMsg = errorData.detail || errorMsg;
      } catch {}
      throw new Error(errorMsg);
    }

    return res.json() as Promise<T>;
  }

  // Auth Endpoints
  public static async login(credentials: { email: string; password: string }): Promise<TokenResponse> {
    const resp = await this.request<TokenResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify(credentials),
    });
    this.setSession(resp);
    return resp;
  }

  public static async register(data: {
    email: string;
    password: string;
    full_name: string;
    tenant_name: string;
    tenant_slug: string;
  }): Promise<TokenResponse> {
    const resp = await this.request<TokenResponse>("/auth/register", {
      method: "POST",
      body: JSON.stringify(data),
    });
    this.setSession(resp);
    return resp;
  }

  public static async getMe(): Promise<User> {
    return this.request<User>("/auth/me");
  }

  // Tenant Endpoints
  public static async listTenants(): Promise<TenantMembership[]> {
    return this.request<TenantMembership[]>("/tenants/");
  }

  public static async getTenant(tenantId: string): Promise<Tenant> {
    return this.request<Tenant>(`/tenants/${tenantId}`);
  }

  public static async updateTenant(tenantId: string, data: Partial<Tenant>): Promise<Tenant> {
    return this.request<Tenant>(`/tenants/${tenantId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  }

  public static async listMembers(tenantId: string): Promise<TenantMembership[]> {
    return this.request<TenantMembership[]>(`/tenants/${tenantId}/members`);
  }

  public static async addMember(tenantId: string, email: string, role: string): Promise<TenantMembership> {
    return this.request<TenantMembership>(`/tenants/${tenantId}/members`, {
      method: "POST",
      body: JSON.stringify({ email, role }),
    });
  }

  // ---------------------------------------------------------------------------
  // Dashboard Endpoints
  // ---------------------------------------------------------------------------

  public static async getDashboardOverview(): Promise<DashboardOverview> {
    return this.request<DashboardOverview>("/dashboard/overview");
  }

  public static async getLeakageFindings(): Promise<LeakageFindingsResponse> {
    return this.request<LeakageFindingsResponse>("/dashboard/leakage-findings");
  }

  public static async getReviewQueue(statusFilter?: string): Promise<ReviewQueueResponse> {
    const query = statusFilter ? `?status_filter=${encodeURIComponent(statusFilter)}` : "";
    return this.request<ReviewQueueResponse>(`/dashboard/review-queue${query}`);
  }

  public static async getFeeAnalytics(): Promise<FeeAnalyticsResponse> {
    return this.request<FeeAnalyticsResponse>("/dashboard/fee-analytics");
  }

  public static async getAIInvestigations(): Promise<AIInvestigationStatus> {
    return this.request<AIInvestigationStatus>("/dashboard/ai-investigations");
  }

  public static async getAuditLogs(limit: number = 50, offset: number = 0): Promise<AuditLogsResponse> {
    return this.request<AuditLogsResponse>(`/dashboard/audit-logs?limit=${limit}&offset=${offset}`);
  }

  // ---------------------------------------------------------------------------
  // Reconciliation Endpoints
  // ---------------------------------------------------------------------------

  public static async listReconciliationRuns(): Promise<ReconciliationRun[]> {
    return this.request<ReconciliationRun[]>("/reconciliation/runs");
  }

  public static async getReconciliationRun(runId: string): Promise<ReconciliationRun> {
    return this.request<ReconciliationRun>(`/reconciliation/runs/${runId}`);
  }

  public static async triggerReconciliationRun(params?: any): Promise<ReconciliationRun> {
    return this.request<ReconciliationRun>("/reconciliation/runs", {
      method: "POST",
      body: JSON.stringify({ parameters: params || {} }),
    });
  }

  public static async resolveMatch(
    matchId: string,
    action: "APPROVE" | "REJECT" | "MANUAL_ALLOCATE",
    notes?: string,
    targetEntityId?: string,
    allocatedAmount?: string
  ): Promise<any> {
    return this.request<any>(`/reconciliation/matches/${matchId}/resolve`, {
      method: "POST",
      body: JSON.stringify({
        action,
        notes: notes || "Review decision registered via Finora Review Workspace",
        target_entity_id: targetEntityId,
        allocated_amount: allocatedAmount,
      }),
    });
  }

  // ---------------------------------------------------------------------------
  // Ingestion & Canonical Explorer Endpoints
  // ---------------------------------------------------------------------------

  public static async listCanonicalOrders(limit: number = 50, offset: number = 0): Promise<any[]> {
    return this.request<any[]>(`/ingestion/orders?limit=${limit}&offset=${offset}`);
  }

  public static async listCanonicalPayments(limit: number = 50, offset: number = 0): Promise<any[]> {
    return this.request<any[]>(`/ingestion/payments?limit=${limit}&offset=${offset}`);
  }

  public static async listCanonicalSettlements(limit: number = 50, offset: number = 0): Promise<any[]> {
    return this.request<any[]>(`/ingestion/settlements?limit=${limit}&offset=${offset}`);
  }

  public static async listCanonicalBankTransactions(limit: number = 50, offset: number = 0): Promise<any[]> {
    return this.request<any[]>(`/ingestion/bank-transactions?limit=${limit}&offset=${offset}`);
  }

  // System Health
  public static async checkHealth(): Promise<{ status: string; service: string; database: string }> {
    const rootUrl = API_BASE_URL.replace("/api/v1", "");
    const res = await fetch(`${rootUrl}/health`);
    return res.json();
  }
}
