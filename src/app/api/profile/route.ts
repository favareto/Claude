import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { auth } from "@/lib/auth";
import { db } from "@/lib/db";

const professionalSchema = z.object({
  name: z.string().min(2),
  bio: z.string().optional(),
  specialty: z.string().min(2),
  crm: z.string().optional(),
  phone: z.string().optional(),
  sessionPrice: z.coerce.number().min(0),
  sessionDuration: z.coerce.number().min(15).max(180),
  photoUrl: z.string().url().optional().or(z.literal("")),
});

const clientSchema = z.object({
  name: z.string().min(2),
  phone: z.string().optional(),
  birthDate: z.string().optional(),
});

export async function GET() {
  const session = await auth();
  if (!session) return NextResponse.json({ error: "Não autorizado" }, { status: 401 });

  const user = await db.user.findUnique({
    where: { id: session.user.id },
    include: {
      professionalProfile: { include: { availabilities: true } },
      clientProfile: true,
    },
  });

  return NextResponse.json(user);
}

export async function PUT(req: NextRequest) {
  const session = await auth();
  if (!session) return NextResponse.json({ error: "Não autorizado" }, { status: 401 });

  const body = await req.json();

  if (session.user.role === "PROFESSIONAL") {
    const parsed = professionalSchema.safeParse(body);
    if (!parsed.success) {
      return NextResponse.json({ error: "Dados inválidos", details: parsed.error.flatten() }, { status: 400 });
    }

    const { name, bio, specialty, crm, phone, sessionPrice, sessionDuration, photoUrl } = parsed.data;

    await db.$transaction([
      db.user.update({
        where: { id: session.user.id },
        data: { name },
      }),
      db.professionalProfile.update({
        where: { userId: session.user.id },
        data: { bio, specialty, crm, phone, sessionPrice, sessionDuration, photoUrl: photoUrl || null },
      }),
    ]);
  } else {
    const parsed = clientSchema.safeParse(body);
    if (!parsed.success) {
      return NextResponse.json({ error: "Dados inválidos" }, { status: 400 });
    }

    const { name, phone, birthDate } = parsed.data;

    await db.$transaction([
      db.user.update({ where: { id: session.user.id }, data: { name } }),
      db.clientProfile.update({
        where: { userId: session.user.id },
        data: { phone, birthDate: birthDate ? new Date(birthDate) : null },
      }),
    ]);
  }

  return NextResponse.json({ success: true });
}
