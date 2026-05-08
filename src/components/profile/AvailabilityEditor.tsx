"use client";

import { useState } from "react";
import { Clock, Check } from "lucide-react";

const DAYS = [
  { value: 0, label: "Domingo" },
  { value: 1, label: "Segunda-feira" },
  { value: 2, label: "Terça-feira" },
  { value: 3, label: "Quarta-feira" },
  { value: 4, label: "Quinta-feira" },
  { value: 5, label: "Sexta-feira" },
  { value: 6, label: "Sábado" },
];

const TIME_OPTIONS: string[] = [];
for (let h = 6; h <= 22; h++) {
  TIME_OPTIONS.push(`${String(h).padStart(2, "0")}:00`);
  if (h < 22) TIME_OPTIONS.push(`${String(h).padStart(2, "0")}:30`);
}

interface Slot {
  dayOfWeek: number;
  startTime: string;
  endTime: string;
  isActive: boolean;
}

interface Props {
  initialSlots: Slot[];
}

export function AvailabilityEditor({ initialSlots }: Props) {
  const [slots, setSlots] = useState<Slot[]>(() => {
    return DAYS.map((day) => {
      const existing = initialSlots.find((s) => s.dayOfWeek === day.value);
      return existing ?? {
        dayOfWeek: day.value,
        startTime: "09:00",
        endTime: "18:00",
        isActive: false,
      };
    });
  });

  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggleDay(dayOfWeek: number) {
    setSlots((prev) =>
      prev.map((s) =>
        s.dayOfWeek === dayOfWeek ? { ...s, isActive: !s.isActive } : s
      )
    );
  }

  function updateTime(dayOfWeek: number, field: "startTime" | "endTime", value: string) {
    setSlots((prev) =>
      prev.map((s) => (s.dayOfWeek === dayOfWeek ? { ...s, [field]: value } : s))
    );
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    setSaved(false);

    const res = await fetch("/api/availability", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slots }),
    });

    setSaving(false);

    if (!res.ok) {
      setError("Erro ao salvar horários. Tente novamente.");
      return;
    }

    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  }

  const activeCount = slots.filter((s) => s.isActive).length;

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className="p-4 border-b border-gray-100 bg-gray-50 flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Clock className="h-4 w-4" />
          <span>
            {activeCount === 0
              ? "Nenhum dia ativo"
              : `${activeCount} dia${activeCount > 1 ? "s" : ""} ativo${activeCount > 1 ? "s" : ""}`}
          </span>
        </div>
        <p className="text-xs text-gray-400">Clique no dia para ativar/desativar</p>
      </div>

      <div className="divide-y divide-gray-100">
        {DAYS.map((day) => {
          const slot = slots.find((s) => s.dayOfWeek === day.value)!;
          return (
            <div
              key={day.value}
              className={`flex items-center gap-4 p-4 transition-colors ${
                slot.isActive ? "bg-white" : "bg-gray-50"
              }`}
            >
              {/* Toggle do dia */}
              <button
                type="button"
                onClick={() => toggleDay(day.value)}
                className={`flex-shrink-0 w-11 h-6 rounded-full transition-colors relative ${
                  slot.isActive ? "bg-blue-600" : "bg-gray-300"
                }`}
              >
                <span
                  className={`absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
                    slot.isActive ? "translate-x-5" : "translate-x-0"
                  }`}
                />
              </button>

              {/* Nome do dia */}
              <span
                className={`w-32 text-sm font-medium ${
                  slot.isActive ? "text-gray-900" : "text-gray-400"
                }`}
              >
                {day.label}
              </span>

              {/* Horários */}
              {slot.isActive ? (
                <div className="flex items-center gap-2 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs text-gray-500">Das</span>
                    <select
                      value={slot.startTime}
                      onChange={(e) => updateTime(day.value, "startTime", e.target.value)}
                      className="text-sm border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                    >
                      {TIME_OPTIONS.map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs text-gray-500">às</span>
                    <select
                      value={slot.endTime}
                      onChange={(e) => updateTime(day.value, "endTime", e.target.value)}
                      className="text-sm border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                    >
                      {TIME_OPTIONS.filter((t) => t > slot.startTime).map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              ) : (
                <span className="flex-1 text-sm text-gray-400 italic">Indisponível</span>
              )}
            </div>
          );
        })}
      </div>

      <div className="p-4 border-t border-gray-100 flex items-center justify-between">
        <div>
          {saved && (
            <span className="text-sm text-green-600 font-medium flex items-center gap-1.5">
              <Check className="h-4 w-4" /> Horários salvos!
            </span>
          )}
          {error && <span className="text-sm text-red-600">{error}</span>}
        </div>
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {saving ? "Salvando..." : "Salvar horários"}
        </button>
      </div>
    </div>
  );
}
