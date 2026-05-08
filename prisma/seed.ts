import { PrismaClient } from "@prisma/client";
import bcrypt from "bcryptjs";

const db = new PrismaClient();

const DEFAULT_CONTENT = {
  site_name: "ConsultaOnline",
  hero_title: "Atendimento online profissional e seguro",
  hero_subtitle:
    "Conecte-se com profissionais qualificados por videochamada. Agende, pague e faça sua consulta sem sair de casa.",
  hero_cta_client: "Sou cliente",
  hero_cta_professional: "Sou profissional",
  about_title: "Por que escolher nossa plataforma?",
  about_text:
    "Somos uma plataforma dedicada a conectar clientes e profissionais de saúde e bem-estar de forma simples, segura e acessível.",
  footer_contact: "contato@consultaonline.com.br",
};

async function main() {
  console.log("Seeding database...");

  // Conteúdo padrão do site
  for (const [key, value] of Object.entries(DEFAULT_CONTENT)) {
    await db.siteContent.upsert({
      where: { key },
      update: {},
      create: { key, value },
    });
  }

  // Admin
  const adminPassword = await bcrypt.hash("admin123", 12);
  const admin = await db.user.upsert({
    where: { email: "admin@consultaonline.com" },
    update: {},
    create: {
      name: "Administrador",
      email: "admin@consultaonline.com",
      password: adminPassword,
      role: "ADMIN",
    },
  });

  // Profissional
  const professionalPassword = await bcrypt.hash("senha123", 12);
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
          bio: "Psicóloga clínica com 10 anos de experiência em terapia cognitivo-comportamental. Atendo adultos com ansiedade, depressão e questões de autoconhecimento.",
          sessionPrice: 200,
          sessionDuration: 50,
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

  // Cliente
  const clientPassword = await bcrypt.hash("senha123", 12);
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

  console.log("\nSeed completo!");
  console.log("─────────────────────────────────");
  console.log(`Admin:         admin@consultaonline.com  / admin123`);
  console.log(`Profissional:  profissional@exemplo.com  / senha123`);
  console.log(`Cliente:       cliente@exemplo.com       / senha123`);
  console.log("─────────────────────────────────");
}

main()
  .catch(console.error)
  .finally(() => db.$disconnect());
