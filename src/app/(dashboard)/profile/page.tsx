import { auth } from "@/lib/auth";
import { db } from "@/lib/db";
import { redirect } from "next/navigation";
import { ProfessionalProfileForm } from "@/components/profile/ProfessionalProfileForm";
import { AvailabilityEditor } from "@/components/profile/AvailabilityEditor";

export default async function ProfilePage() {
  const session = await auth();
  if (!session) redirect("/login");

  const user = await db.user.findUnique({
    where: { id: session.user.id },
    include: {
      professionalProfile: { include: { availabilities: { orderBy: { dayOfWeek: "asc" } } } },
      clientProfile: true,
    },
  });

  if (!user) redirect("/login");

  if (user.role === "CLIENT") {
    return (
      <div className="max-w-2xl space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Meu Perfil</h1>
          <p className="text-gray-500 mt-1">Gerencie suas informações pessoais</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <p className="text-gray-500">Edição de perfil de cliente em breve.</p>
        </div>
      </div>
    );
  }

  const availabilities = user.professionalProfile?.availabilities ?? [];

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Meu Perfil</h1>
        <p className="text-gray-500 mt-1">
          Essas informações aparecem para os clientes ao agendar uma consulta
        </p>
      </div>

      <ProfessionalProfileForm
        initialData={{
          name: user.name,
          professionalProfile: user.professionalProfile
            ? {
                ...user.professionalProfile,
                sessionPrice: Number(user.professionalProfile.sessionPrice),
              }
            : null,
        }}
      />

      <div>
        <h2 className="text-xl font-bold text-gray-900 mb-1">Horários de atendimento</h2>
        <p className="text-gray-500 mb-6 text-sm">
          Configure os dias e horários em que você está disponível para consultas
        </p>
        <AvailabilityEditor initialSlots={availabilities} />
      </div>
    </div>
  );
}
