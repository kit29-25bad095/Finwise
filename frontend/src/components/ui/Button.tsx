import React from "react";
import { cn } from "@/lib/utils";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "subtle" | "danger" | "outline" | "ghost";
  size?: "sm" | "md" | "lg";
  loading?: boolean;
}

export function Button({
  children,
  variant = "secondary",
  size = "md",
  loading = false,
  className,
  disabled,
  ...props
}: ButtonProps) {
  const baseStyles = "inline-flex items-center justify-center font-medium transition-colors border select-none disabled:opacity-50 disabled:pointer-events-none focus:outline-none focus:ring-1 focus:ring-ink-primary";

  const resolvedVariant = variant === "outline" ? "secondary" : variant === "ghost" ? "subtle" : variant;

  const variantStyles = {
    // Primary: Black background #18181B, white text
    primary: "bg-[#18181B] text-white border-[#18181B] hover:bg-[#27272A] active:bg-[#09090B]",
    // Secondary: Editorial white background, structural border
    secondary: "bg-surface text-ink-primary border-border hover:bg-hover active:bg-[#E4E4E7]",
    // Subtle: No border, minimal hover
    subtle: "bg-transparent text-ink-secondary border-transparent hover:bg-hover hover:text-ink-primary",
    // Danger: Financial exception/leakage red
    danger: "bg-[#FEF2F2] text-[#DC2626] border-[#FECACA] hover:bg-[#FEE2E2]",
  };

  const sizeStyles = {
    sm: "h-8 px-2.5 text-xs rounded",
    md: "h-9 px-3.5 text-xs rounded",
    lg: "h-10 px-4 text-sm rounded",
  };

  return (
    <button
      className={cn(baseStyles, variantStyles[resolvedVariant], sizeStyles[size], className)}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? (
        <span className="flex items-center gap-1.5">
          <svg className="animate-spin h-3.5 w-3.5" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
          </svg>
          <span>{children}</span>
        </span>
      ) : (
        children
      )}
    </button>
  );
}
