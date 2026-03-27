import { createClient } from "@supabase/supabase-js";
import { NextRequest, NextResponse } from "next/server";

export async function GET(request: NextRequest) {
  const { searchParams, origin } = new URL(request.url);

  const code = searchParams.get("code");
  const error = searchParams.get("error");
  const errorDescription = searchParams.get("error_description");

  // GitHub (or Supabase) returned an OAuth error
  if (error) {
    const params = new URLSearchParams({ error: errorDescription ?? error });
    return NextResponse.redirect(`${origin}/?${params.toString()}`);
  }

  // No code present — nothing to exchange
  if (!code) {
    return NextResponse.redirect(
      `${origin}/?error=Missing+authorization+code`
    );
  }

  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const supabaseKey =
    process.env.SUPABASE_KEY ?? process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  if (!supabaseUrl || !supabaseKey) {
    return NextResponse.redirect(
      `${origin}/?error=Auth+service+not+configured`
    );
  }

  const supabase = createClient(supabaseUrl, supabaseKey);

  const { error: exchangeError } = await supabase.auth.exchangeCodeForSession(code);

  if (exchangeError) {
    const params = new URLSearchParams({ error: exchangeError.message });
    return NextResponse.redirect(`${origin}/?${params.toString()}`);
  }

  // Successful exchange — send the user to the dashboard
  return NextResponse.redirect(`${origin}/`);
}
