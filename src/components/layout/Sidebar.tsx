"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut } from "next-auth/react";
import {
  Video,
  LayoutDashboard,
  Calendar,
  ClipboardList,
  CreditCard,
  User,
  LogOut,
  Shield,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { UserRole } from "@prisma/client";

interface SidebarProps {
  user: {
    name?: string | null;
    email?: string | null;
    image?: string | null;
    role: UserRole;
  };
}

const navItems = [
  { href: "/dashboard", icon: LayoutDashboard, label: "Início" },
  { href: "/schedule", icon: Calendar, label: "Agenda" },
  { href: "/consultations", icon: ClipboardList, label: "Consultas" },
  { href: "/billing", icon: CreditCard, label: "Financeiro" },
  { href: "/profile", icon: User, label: "Meu Perfil" },
];

export function Sidebar({ user }: SidebarProps) {
  const pathname = usePathname();

  return (
    <aside className="w-64 bg-white border-r border-gray-200 flex flex-col">
      <div className="p-6 border-b border-gray-200">
        <Link href="/dashboard" className="flex items-center gap-2">
          <Video className="h-6 w-6 text-blue-600" />
          <span className="font-bold text-gray-900">ConsultaOnline</span>
        </Link>
      </div>

      <nav className="flex-1 p-4 space-y-1">
        {navItems.map(({ href, icon: Icon, label }) => (
          <Link
            key={href}
            href={href}
            className={cn(
              "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
              pathname === href
                ? "bg-blue-50 text-blue-700"
                : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
            )}
          >
            <Icon className="h-5 w-5" />
            {label}
          </Link>
        ))}
      </nav>

      <div className="p-4 border-t border-gray-200 space-y-2">
        {user.role === "ADMIN" && (
          <Link
            href="/admin"
            className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium text-red-600 hover:bg-red-50 transition-colors"
          >
            <Shield className="h-5 w-5" />
            Painel Admin
          </Link>
        )}
        <div className="flex items-center gap-3 px-3 py-2">
          <div className="h-8 w-8 rounded-full bg-blue-100 flex items-center justify-center">
            <User className="h-4 w-4 text-blue-600" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-gray-900 truncate">{user.name}</p>
            <p className="text-xs text-gray-500 truncate">
              {user.role === "PROFESSIONAL" ? "Profissional" : "Cliente"}
            </p>
          </div>
        </div>
        <button
          onClick={() => signOut({ callbackUrl: "/" })}
          className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-100 hover:text-gray-900 transition-colors"
        >
          <LogOut className="h-5 w-5" />
          Sair
        </button>
      </div>
    </aside>
  );
}
