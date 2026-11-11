"use client";

import { useEffect, useState } from "react";
import {
  Building2,
  Users,
  Clock,
  Percent,
  Sliders,
  CheckCircle2,
  ShieldCheck,
  UserPlus,
  RefreshCw
} from "lucide-react";
import { ApiClient, Tenant, TenantMembership } from "@/lib/api";

export default function DashboardOverviewPage() {
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [members, setMembers] = useState<TenantMembership[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Add Member Modal State
  const [showAddMember, setShowAddMember] = useState(false);
  const [newEmail, setNewEmail] = useState("");
  const [newRole, setNewRole] = useState("FINANCE_MANAGER");
  const [addingMember, setAddingMember] = useState(false);
  const [modalError, setModalError] = useState<string | null>(null);

  const activeTenantId = typeof window !== "undefined" ? localStorage.getItem("finora_active_tenant_id") : null;
  const activeRole = typeof window !== "undefined" ? localStorage.getItem("finora_active_role") : "FINANCE_MANAGER";

  const loadData = async () => {
    if (!activeTenantId) return;
    setLoading(true);
    setError(null);
    try {
      const [tData, mData] = await Promise.all([
        ApiClient.getTenant(activeTenantId),
        ApiClient.listMembers(activeTenantId).catch(() => []),
      ]);
      setTenant(tData);
      setMembers(mData);
    } catch (err: any) {
      setError(err.message || "Failed to load tenant details.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [activeTenantId]);

  const handleAddMember = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeTenantId) return;
    setAddingMember(true);
    setModalError(null);
    try {
      await ApiClient.addMember(activeTenantId, newEmail, newRole);
      setShowAddMember(false);
      setNewEmail("");
      loadData();
    } catch (err: any) {
      setModalError(err.message || "Failed to add member.");
    } finally {
      setAddingMember(false);
    }
  };

  return (
    <div className="p-8 max-w-7xl mx-auto w-full space-y-8">
      {/* Top Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-border/40 pb-6">
        <div>
          <div className="flex items-center space-x-2">
            <h1 className="text-2xl font-bold text-white tracking-tight">
              {tenant?.name || "Financial Organization"}
            </h1>
            <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-950 text-emerald-400 border border-emerald-800 font-mono">
              Live Verified
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Tenant ID: <span className="font-mono text-slate-300">{activeTenantId}</span> • Slug: <span className="font-mono text-slate-300">{tenant?.slug}</span>
          </p>
        </div>

        <div className="flex items-center space-x-3">
          <button
            onClick={loadData}
            className="p-2 rounded-lg bg-surface border border-border text-slate-400 hover:text-white transition"
            title="Refresh details"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </button>
          {activeRole === "ADMIN" && (
            <button
              onClick={() => setShowAddMember(true)}
              className="px-4 py-2 rounded-lg bg-primary hover:bg-primary-dark text-white text-xs font-medium flex items-center space-x-1.5 transition shadow-sm"
            >
              <UserPlus className="h-3.5 w-3.5" />
              <span>Add Member</span>
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl border border-rose-800 bg-rose-950/40 text-rose-300 text-xs">
          {error}
        </div>
      )}

      {/* Configuration Metrics Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="p-5 rounded-xl border border-border/60 bg-surface/70">
          <div className="flex items-center justify-between text-slate-400 text-xs mb-2">
            <span>Settlement Cutoff</span>
            <Clock className="h-4 w-4 text-sky-400" />
          </div>
          <div className="text-xl font-bold text-white font-mono">
            {tenant?.settlement_cutoff_time || "23:00"} IST
          </div>
          <div className="text-[11px] text-slate-500 mt-1">Daily batch calculation boundary</div>
        </div>

        <div className="p-5 rounded-xl border border-border/60 bg-surface/70">
          <div className="flex items-center justify-between text-slate-400 text-xs mb-2">
            <span>Fee Tolerance (ε)</span>
            <Percent className="h-4 w-4 text-emerald-400" />
          </div>
          <div className="text-xl font-bold text-white font-mono">
            ₹{tenant?.fee_overcharge_tolerance || "0.05"}
          </div>
          <div className="text-[11px] text-slate-500 mt-1">Configurable sub-paisa tolerance</div>
        </div>

        <div className="p-5 rounded-xl border border-border/60 bg-surface/70">
          <div className="flex items-center justify-between text-slate-400 text-xs mb-2">
            <span>Knapsack Search Bound</span>
            <Sliders className="h-4 w-4 text-cyan-400" />
          </div>
          <div className="text-xl font-bold text-white font-mono">
            N ≤ {tenant?.max_knapsack_bound || 5} Batches
          </div>
          <div className="text-[11px] text-slate-500 mt-1">Never-force-match safety bound</div>
        </div>

        <div className="p-5 rounded-xl border border-border/60 bg-surface/70">
          <div className="flex items-center justify-between text-slate-400 text-xs mb-2">
            <span>Currency Ledger</span>
            <Building2 className="h-4 w-4 text-amber-400" />
          </div>
          <div className="text-xl font-bold text-white font-mono">
            {tenant?.default_currency || "INR"}
          </div>
          <div className="text-[11px] text-slate-500 mt-1">Arbitrary-precision Decimal</div>
        </div>
      </div>

      {/* Team Members & RBAC Section */}
      <div className="p-6 rounded-2xl border border-border/60 bg-surface/70">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center space-x-2">
            <Users className="h-4 w-4 text-sky-400" />
            <h2 className="text-base font-semibold text-white">Authorized Tenant Members</h2>
          </div>
          <span className="text-xs text-slate-400">{members.length} Users Enrolled</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-border/40 text-slate-400">
                <th className="py-2.5 px-3">User ID</th>
                <th className="py-2.5 px-3">Role</th>
                <th className="py-2.5 px-3">Default Tenant</th>
                <th className="py-2.5 px-3">Enrolled At</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/20 text-slate-300">
              {members.map((m) => (
                <tr key={m.id} className="hover:bg-surfaceLight/30 transition">
                  <td className="py-3 px-3 font-mono text-slate-200">{m.user_id}</td>
                  <td className="py-3 px-3">
                    <span
                      className={`inline-block px-2 py-0.5 rounded text-[10px] font-mono border ${
                        m.role === "ADMIN"
                          ? "bg-rose-950/60 text-rose-300 border-rose-800"
                          : m.role === "FINANCE_MANAGER"
                          ? "bg-sky-950/60 text-sky-300 border-sky-800"
                          : "bg-slate-800 text-slate-300 border-slate-700"
                      }`}
                    >
                      {m.role}
                    </span>
                  </td>
                  <td className="py-3 px-3">{m.is_default ? "Yes" : "No"}</td>
                  <td className="py-3 px-3 text-slate-400">
                    {m.created_at
                      ? new Date(m.created_at).toLocaleDateString("en-IN", {
                          day: "2-digit",
                          month: "short",
                          year: "numeric",
                        })
                      : "Recently"}
                  </td>
                </tr>
              ))}
              {members.length === 0 && (
                <tr>
                  <td colSpan={4} className="py-6 text-center text-slate-500">
                    No members enrolled or insufficient view permissions.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Add Member Modal */}
      {showAddMember && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-surface border border-border p-6 rounded-2xl w-full max-w-md shadow-2xl">
            <h3 className="text-base font-semibold text-white mb-1">Add Team Member</h3>
            <p className="text-xs text-slate-400 mb-4">
              Grant a registered user role-based access to this tenant.
            </p>

            {modalError && (
              <div className="p-3 mb-4 rounded-lg border border-rose-800 bg-rose-950/40 text-rose-300 text-xs">
                {modalError}
              </div>
            )}

            <form onSubmit={handleAddMember} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">User Email</label>
                <input
                  type="email"
                  required
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                  placeholder="colleague@brand.com"
                  className="w-full px-3 py-2 rounded-lg bg-surfaceLight border border-border text-white text-xs focus:outline-none focus:border-primary"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Assigned Role</label>
                <select
                  value={newRole}
                  onChange={(e) => setNewRole(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-surfaceLight border border-border text-white text-xs focus:outline-none focus:border-primary"
                >
                  <option value="ADMIN">ADMIN (Full Governance)</option>
                  <option value="FINANCE_MANAGER">FINANCE_MANAGER (Reconciliation & Claims)</option>
                  <option value="AUDITOR">AUDITOR (Read-Only Inspection)</option>
                </select>
              </div>

              <div className="flex justify-end space-x-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowAddMember(false)}
                  className="px-4 py-2 rounded-lg bg-surfaceLight text-slate-400 hover:text-white text-xs"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={addingMember}
                  className="px-4 py-2 rounded-lg bg-primary hover:bg-primary-dark text-white text-xs font-medium"
                >
                  {addingMember ? "Adding..." : "Confirm & Enroll"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
