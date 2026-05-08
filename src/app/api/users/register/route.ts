import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import bcrypt from "bcryptjs";
import { db } from "@/lib/db";

const schema = z.object({
  name: z.string().min(2),
  email: z.string().email(),
  password: z.string().min(6),
  role: z.enum(["CLIENT", "PROFESSIONAL"]),
  specialty: z.string().optional(),
});

export async function POST(req: NextRequest) {
  const body = await req.json();
  const parsed = schema.safeParse(body);

  if (!parsed.success) {
    return NextResponse.json({ error: "Dados inválidos" }, { status: 400 });
  }

  const { name, email, password, role, specialty } = parsed.data;

  const existing = await db.user.findUnique({ where: { email } });
  if (existing) {
    return NextResponse.json({ error: "Email já cadastrado" }, { status: 409 });
  }

  const hashedPassword = await bcrypt.hash(password, 12);

  const user = await db.user.create({
    data: {
      name,
      email,
      password: hashedPassword,
      role,
      ...(role === "CLIENT" && {
        clientProfile: { create: {} },
      }),
      ...(role === "PROFESSIONAL" && {
        professionalProfile: {
          create: {
            specialty: specialty ?? "Não informada",
            sessionPrice: 0,
          },
        },
      }),
    },
  });

  return NextResponse.json({ id: user.id }, { status: 201 });
}
