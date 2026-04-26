'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';

export default function LoginPage() {
  const router = useRouter();
  const [step, setStep] = useState<'phone' | 'otp'>('phone');
  const [phone, setPhone] = useState('');
  const [otp, setOtp] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const formatPhone = (value: string) => {
    const numbers = value.replace(/\D/g, '');
    if (numbers.length <= 2) return numbers;
    if (numbers.length <= 7) return `(${numbers.slice(0, 2)}) ${numbers.slice(2)}`;
    return `(${numbers.slice(0, 2)}) ${numbers.slice(2, 7)}-${numbers.slice(7, 11)}`;
  };

  const handleRequestOTP = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    try {
      const res = await fetch('/api/auth/otp/request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone: phone.replace(/\D/g, '') }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.message || 'Erro ao enviar codigo');
      }

      setStep('otp');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro ao enviar codigo');
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyOTP = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    try {
      const res = await fetch('/api/auth/otp/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          phone: phone.replace(/\D/g, ''),
          otp,
        }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.message || 'Codigo invalido');
      }

      const data = await res.json();
      localStorage.setItem('accessToken', data.data.accessToken);
      localStorage.setItem('refreshToken', data.data.refreshToken);
      localStorage.setItem('userRole', data.data.user.role);

      if (data.data.user.role === 'PROFESSIONAL') {
        router.push('/profissional/meu-painel');
      } else {
        router.push('/dashboard');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Codigo invalido');
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen overflow-hidden bg-[#120b16] text-white">
      <section className="relative min-h-screen">
        <div className="absolute inset-0">
          <img
            src="/image-2.png"
            alt="divina"
            className="h-full w-full object-cover object-center opacity-45"
          />
          <div className="absolute inset-0 bg-[linear-gradient(90deg,rgba(18,11,22,0.98)_0%,rgba(18,11,22,0.9)_42%,rgba(18,11,22,0.28)_100%)]" />
          <div className="absolute inset-x-0 bottom-0 h-40 bg-gradient-to-t from-[#120b16] to-transparent" />
        </div>

        <div className="relative z-10 mx-auto grid min-h-screen max-w-7xl grid-cols-1 items-center gap-10 px-5 py-8 lg:grid-cols-[1.05fr_0.95fr] lg:px-10">
          <div className="max-w-2xl">
            <div className="mb-8 inline-flex items-center rounded-full border border-white/15 bg-white/10 px-4 py-2 text-sm font-medium text-rose-100 backdrop-blur">
              Gestão inteligente para salões, clínicas e studios
            </div>

            <h1 className="text-5xl font-black tracking-tight text-white sm:text-6xl lg:text-7xl">
              divina
            </h1>
            <p className="mt-5 max-w-xl text-xl leading-8 text-rose-50/90">
              Agendamentos, clientes, financeiro e WhatsApp em uma experiência visual, rápida e feita para negócios de beleza venderem mais com menos esforço.
            </p>

            <div className="mt-8 max-w-md rounded-2xl border border-amber-300/50 bg-amber-300 px-6 py-5 text-[#2a1600] shadow-2xl shadow-amber-950/30">
              <p className="text-sm font-black uppercase tracking-[0.22em]">Promoção do sistema</p>
              <p className="mt-1 text-4xl font-black">R$ 1.000,00</p>
            </div>

            <div className="mt-8 grid max-w-2xl grid-cols-1 gap-3 sm:grid-cols-3">
              {['Agenda organizada', 'WhatsApp integrado', 'Painel financeiro'].map(item => (
                <div key={item} className="rounded-xl border border-white/10 bg-white/10 px-4 py-3 text-sm font-semibold text-white backdrop-blur">
                  {item}
                </div>
              ))}
            </div>
          </div>

          <div className="w-full max-w-md justify-self-center lg:justify-self-end">
            <div className="rounded-[2rem] border border-white/15 bg-white p-7 text-gray-900 shadow-2xl shadow-black/40">
              {step === 'phone' ? (
                <form onSubmit={handleRequestOTP}>
                  <p className="text-sm font-bold uppercase tracking-[0.18em] text-purple-600">
                    Acesso ao painel
                  </p>
                  <h2 className="mt-2 text-2xl font-bold text-gray-950">
                    Entre com seu telefone
                  </h2>
                  <p className="mt-2 text-sm text-gray-500">
                    Receba um código para acessar a sua área de gestão.
                  </p>

                  <div className="mt-6">
                    <label className="mb-2 block text-sm font-semibold text-gray-700">
                      Telefone
                    </label>
                    <input
                      type="tel"
                      value={phone}
                      onChange={e => setPhone(formatPhone(e.target.value))}
                      placeholder="(11) 99999-9999"
                      className="w-full rounded-xl border border-gray-200 bg-gray-50 px-4 py-4 text-lg outline-none transition focus:border-purple-500 focus:bg-white focus:ring-4 focus:ring-purple-100"
                      maxLength={15}
                      required
                    />
                  </div>

                  {error && <p className="mt-4 text-sm font-medium text-red-500">{error}</p>}

                  <button
                    type="submit"
                    disabled={loading || phone.replace(/\D/g, '').length < 10}
                    className="mt-6 w-full rounded-xl bg-gradient-to-r from-purple-700 to-rose-500 py-4 font-bold text-white shadow-lg shadow-purple-500/25 transition hover:scale-[1.01] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {loading ? 'Enviando...' : 'Enviar código'}
                  </button>
                </form>
              ) : (
                <form onSubmit={handleVerifyOTP}>
                  <p className="text-sm font-bold uppercase tracking-[0.18em] text-purple-600">
                    Verificação
                  </p>
                  <h2 className="mt-2 text-2xl font-bold text-gray-950">Digite o código</h2>
                  <p className="mt-2 text-sm text-gray-500">Enviamos um código para {phone}</p>

                  <div className="mt-6">
                    <input
                      type="text"
                      value={otp}
                      onChange={e => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
                      placeholder="000000"
                      className="w-full rounded-xl border border-gray-200 bg-gray-50 px-4 py-4 text-center text-3xl tracking-[0.35em] outline-none transition focus:border-purple-500 focus:bg-white focus:ring-4 focus:ring-purple-100"
                      maxLength={6}
                      required
                    />
                  </div>

                  {error && <p className="mt-4 text-sm font-medium text-red-500">{error}</p>}

                  <button
                    type="submit"
                    disabled={loading || otp.length !== 6}
                    className="mt-6 w-full rounded-xl bg-gradient-to-r from-purple-700 to-rose-500 py-4 font-bold text-white shadow-lg shadow-purple-500/25 transition hover:scale-[1.01] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {loading ? 'Verificando...' : 'Entrar'}
                  </button>

                  <button
                    type="button"
                    onClick={() => {
                      setStep('phone');
                      setOtp('');
                      setError('');
                    }}
                    className="mt-4 w-full py-2 font-semibold text-purple-700 hover:underline"
                  >
                    Usar outro número
                  </button>
                </form>
              )}
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
