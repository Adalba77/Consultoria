import { NextResponse } from 'next/server';

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  const phone = String(body?.phone || '').replace(/\D/g, '');
  const otp = String(body?.otp || '').replace(/\D/g, '');

  if (phone.length < 10 || otp.length !== 6) {
    return NextResponse.json(
      { message: 'Telefone ou codigo invalido.' },
      { status: 400 }
    );
  }

  return NextResponse.json({
    success: true,
    data: {
      accessToken: 'divina-demo-access-token',
      refreshToken: 'divina-demo-refresh-token',
      user: {
        id: 'demo-user',
        name: 'Divina',
        role: 'OWNER',
        phone,
      },
    },
  });
}
