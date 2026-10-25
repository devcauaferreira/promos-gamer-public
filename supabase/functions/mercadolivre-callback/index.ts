import {createClient} from 'npm:@supabase/supabase-js@2';
import {authorized, authorizationUrl, callbackInputs, hash, json, randomToken, seal, unseal} from '../_shared/security.mjs';
import {exchangeTokens, OAuthFailure, safeFailure} from '../_shared/oauth.mjs';

function env(name: string): string {
  const value = Deno.env.get(name);
  if (!value) throw new OAuthFailure('configuration_missing');
  return value;
}
async function exchange(parameters: Record<string,string>) {
  // Tokens de refresh são de uso único: não repetir este POST automaticamente.
  return exchangeTokens(parameters,{clientId:env('ML_CLIENT_ID'),clientSecret:env('ML_CLIENT_SECRET')});
}
Deno.serve(async (request: Request) => {
  let phase = 'configuration';
  let db: ReturnType<typeof createClient> | undefined;
  try {
    const route = new URL(request.url);
    const action = route.pathname.split('/').filter(Boolean).at(-1);
    const admin = await authorized(request, env('BOT_API_SECRET'));
    db = createClient(env('SUPABASE_URL'), env('SUPABASE_SERVICE_ROLE_KEY'), {auth:{persistSession:false, autoRefreshToken:false}});
    const encryptionKey = env('ML_TOKEN_ENCRYPTION_KEY');
    if (action === 'start' && request.method === 'POST') {
      if (!admin) return json({error:'unauthorized'}, 401);
      phase = 'authorization_start';
      const state = randomToken(), verifier = randomToken(48);
      const authorization_url = await authorizationUrl(env('ML_CLIENT_ID'), env('ML_REDIRECT_URI'), state, verifier);
      const {error} = await db.from('ml_oauth_pending').insert({state_hash:await hash(state),
        encrypted_verifier:await seal({verifier}, encryptionKey), expires_at:new Date(Date.now()+600000).toISOString()});
      if (error) throw new Error('Persistence failed');
      await db.from('ml_oauth_pending').delete().lt('expires_at', new Date().toISOString());
      return json({authorization_url, expires_in:600});
    }
    if (action === 'status' && request.method === 'POST') {
      if (!admin) return json({error:'unauthorized'}, 401);
      phase = 'status';
      const {data, error} = await db.from('ml_oauth_credentials').select('expires_at,refresh_lock,updated_at').eq('id','mercadolivre').maybeSingle();
      if (error) throw new Error('Persistence failed');
      let diagnosticsQuery = db.from('ml_oauth_diagnostics').select('id,created_at,phase,code,provider_status,provider_code')
        .order('created_at',{ascending:false}).limit(1);
      if (data?.updated_at) diagnosticsQuery = diagnosticsQuery.gte('created_at',data.updated_at);
      const {data:diagnostics} = await diagnosticsQuery;
      return json({connected:!!data, expires_at:data?.expires_at, requires_review:!!data?.refresh_lock, last_error:diagnostics?.[0] ?? null});
    }
    if (action === 'token' && request.method === 'POST') {
      if (!admin) return json({error:'unauthorized'}, 401);
      phase = 'token_read';
      const {data:stored, error} = await db.from('ml_oauth_credentials').select('*').eq('id','mercadolivre').maybeSingle();
      if (error) throw new Error('Persistence failed');
      if (!stored) return json({error:'authorization_required'}, 409);
      let tokens = await unseal(stored.encrypted_tokens, encryptionKey);
      let expiresAt = stored.expires_at;
      if (new Date(expiresAt).getTime() < Date.now()+120000) {
        phase = 'refresh_claim';
        const lock = randomToken();
        const {data:claimed, error:claimError} = await db.from('ml_oauth_credentials').update({refresh_lock:lock})
          .eq('id','mercadolivre').eq('generation',stored.generation).is('refresh_lock',null).select('id').maybeSingle();
        if (claimError) throw new Error('Persistence failed');
        if (!claimed) return json({error:'refresh_busy_or_uncertain'}, 409);
        // Se houver falha/timeout depois do POST, mantém o lock para não reutilizar refresh token.
        phase = 'refresh_exchange';
        tokens = await exchange({grant_type:'refresh_token', refresh_token:tokens.refresh_token});
        expiresAt = new Date(Date.now()+tokens.expires_in*1000).toISOString();
        phase = 'refresh_save';
        const {data:updated, error:updateError} = await db.from('ml_oauth_credentials').update({
          encrypted_tokens:await seal(tokens,encryptionKey), expires_at:expiresAt, refresh_lock:null,
          updated_at:new Date().toISOString()}).eq('id','mercadolivre').eq('generation',stored.generation)
          .eq('refresh_lock',lock).select('id').maybeSingle();
        if (updateError || !updated) throw new Error('Persistence failed');
      }
      return json({access_token:tokens.access_token, expires_at:expiresAt});
    }
    if (action === 'mercadolivre-callback' && request.method === 'GET') {
      let inputs;
      try { inputs = callbackInputs(route); } catch { return json({error:'invalid_callback'},400); }
      // DELETE ... RETURNING consome o state atomicamente antes de usar o código.
      phase = 'state_consume';
      const {data:pending, error} = await db.from('ml_oauth_pending').delete().eq('state_hash',await hash(inputs.state))
        .gt('expires_at',new Date().toISOString()).select('encrypted_verifier').maybeSingle();
      if (error) throw new Error('Persistence failed');
      if (!pending) return json({error:'expired_or_used_state'},400);
      if (inputs.denied) return json({error:'authorization_denied'},400);
      phase = 'verifier_decrypt';
      const {verifier} = await unseal(pending.encrypted_verifier,encryptionKey);
      phase = 'authorization_exchange';
      const tokens = await exchange({grant_type:'authorization_code', code:inputs.code!,
        redirect_uri:env('ML_REDIRECT_URI'), code_verifier:verifier});
      phase = 'credential_save';
      const {error:saveError} = await db.from('ml_oauth_credentials').upsert({id:'mercadolivre',
        encrypted_tokens:await seal(tokens,encryptionKey), expires_at:new Date(Date.now()+tokens.expires_in*1000).toISOString(),
        generation:crypto.randomUUID(), refresh_lock:null, updated_at:new Date().toISOString()});
      if (saveError) throw new Error('Persistence failed');
      return new Response(null,{status:303,headers:{Location:env('ML_REDIRECT_URI')+'/success',
        'Cache-Control':'no-store','Referrer-Policy':'no-referrer'}});
    }
    if (action === 'success' && request.method === 'GET') return json({message:'Autorização concluída. Pode fechar esta aba.'});
    return json({error:'not_found'},404);
  } catch (error) {
    const diagnostic = safeFailure(error,phase,crypto.randomUUID());
    // Apenas enumerações controladas: nunca imprimir error.message, URL ou corpo do provedor.
    console.error(JSON.stringify({event:'oauth_failure',...diagnostic}));
    try { if (db) await db.from('ml_oauth_diagnostics').insert(diagnostic); } catch { /* sem conteúdo bruto */ }
    return json({error:diagnostic.code, phase:diagnostic.phase, provider_error:diagnostic.provider_code,
      reference:diagnostic.id, action:'check_configuration_or_reauthorize'},502);
  }
});
