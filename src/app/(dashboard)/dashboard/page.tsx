import { auth } from "@/lib/auth";
import { db } from "@/lib/db";
import { formatDateTime, formatCurrency } from "@/lib/utils";
import { Calendar, Video, CreditCard, Users } from "lucide-react";
import Link from "next/link";

export default async function DashboardPage() {
  const session = await auth();
  if (!session) return null;

  const isProfessional = session.user.role === "PROFESSIONAL";

  const upcomingAppointments = await db.appointment.findMany({
    where: {
      ...(isProfessional
        ? { professionalId: session.user.id }
        : { clientId: session.user.id }),
      status: { in: ["PENDING", "CONFIRMED"] },
      scheduledAt: { gte: new Date() },
    },
    include: {
      client: { select: { name: true } },
      professional: { select: { name: true } },
      payment: true,
    },
    orderBy: { scheduledAt: "asc" },
    take: 5,
  });

  const totalAppointments = await db.appointment.count({
    where: isProfessional
      ? { professionalId: session.user.id }
      : { clientId: session.user.id },
  });

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">
          Olá, {session.user.name?.split(" ")[0]}!
        </h1>
        <p className="text-gray-500 mt-1">
          {isProfessional ? "Gerencie suas consultas e agenda" : "Agende e acompanhe suas consultas"}
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <div className="flex items-center gap-4">
            <div className="h-12 w-12 bg-blue-100 rounded-lg flex items-center justify-center">
              <Calendar className="h-6 w-6 text-blue-600" />
            </div>
            <div>
              <p className="text-sm text-gray-500">Próximas consultas</p>
              <p className="text-2xl font-bold text-gray-900">{upcomingAppointments.length}</p>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <div className="flex items-center gap-4">
            <div className="h-12 w-12 bg-green-100 rounded-lg flex items-center justify-center">
              <Users className="h-6 w-6 text-green-600" />
            </div>
            <div>
              <p className="text-sm text-gray-500">Total de consultas</p>
              <p className="text-2xl font-bold text-gray-900">{totalAppointments}</p>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <div className="flex items-center gap-4">
            <div className="h-12 w-12 bg-purple-100 rounded-lg flex items-center justify-center">
              <Video className="h-6 w-6 text-purple-600" />
            </div>
            <div>
              <p className="text-sm text-gray-500">Status</p>
              <p className="text-2xl font-bold text-green-600">Online</p>
            </div>
          </div>
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-200">
        <div className="p-6 border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900">Próximas consultas</h2>
          <Link href="/consultations" className="text-sm text-blue-600 hover:text-blue-500">
            Ver todas
          </Link>
        </div>
        <div className="divide-y divide-gray-100">
          {upcomingAppointments.length === 0 ? (
            <div className="p-6 text-center">
              <Calendar className="h-12 w-12 text-gray-300 mx-auto mb-3" />
              <p className="text-gray-500">Nenhuma consulta agendada</p>
              {!isProfessional && (
                <Link
                  href="/schedule"
                  className="mt-3 inline-block text-sm text-blue-600 hover:text-blue-500"
                >
                  Agendar consulta
                </Link>
              )}
            </div>
          ) : (
            upcomingAppointments.map((appointment) => (
              <div key={appointment.id} className="p-4 flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className="h-10 w-10 bg-blue-100 rounded-full flex items-center justify-center">
                    <Video className="h-5 w-5 text-blue-600" />
                  </div>
                  <div>
                    <p className="text-sm font-medium text-gray-900">
                      {isProfessional ? appointment.client.name : appointment.professional.name}
                    </p>
                    <p className="text-sm text-gray-500">
                      {formatDateTime(appointment.scheduledAt)}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span
                    className={`text-xs px-2 py-1 rounded-full font-medium ${
                      appointment.status === "CONFIRMED"
                        ? "bg-green-100 text-green-700"
                        : "bg-yellow-100 text-yellow-700"
                    }`}
                  >
                    {appointment.status === "CONFIRMED" ? "Confirmado" : "Pendente"}
                  </span>
                  {appointment.videoRoomUrl && appointment.status === "CONFIRMED" && (
                    <Link
                      href={`/consultations/${appointment.id}`}
                      className="text-xs bg-blue-600 text-white px-3 py-1 rounded-md hover:bg-blue-700 transition-colors"
                    >
                      Entrar
                    </Link>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
