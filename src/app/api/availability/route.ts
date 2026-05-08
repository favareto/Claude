import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { auth } from "@/lib/auth";
import { db } from "@/lib/db";

const availabilitySchema = z.object({
  slots: z.array(
    z.object({
      dayOfWeek: z.number().min(0).max(6),
      startTime: z.string().regex(/^\d{2}:\d{2}$/),
      endTime: z.string().regex(/^\d{2}:\d{2}$/),
      isActive: z.boolean(),
    })
  ),
});

export async function PUT(req: NextRequest) {
  const session = await auth();
  if (!session || session.user.role !== "PROFESSIONAL") {
    return NextResponse.json({ error: "Não autorizado" }, { status: 401 });
  }

  const body = await req.json();
  const parsed = availabilitySchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: "Dados inválidos" }, { status: 400 });
  }

  const profile = await db.professionalProfile.findUnique({
    where: { userId: session.user.id },
  });

  if (!profile) {
    return NextResponse.json({ error: "Perfil não encontrado" }, { status: 404 });
  }

  // Deleta todos e recria — mais simples e confiável
  await db.$transaction([
    db.availability.deleteMany({ where: { professionalId: profile.id } }),
    db.availability.createMany({
      data: parsed.data.slots.map((slot) => ({
        professionalId: profile.id,
        dayOfWeek: slot.dayOfWeek,
        startTime: slot.startTime,
        endTime: slot.endTime,
        isActive: slot.isActive,
      })),
    }),
  ]);

  return NextResponse.json({ success: true });
}
