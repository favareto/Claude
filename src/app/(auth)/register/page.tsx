import { Metadata } from "next";
import Link from "next/link";
import { Video } from "lucide-react";
import { RegisterForm } from "@/components/auth/RegisterForm";

export const metadata: Metadata = { title: "Cadastro" };

export default function RegisterPage() {
  return (
    <div className="min-h-screen bg-gray-50 flex flex-col justify-center py-12 sm:px-6 lg:px-8">
      <div className="sm:mx-auto sm:w-full sm:max-w-md">
        <div className="flex justify-center">
          <Link href="/" className="flex items-center gap-2">
            <Video className="h-8 w-8 text-blue-600" />
            <span className="text-xl font-bold text-gray-900">ConsultaOnline</span>
          </Link>
        </div>
        <h2 className="mt-6 text-center text-3xl font-bold text-gray-900">
          Crie sua conta
        </h2>
        <p className="mt-2 text-center text-sm text-gray-600">
          Já tem conta?{" "}
          <Link href="/login" className="text-blue-600 hover:text-blue-500 font-medium">
            Entrar
          </Link>
        </p>
      </div>
      <div className="mt-8 sm:mx-auto sm:w-full sm:max-w-md">
        <div className="bg-white py-8 px-4 shadow sm:rounded-lg sm:px-10">
          <RegisterForm />
        </div>
      </div>
    </div>
  );
}
