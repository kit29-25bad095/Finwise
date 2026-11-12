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
  role: string;
  is_default: boolean;
  tenant: Tenant;
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export class ApiClient {
  static getAuthHeaders(): HeadersInit {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (typeof window !== "undefined") {
      const token = localStorage.getItem("finora_access_token");
      if (token && token !== "demo_token_authenticated") {
        headers["Authorization"] = `Bearer ${token}`;
      }
      const tenantId = localStorage.getItem("finora_active_tenant_id");
      if (tenantId) {
        headers["X-Tenant-ID"] = tenantId;
      }
    }
    return headers;
  }

  static async checkHealth(): Promise<{ status: string; database: string }> {
    try {
      const res = await fetch("http://localhost:8000/health");
      if (!res.ok) throw new Error("Health check failed");
      const data = await res.json();
      return {
        status: data.status || "ONLINE",
        database: data.database || "HEALTHY",
      };
    } catch {
      return { status: "ONLINE", database: "LOCAL" };
    }
  }

  static async login(credentials: { email: string; password: string }): Promise<any> {
    const formData = new URLSearchParams();
    formData.append("username", credentials.email);
    formData.append("password", credentials.password);

    const res = await fetch(`${API_BASE_URL}/auth/token`, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: formData.toString(),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Invalid email or passphrase");
    }

    const data = await res.json();
    if (typeof window !== "undefined") {
      localStorage.setItem("finora_access_token", data.access_token);
      localStorage.setItem("finora_user", JSON.stringify(data.user));
    }
    return data;
  }

  static async register(payload: {
    email: string;
    password: string;
    full_name: string;
    tenant_name: string;
    tenant_slug: string;
  }): Promise<any> {
    const res = await fetch(`${API_BASE_URL}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Registration failed");
    }

    const data = await res.json();
    if (typeof window !== "undefined" && data.access_token) {
      localStorage.setItem("finora_access_token", data.access_token);
      localStorage.setItem("finora_user", JSON.stringify(data.user));
    }
    return data;
  }

  static async listTenants(): Promise<TenantMembership[]> {
    const headers = this.getAuthHeaders();
    const res = await fetch(`${API_BASE_URL}/tenants/me`, { headers });
    if (!res.ok) {
      throw new Error("Failed to fetch tenants");
    }
    return res.json();
  }

  static clearSession(): void {
    if (typeof window !== "undefined") {
      localStorage.removeItem("finora_access_token");
      localStorage.removeItem("finora_user");
      localStorage.removeItem("finora_active_tenant_id");
      localStorage.removeItem("finora_active_role");
    }
  }
}
