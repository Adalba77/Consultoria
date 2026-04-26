import { NextResponse } from 'next/server';

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  const phone = String(body?.phone || '').replace(/\D/g, '');

  if (phone.length < 10) {
    return NextResponse.json(
      { message: 'Informe um telefone valido.' },
      { status: 400 }
    );
  }

  return NextResponse.json({
    success: true,
    message: 'Codigo enviado.',
    data: {
      expiresInSeconds: 300,
      demoCode: '123456',
    },
  });
}
