import { auth } from "@/lib/auth";
import { db } from "@/lib/db";
import { Calendar } from "lucide-react";

export default async function SchedulePage() {
  const session = await auth();
  if (!session) return null;

  const isProfessional = session.user.role === "PROFESSIONAL";

  if (isProfessional) {
    const profile = await db.professionalProfile.findUnique({
      where: { userId: session.user.id },
      include: { availabilities: { orderBy: { dayOfWeek: "asc" } } },
    });

    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Minha Agenda</h1>
          <p className="text-gray-500 mt-1">Configure seus horários de atendimento</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">
            Disponibilidade semanal
          </h2>
          <p className="text-gray-500 text-sm">
            Funcionalidade de configuração de agenda em construção.
          </p>
        </div>
      </div>
    );
  }

  const professionals = await db.user.findMany({
    where: { role: "PROFESSIONAL" },
    include: {
      professionalProfile: {
        include: { availabilities: true },
      },
    },
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Agendar Consulta</h1>
        <p className="text-gray-500 mt-1">Escolha um profissional e agende sua consulta</p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {professionals.map((prof) => (
          <div key={prof.id} className="bg-white rounded-xl border border-gray-200 p-6">
            <div className="flex items-start gap-4">
              <div className="h-12 w-12 bg-blue-100 rounded-full flex items-center justify-center flex-shrink-0">
                <span className="text-blue-600 font-semibold text-lg">
                  {prof.name?.charAt(0)}
                </span>
              </div>
              <div className="flex-1 min-w-0">
                <h3 className="font-semibold text-gray-900">{prof.name}</h3>
                <p className="text-sm text-blue-600">{prof.professionalProfile?.specialty}</p>
                {prof.professionalProfile?.bio && (
                  <p className="text-sm text-gray-500 mt-2 line-clamp-2">
                    {prof.professionalProfile.bio}
                  </p>
                )}
                <p className="text-sm font-semibold text-gray-900 mt-3">
                  R$ {Number(prof.professionalProfile?.sessionPrice).toFixed(2)}/sessão
                </p>
              </div>
            </div>
            <a
              href={`/professional/${prof.id}`}
              className="mt-4 w-full flex items-center justify-center gap-2 bg-blue-600 text-white py-2 px-4 rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors"
            >
              <Calendar className="h-4 w-4" />
              Agendar
            </a>
          </div>
        ))}
      </div>
    </div>
  );
}
