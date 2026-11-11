"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Sidebar } from "@/components/shell/Sidebar";
import { ApiClient, User, TenantMembership } from "@/lib/api";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [memberships, setMemberships] = useState<TenantMembership[]>([]);
  const [activeTenantId, setActiveTenantId] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    const token = localStorage.getItem("finora_access_token");
    const rawUser = localStorage.getItem("finora_user");
    const currentTenant = localStorage.getItem("finora_active_tenant_id");

    if (rawUser) {
      try {
        setUser(JSON.parse(rawUser));
      } catch {}
    }

    if (currentTenant) {
      setActiveTenantId(currentTenant);
    }

    // Attempt to fetch live memberships from backend if logged in
    if (token) {
      ApiClient.listTenants()
        .then((mems) => {
          setMemberships(mems);
          if (!currentTenant && mems.length > 0) {
            setActiveTenantId(mems[0].tenant_id);
            localStorage.setItem("finora_active_tenant_id", mems[0].tenant_id);
            localStorage.setItem("finora_active_role", mems[0].role);
          }
        })
        .catch(() => {
          // If offline or dev mode, supply fallback mock membership
          if (memberships.length === 0) {
            setMemberships([
              {
                id: "mem-001",
                tenant_id: "ten-prod",
                user_id: "usr-001",
                role: "FINANCE_MANAGER",
                is_default: true,
                tenant: {
                  id: "ten-prod",
                  name: "Finora Production Enterprise",
                  slug: "finora-prod",
                  default_currency: "INR",
                  settlement_cutoff_time: "23:00:00",
                  fee_overcharge_tolerance: "0.05",
                  max_knapsack_bound: 5,
                  is_active: true,
                },
              },
            ]);
            setActiveTenantId("ten-prod");
          }
        });
    } else {
      // Default offline presentation state for reviewing UI
      setMemberships([
        {
          id: "mem-001",
          tenant_id: "ten-prod",
          user_id: "usr-001",
          role: "FINANCE_MANAGER",
          is_default: true,
          tenant: {
            id: "ten-prod",
            name: "Finora Production Enterprise",
            slug: "finora-prod",
            default_currency: "INR",
            settlement_cutoff_time: "23:00:00",
            fee_overcharge_tolerance: "0.05",
            max_knapsack_bound: 5,
            is_active: true,
          },
        },
      ]);
      setActiveTenantId("ten-prod");
    }
  }, [router]);

  const handleSelectTenant = (tenantId: string) => {
    setActiveTenantId(tenantId);
    localStorage.setItem("finora_active_tenant_id", tenantId);
    const m = memberships.find((item) => item.tenant_id === tenantId);
    if (m) {
      localStorage.setItem("finora_active_role", m.role);
    }
  };

  if (!mounted) {
    return <div className="min-h-screen bg-canvas" />;
  }

  return (
    <div className="min-h-screen bg-canvas flex text-ink-primary font-sans antialiased">
      {/* 220px Left Sidebar */}
      <Sidebar
        user={user}
        memberships={memberships}
        activeTenantId={activeTenantId}
        onSelectTenant={handleSelectTenant}
      />

      {/* Main Workspace Canvas */}
      <div className="flex-1 flex flex-col min-w-0 bg-canvas overflow-x-hidden">
        {children}
      </div>
    </div>
  );
}
