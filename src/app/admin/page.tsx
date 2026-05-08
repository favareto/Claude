import { db } from "@/lib/db";
import { Users, Calendar, CreditCard, TrendingUp } from "lucide-react";

export default async function AdminPage() {
  const [totalUsers, totalProfessionals, totalAppointments, totalRevenue] = await Promise.all([
    db.user.count({ where: { role: "CLIENT" } }),
    db.user.count({ where: { role: "PROFESSIONAL" } }),
    db.appointment.count(),
    db.payment.aggregate({
      where: { status: "PAID" },
      _sum: { amount: true },
    }),
  ]);

  const recentUsers = await db.user.findMany({
    orderBy: { createdAt: "desc" },
    take: 5,
    select: { id: true, name: true, email: true, role: true, createdAt: true },
  });

  const stats = [
    { label: "Clientes", value: totalUsers, icon: Users, color: "blue" },
    { label: "Profissionais", value: totalProfessionals, icon: TrendingUp, color: "green" },
    { label: "Consultas", value: totalAppointments, icon: Calendar, color: "purple" },
    {
      label: "Receita total",
      value: `R$ ${Number(totalRevenue._sum.amount ?? 0).toFixed(2)}`,
      icon: CreditCard,
      color: "orange",
    },
  ];

  const colorMap: Record<string, string> = {
    blue: "bg-blue-100 text-blue-600",
    green: "bg-green-100 text-green-600",
    purple: "bg-purple-100 text-purple-600",
    orange: "bg-orange-100 text-orange-600",
  };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Visão geral</h1>
        <p className="text-gray-500 mt-1">Resumo da plataforma</p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map(({ label, value, icon: Icon, color }) => (
          <div key={label} className="bg-white rounded-xl border border-gray-200 p-5">
            <div className={`h-10 w-10 rounded-lg flex items-center justify-center mb-3 ${colorMap[color]}`}>
              <Icon className="h-5 w-5" />
            </div>
            <p className="text-2xl font-bold text-gray-900">{value}</p>
            <p className="text-sm text-gray-500 mt-0.5">{label}</p>
          </div>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-gray-200">
        <div className="p-5 border-b border-gray-100">
          <h2 className="font-semibold text-gray-900">Últimos usuários cadastrados</h2>
        </div>
        <div className="divide-y divide-gray-100">
          {recentUsers.map((user) => (
            <div key={user.id} className="p-4 flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-900">{user.name}</p>
                <p className="text-xs text-gray-500">{user.email}</p>
              </div>
              <span
                className={`text-xs px-2 py-1 rounded-full font-medium ${
                  user.role === "PROFESSIONAL"
                    ? "bg-blue-100 text-blue-700"
                    : "bg-gray-100 text-gray-600"
                }`}
              >
                {user.role === "PROFESSIONAL" ? "Profissional" : "Cliente"}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
