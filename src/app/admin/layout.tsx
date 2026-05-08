import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import Link from "next/link";
import { Video, LayoutDashboard, FileText, Users, Settings } from "lucide-react";

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const session = await auth();
  if (!session || session.user.role !== "ADMIN") redirect("/dashboard");

  return (
    <div className="flex h-screen bg-gray-50">
      <aside className="w-60 bg-gray-900 text-white flex flex-col">
        <div className="p-5 border-b border-gray-700">
          <Link href="/admin" className="flex items-center gap-2">
            <Video className="h-6 w-6 text-blue-400" />
            <div>
              <p className="font-bold text-sm">ConsultaOnline</p>
              <p className="text-xs text-gray-400">Painel Admin</p>
            </div>
          </Link>
        </div>
        <nav className="flex-1 p-3 space-y-1">
          {[
            { href: "/admin", icon: LayoutDashboard, label: "Visão geral" },
            { href: "/admin/content", icon: FileText, label: "Conteúdo do site" },
            { href: "/admin/users", icon: Users, label: "Usuários" },
          ].map(({ href, icon: Icon, label }) => (
            <Link
              key={href}
              href={href}
              className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-gray-300 hover:bg-gray-800 hover:text-white transition-colors"
            >
              <Icon className="h-4 w-4" />
              {label}
            </Link>
          ))}
        </nav>
        <div className="p-3 border-t border-gray-700">
          <Link
            href="/dashboard"
            className="flex items-center gap-2 px-3 py-2 text-xs text-gray-400 hover:text-white transition-colors"
          >
            ← Voltar ao dashboard
          </Link>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto">
        <div className="container mx-auto px-8 py-8">{children}</div>
      </main>
    </div>
  );
}
