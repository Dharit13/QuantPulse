import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";

let supabase: SupabaseClient | null = null;

function getSupabase(): SupabaseClient | null {
  if (supabase) return supabase;
  if (!supabaseUrl || !supabaseAnonKey) return null;
  supabase = createClient(supabaseUrl, supabaseAnonKey);
  return supabase;
}

export { getSupabase, supabase };

export async function getSessionToken(): Promise<string | null> {
  const client = getSupabase();
  if (!client) return null;
  try {
    const {
      data: { session },
    } = await client.auth.getSession();
    return session?.access_token ?? null;
  } catch {
    return null;
  }
}
