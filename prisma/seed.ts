import { PrismaClient } from "@prisma/client";
import bcrypt from "bcryptjs";

const db = new PrismaClient();

async function main() {
  console.log("Seeding database...");

  const professionalPassword = await bcrypt.hash("senha123", 12);
  const clientPassword = await bcrypt.hash("senha123", 12);

  const professional = await db.user.upsert({
    where: { email: "profissional@exemplo.com" },
    update: {},
    create: {
      name: "Dra. Ana Silva",
      email: "profissional@exemplo.com",
      password: professionalPassword,
      role: "PROFESSIONAL",
      professionalProfile: {
        create: {
          specialty: "Psicologia",
          bio: "Psicóloga clínica com 10 anos de experiência em terapia cognitivo-comportamental.",
          sessionPrice: 200,
          currency: "BRL",
          availabilities: {
            create: [
              { dayOfWeek: 1, startTime: "09:00", endTime: "18:00" },
              { dayOfWeek: 2, startTime: "09:00", endTime: "18:00" },
              { dayOfWeek: 3, startTime: "09:00", endTime: "18:00" },
              { dayOfWeek: 4, startTime: "09:00", endTime: "18:00" },
              { dayOfWeek: 5, startTime: "09:00", endTime: "16:00" },
            ],
          },
        },
      },
    },
  });

  const client = await db.user.upsert({
    where: { email: "cliente@exemplo.com" },
    update: {},
    create: {
      name: "João Santos",
      email: "cliente@exemplo.com",
      password: clientPassword,
      role: "CLIENT",
      clientProfile: { create: {} },
    },
  });

  console.log("Seed complete!");
  console.log(`Professional: ${professional.email} / senha123`);
  console.log(`Client: ${client.email} / senha123`);
}

main()
  .catch(console.error)
  .finally(() => db.$disconnect());
