import { auth } from "@/lib/auth";
import { db } from "@/lib/db";
import { formatDateTime, formatCurrency } from "@/lib/utils";
import { CreditCard, TrendingUp } from "lucide-react";

const PAYMENT_STATUS_LABELS: Record<string, { label: string; className: string }> = {
  PENDING: { label: "Pendente", className: "bg-yellow-100 text-yellow-700" },
  PAID: { label: "Pago", className: "bg-green-100 text-green-700" },
  REFUNDED: { label: "Reembolsado", className: "bg-blue-100 text-blue-700" },
  FAILED: { label: "Falhou", className: "bg-red-100 text-red-700" },
};

export default async function BillingPage() {
  const session = await auth();
  if (!session) return null;

  const isProfessional = session.user.role === "PROFESSIONAL";

  const payments = await db.payment.findMany({
    where: {
      appointment: isProfessional
        ? { professionalId: session.user.id }
        : { clientId: session.user.id },
    },
    include: {
      appointment: {
        include: {
          client: { select: { name: true } },
          professional: { select: { name: true } },
        },
      },
    },
    orderBy: { createdAt: "desc" },
  });

  const totalPaid = payments
    .filter((p) => p.status === "PAID")
    .reduce((acc, p) => acc + Number(p.amount), 0);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Financeiro</h1>
        <p className="text-gray-500 mt-1">
          {isProfessional ? "Seus ganhos e histórico de pagamentos" : "Seus pagamentos"}
        </p>
      </div>

      {isProfessional && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <div className="flex items-center gap-4">
              <div className="h-12 w-12 bg-green-100 rounded-lg flex items-center justify-center">
                <TrendingUp className="h-6 w-6 text-green-600" />
              </div>
              <div>
                <p className="text-sm text-gray-500">Total recebido</p>
                <p className="text-2xl font-bold text-gray-900">{formatCurrency(totalPaid)}</p>
              </div>
            </div>
          </div>
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <div className="flex items-center gap-4">
              <div className="h-12 w-12 bg-blue-100 rounded-lg flex items-center justify-center">
                <CreditCard className="h-6 w-6 text-blue-600" />
              </div>
              <div>
                <p className="text-sm text-gray-500">Consultas pagas</p>
                <p className="text-2xl font-bold text-gray-900">
                  {payments.filter((p) => p.status === "PAID").length}
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-200">
        <div className="p-6 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">Histórico de pagamentos</h2>
        </div>
        <div className="divide-y divide-gray-100">
          {payments.length === 0 ? (
            <div className="p-12 text-center">
              <CreditCard className="h-12 w-12 text-gray-300 mx-auto mb-3" />
              <p className="text-gray-500">Nenhum pagamento encontrado</p>
            </div>
          ) : (
            payments.map((payment) => {
              const statusInfo =
                PAYMENT_STATUS_LABELS[payment.status] ?? PAYMENT_STATUS_LABELS.PENDING;
              return (
                <div key={payment.id} className="p-4 flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-gray-900">
                      {isProfessional
                        ? payment.appointment.client.name
                        : payment.appointment.professional.name}
                    </p>
                    <p className="text-sm text-gray-500">
                      {formatDateTime(payment.createdAt)}
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className={`text-xs px-2 py-1 rounded-full font-medium ${statusInfo.className}`}>
                      {statusInfo.label}
                    </span>
                    <span className="text-sm font-semibold text-gray-900">
                      {formatCurrency(Number(payment.amount))}
                    </span>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
