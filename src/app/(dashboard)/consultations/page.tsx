import { auth } from "@/lib/auth";
import { db } from "@/lib/db";
import { formatDateTime } from "@/lib/utils";
import { Video, Clock } from "lucide-react";
import Link from "next/link";

const STATUS_LABELS: Record<string, { label: string; className: string }> = {
  PENDING: { label: "Pendente", className: "bg-yellow-100 text-yellow-700" },
  CONFIRMED: { label: "Confirmado", className: "bg-green-100 text-green-700" },
  IN_PROGRESS: { label: "Em andamento", className: "bg-blue-100 text-blue-700" },
  COMPLETED: { label: "Concluído", className: "bg-gray-100 text-gray-700" },
  CANCELLED: { label: "Cancelado", className: "bg-red-100 text-red-700" },
  NO_SHOW: { label: "Não compareceu", className: "bg-orange-100 text-orange-700" },
};

export default async function ConsultationsPage() {
  const session = await auth();
  if (!session) return null;

  const isProfessional = session.user.role === "PROFESSIONAL";

  const appointments = await db.appointment.findMany({
    where: isProfessional
      ? { professionalId: session.user.id }
      : { clientId: session.user.id },
    include: {
      client: { select: { name: true, email: true } },
      professional: { select: { name: true } },
      payment: true,
    },
    orderBy: { scheduledAt: "desc" },
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Minhas Consultas</h1>
        <p className="text-gray-500 mt-1">Histórico e consultas agendadas</p>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100">
        {appointments.length === 0 ? (
          <div className="p-12 text-center">
            <Clock className="h-12 w-12 text-gray-300 mx-auto mb-3" />
            <p className="text-gray-500">Nenhuma consulta encontrada</p>
          </div>
        ) : (
          appointments.map((appt) => {
            const statusInfo = STATUS_LABELS[appt.status] ?? STATUS_LABELS.PENDING;
            return (
              <div key={appt.id} className="p-4 flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className="h-10 w-10 bg-blue-100 rounded-full flex items-center justify-center">
                    <Video className="h-5 w-5 text-blue-600" />
                  </div>
                  <div>
                    <p className="text-sm font-medium text-gray-900">
                      {isProfessional ? appt.client.name : appt.professional.name}
                    </p>
                    <p className="text-sm text-gray-500">
                      {formatDateTime(appt.scheduledAt)} • {appt.durationMin} min
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`text-xs px-2 py-1 rounded-full font-medium ${statusInfo.className}`}>
                    {statusInfo.label}
                  </span>
                  {(appt.status === "CONFIRMED" || appt.status === "IN_PROGRESS") &&
                    appt.videoRoomUrl && (
                      <Link
                        href={`/consultations/${appt.id}`}
                        className="text-xs bg-blue-600 text-white px-3 py-1 rounded-md hover:bg-blue-700 transition-colors"
                      >
                        Entrar na sala
                      </Link>
                    )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
