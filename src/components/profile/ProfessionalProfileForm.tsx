"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useRouter } from "next/navigation";
import { User, FileText, DollarSign, Clock, Phone, Award } from "lucide-react";

const schema = z.object({
  name: z.string().min(2, "Mínimo 2 caracteres"),
  specialty: z.string().min(2, "Informe sua especialidade"),
  bio: z.string().max(1000, "Máximo 1000 caracteres").optional(),
  crm: z.string().optional(),
  phone: z.string().optional(),
  sessionPrice: z.coerce.number().min(0, "Valor inválido"),
  sessionDuration: z.coerce.number().min(15).max(180),
  photoUrl: z.string().url("URL inválida").optional().or(z.literal("")),
});

type FormData = z.infer<typeof schema>;

interface Props {
  initialData: {
    name?: string | null;
    professionalProfile?: {
      specialty: string;
      bio?: string | null;
      crm?: string | null;
      phone?: string | null;
      sessionPrice: number;
      sessionDuration: number;
      photoUrl?: string | null;
    } | null;
  };
}

export function ProfessionalProfileForm({ initialData }: Props) {
  const router = useRouter();
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting, isDirty },
  } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: initialData.name ?? "",
      specialty: initialData.professionalProfile?.specialty ?? "",
      bio: initialData.professionalProfile?.bio ?? "",
      crm: initialData.professionalProfile?.crm ?? "",
      phone: initialData.professionalProfile?.phone ?? "",
      sessionPrice: Number(initialData.professionalProfile?.sessionPrice ?? 0),
      sessionDuration: initialData.professionalProfile?.sessionDuration ?? 50,
      photoUrl: initialData.professionalProfile?.photoUrl ?? "",
    },
  });

  const photoUrl = watch("photoUrl");
  const bio = watch("bio") ?? "";

  async function onSubmit(data: FormData) {
    setError(null);
    setSuccess(false);
    const res = await fetch("/api/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });

    if (!res.ok) {
      setError("Erro ao salvar. Tente novamente.");
      return;
    }

    setSuccess(true);
    router.refresh();
    setTimeout(() => setSuccess(false), 3000);
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-8">
      {success && (
        <div className="bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded-lg text-sm font-medium">
          Perfil salvo com sucesso!
        </div>
      )}
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">
          {error}
        </div>
      )}

      {/* Foto e nome */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="text-base font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <User className="h-5 w-5 text-blue-600" /> Identificação
        </h2>
        <div className="flex gap-6 items-start">
          <div className="flex-shrink-0">
            <div className="h-24 w-24 rounded-full bg-blue-100 overflow-hidden flex items-center justify-center border-2 border-blue-200">
              {photoUrl ? (
                <img src={photoUrl} alt="Foto" className="h-full w-full object-cover" />
              ) : (
                <User className="h-10 w-10 text-blue-400" />
              )}
            </div>
          </div>
          <div className="flex-1 space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Nome completo *
              </label>
              <input
                {...register("name")}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="Dr. João Silva"
              />
              {errors.name && <p className="mt-1 text-sm text-red-600">{errors.name.message}</p>}
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                URL da foto de perfil
              </label>
              <input
                {...register("photoUrl")}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="https://exemplo.com/sua-foto.jpg"
              />
              {errors.photoUrl && (
                <p className="mt-1 text-sm text-red-600">{errors.photoUrl.message}</p>
              )}
              <p className="mt-1 text-xs text-gray-400">
                Cole o link de uma imagem hospedada online
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Especialidade e bio */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="text-base font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <FileText className="h-5 w-5 text-blue-600" /> Informações profissionais
        </h2>
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Especialidade *
              </label>
              <input
                {...register("specialty")}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="Psicologia, Nutrição, Coaching..."
              />
              {errors.specialty && (
                <p className="mt-1 text-sm text-red-600">{errors.specialty.message}</p>
              )}
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                CRM / Registro profissional
              </label>
              <input
                {...register("crm")}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="CRM/SP 123456"
              />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Bio / Apresentação
            </label>
            <textarea
              {...register("bio")}
              rows={5}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
              placeholder="Conte sobre sua formação, experiência e abordagem de trabalho..."
            />
            <p className="mt-1 text-xs text-gray-400 text-right">
              {bio.length}/1000 caracteres
            </p>
            {errors.bio && <p className="mt-1 text-sm text-red-600">{errors.bio.message}</p>}
          </div>
        </div>
      </div>

      {/* Contato */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="text-base font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <Phone className="h-5 w-5 text-blue-600" /> Contato
        </h2>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Telefone / WhatsApp</label>
          <input
            {...register("phone")}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="(11) 99999-9999"
          />
        </div>
      </div>

      {/* Valores */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="text-base font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <DollarSign className="h-5 w-5 text-blue-600" /> Valor e duração da sessão
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Valor por sessão (R$)
            </label>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 text-sm">R$</span>
              <input
                {...register("sessionPrice")}
                type="number"
                min="0"
                step="0.01"
                className="w-full pl-9 pr-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="200,00"
              />
            </div>
            {errors.sessionPrice && (
              <p className="mt-1 text-sm text-red-600">{errors.sessionPrice.message}</p>
            )}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Duração da sessão (minutos)
            </label>
            <div className="relative">
              <Clock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
              <select
                {...register("sessionDuration")}
                className="w-full pl-9 pr-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 appearance-none"
              >
                <option value={30}>30 minutos</option>
                <option value={45}>45 minutos</option>
                <option value={50}>50 minutos</option>
                <option value={60}>60 minutos</option>
                <option value={90}>90 minutos</option>
                <option value={120}>2 horas</option>
              </select>
            </div>
          </div>
        </div>
      </div>

      <div className="flex justify-end">
        <button
          type="submit"
          disabled={isSubmitting || !isDirty}
          className="px-6 py-2.5 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {isSubmitting ? "Salvando..." : "Salvar perfil"}
        </button>
      </div>
    </form>
  );
}
