import Link from "next/link";
import { Video, Calendar, CreditCard, Shield } from "lucide-react";

export default function HomePage() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100">
      <header className="container mx-auto px-4 py-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Video className="h-8 w-8 text-blue-600" />
          <span className="text-xl font-bold text-gray-900">ConsultaOnline</span>
        </div>
        <nav className="flex items-center gap-4">
          <Link
            href="/login"
            className="text-gray-600 hover:text-gray-900 transition-colors"
          >
            Entrar
          </Link>
          <Link
            href="/register"
            className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors"
          >
            Começar agora
          </Link>
        </nav>
      </header>

      <main className="container mx-auto px-4 py-24 text-center">
        <h1 className="text-5xl font-bold text-gray-900 mb-6">
          Atendimento online{" "}
          <span className="text-blue-600">profissional e seguro</span>
        </h1>
        <p className="text-xl text-gray-600 mb-12 max-w-2xl mx-auto">
          Conecte-se com profissionais qualificados por videochamada. Agende,
          pague e faça sua consulta sem sair de casa.
        </p>
        <div className="flex gap-4 justify-center">
          <Link
            href="/register?role=client"
            className="bg-blue-600 text-white px-8 py-3 rounded-lg text-lg font-medium hover:bg-blue-700 transition-colors"
          >
            Sou cliente
          </Link>
          <Link
            href="/register?role=professional"
            className="bg-white text-blue-600 border-2 border-blue-600 px-8 py-3 rounded-lg text-lg font-medium hover:bg-blue-50 transition-colors"
          >
            Sou profissional
          </Link>
        </div>
      </main>

      <section className="container mx-auto px-4 py-20">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-8">
          {[
            {
              icon: Video,
              title: "Vídeo HD",
              desc: "Chamadas de alta qualidade com tecnologia WebRTC",
            },
            {
              icon: Calendar,
              title: "Agendamento fácil",
              desc: "Calendário integrado com lembretes automáticos",
            },
            {
              icon: CreditCard,
              title: "Pagamento seguro",
              desc: "Stripe com proteção total para suas transações",
            },
            {
              icon: Shield,
              title: "Privacidade total",
              desc: "Seus dados e conversas são 100% protegidos",
            },
          ].map(({ icon: Icon, title, desc }) => (
            <div key={title} className="bg-white rounded-xl p-6 shadow-sm">
              <Icon className="h-10 w-10 text-blue-600 mb-4" />
              <h3 className="text-lg font-semibold text-gray-900 mb-2">{title}</h3>
              <p className="text-gray-600">{desc}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
