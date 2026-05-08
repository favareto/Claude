import { db } from "@/lib/db";
import { formatDate } from "@/lib/utils";
import { User, Shield } from "lucide-react";

export default async function AdminUsersPage() {
  const users = await db.user.findMany({
    orderBy: { createdAt: "desc" },
    include: {
      professionalProfile: { select: { specialty: true, isActive: true, sessionPrice: true } },
      _count: {
        select: {
          appointmentsAsClient: true,
          appointmentsAsProfessional: true,
        },
      },
    },
  });

  const roleLabel: Record<string, string> = {
    CLIENT: "Cliente",
    PROFESSIONAL: "Profissional",
    ADMIN: "Admin",
  };

  const roleBadge: Record<string, string> = {
    CLIENT: "bg-gray-100 text-gray-700",
    PROFESSIONAL: "bg-blue-100 text-blue-700",
    ADMIN: "bg-red-100 text-red-700",
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Usuários</h1>
        <p className="text-gray-500 mt-1">{users.length} usuários cadastrados</p>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50">
              <th className="px-5 py-3 text-left font-medium text-gray-500">Usuário</th>
              <th className="px-5 py-3 text-left font-medium text-gray-500">Tipo</th>
              <th className="px-5 py-3 text-left font-medium text-gray-500">Especialidade</th>
              <th className="px-5 py-3 text-left font-medium text-gray-500">Consultas</th>
              <th className="px-5 py-3 text-left font-medium text-gray-500">Cadastro</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {users.map((user) => (
              <tr key={user.id} className="hover:bg-gray-50 transition-colors">
                <td className="px-5 py-4">
                  <div className="flex items-center gap-3">
                    <div className="h-8 w-8 rounded-full bg-blue-100 flex items-center justify-center flex-shrink-0">
                      {user.role === "ADMIN" ? (
                        <Shield className="h-4 w-4 text-red-500" />
                      ) : (
                        <User className="h-4 w-4 text-blue-500" />
                      )}
                    </div>
                    <div>
                      <p className="font-medium text-gray-900">{user.name ?? "—"}</p>
                      <p className="text-xs text-gray-400">{user.email}</p>
                    </div>
                  </div>
                </td>
                <td className="px-5 py-4">
                  <span className={`text-xs px-2 py-1 rounded-full font-medium ${roleBadge[user.role]}`}>
                    {roleLabel[user.role]}
                  </span>
                </td>
                <td className="px-5 py-4 text-gray-500">
                  {user.professionalProfile?.specialty ?? "—"}
                </td>
                <td className="px-5 py-4 text-gray-500">
                  {user.role === "PROFESSIONAL"
                    ? user._count.appointmentsAsProfessional
                    : user._count.appointmentsAsClient}
                </td>
                <td className="px-5 py-4 text-gray-500">{formatDate(user.createdAt)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
