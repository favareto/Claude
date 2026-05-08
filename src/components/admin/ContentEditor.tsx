"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { Check, AlertCircle } from "lucide-react";

interface ContentField {
  key: string;
  label: string;
  description: string;
  type: "text" | "textarea";
  placeholder: string;
}

const CONTENT_FIELDS: ContentField[] = [
  {
    key: "hero_title",
    label: "Título principal",
    description: "Texto grande em destaque na página inicial",
    type: "text",
    placeholder: "Atendimento online profissional e seguro",
  },
  {
    key: "hero_subtitle",
    label: "Subtítulo",
    description: "Texto abaixo do título principal",
    type: "textarea",
    placeholder: "Conecte-se com profissionais qualificados por videochamada.",
  },
  {
    key: "hero_cta_client",
    label: "Botão principal (cliente)",
    description: "Texto do botão para clientes",
    type: "text",
    placeholder: "Agendar consulta",
  },
  {
    key: "hero_cta_professional",
    label: "Botão principal (profissional)",
    description: "Texto do botão para profissionais",
    type: "text",
    placeholder: "Quero atender online",
  },
  {
    key: "about_title",
    label: "Título da seção 'Sobre'",
    description: "",
    type: "text",
    placeholder: "Por que escolher nossa plataforma?",
  },
  {
    key: "about_text",
    label: "Texto da seção 'Sobre'",
    description: "Descrição mais longa sobre a plataforma",
    type: "textarea",
    placeholder: "Somos uma plataforma...",
  },
  {
    key: "footer_contact",
    label: "Email de contato no rodapé",
    description: "",
    type: "text",
    placeholder: "contato@suaplataforma.com.br",
  },
  {
    key: "site_name",
    label: "Nome do site",
    description: "Aparece no cabeçalho, rodapé e aba do navegador",
    type: "text",
    placeholder: "ConsultaOnline",
  },
];

interface Props {
  initialContent: Record<string, string>;
}

export function ContentEditor({ initialContent }: Props) {
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");

  const { register, handleSubmit, formState: { isDirty } } = useForm({
    defaultValues: Object.fromEntries(
      CONTENT_FIELDS.map((f) => [f.key, initialContent[f.key] ?? ""])
    ),
  });

  async function onSubmit(data: Record<string, string>) {
    setStatus("saving");
    const res = await fetch("/api/admin/content", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });

    if (!res.ok) {
      setStatus("error");
      setTimeout(() => setStatus("idle"), 3000);
      return;
    }

    setStatus("saved");
    setTimeout(() => setStatus("idle"), 3000);
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
      {status === "saved" && (
        <div className="flex items-center gap-2 bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded-lg text-sm font-medium">
          <Check className="h-4 w-4" /> Conteúdo salvo com sucesso!
        </div>
      )}
      {status === "error" && (
        <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">
          <AlertCircle className="h-4 w-4" /> Erro ao salvar. Tente novamente.
        </div>
      )}

      <div className="grid gap-6">
        {CONTENT_FIELDS.map((field) => (
          <div key={field.key} className="bg-white rounded-xl border border-gray-200 p-5">
            <label className="block text-sm font-semibold text-gray-900 mb-0.5">
              {field.label}
            </label>
            {field.description && (
              <p className="text-xs text-gray-400 mb-3">{field.description}</p>
            )}
            {field.type === "textarea" ? (
              <textarea
                {...register(field.key)}
                rows={3}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                placeholder={field.placeholder}
              />
            ) : (
              <input
                {...register(field.key)}
                type="text"
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder={field.placeholder}
              />
            )}
          </div>
        ))}
      </div>

      <div className="flex justify-end">
        <button
          type="submit"
          disabled={status === "saving" || !isDirty}
          className="px-6 py-2.5 bg-blue-600 text-white rounded-lg font-medium text-sm hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {status === "saving" ? "Salvando..." : "Publicar alterações"}
        </button>
      </div>
    </form>
  );
}
