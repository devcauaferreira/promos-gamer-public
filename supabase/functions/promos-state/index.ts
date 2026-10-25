import {createClient} from 'npm:@supabase/supabase-js@2';
import {authorized, json} from '../_shared/security.mjs';

Deno.serve(async (request: Request) => {
  try {
    if (!await authorized(request,Deno.env.get('BOT_API_SECRET'))) return json({error:'unauthorized'},401);
    const db = createClient(Deno.env.get('SUPABASE_URL')!,Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,
      {auth:{persistSession:false,autoRefreshToken:false}});
    if (request.method === 'GET') {
      const {data,error} = await db.from('promos_runtime_state').select('version,payload').eq('id','main').single();
      if (error) throw new Error('Persistence failed');
      return json(data);
    }
    if (request.method === 'PUT') {
      if (Number(request.headers.get('content-length')) > 7000000) return json({error:'too_large'},413);
      const text = await request.text();
      if (text.length > 7000000) return json({error:'too_large'},413);
      const body = JSON.parse(text);
      if (!Number.isSafeInteger(body.version) || body.version < 0 || typeof body.payload !== 'string' ||
          body.payload.length > 6999000 || !/^[A-Za-z0-9+/]+={0,2}$/.test(body.payload)) return json({error:'invalid_state'},400);
      if (!atob(body.payload.slice(0,24)).startsWith('SQLite format 3\x00')) return json({error:'invalid_sqlite'},400);
      const {data,error} = await db.from('promos_runtime_state').update({version:body.version+1,
        payload:body.payload,updated_at:new Date().toISOString()}).eq('id','main').eq('version',body.version)
        .select('version').maybeSingle();
      if (error) throw new Error('Persistence failed');
      if (!data) return json({error:'state_conflict'},409);
      return json(data);
    }
    return json({error:'method_not_allowed'},405);
  } catch { return json({error:'state_operation_failed'},502); }
});
