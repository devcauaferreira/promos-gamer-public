import {createClient} from 'npm:@supabase/supabase-js@2';
import {authorized, json} from '../_shared/security.mjs';

const headers = {'Cache-Control':'no-store', 'Content-Type':'application/octet-stream', 'X-Content-Type-Options':'nosniff'};
Deno.serve(async (request: Request) => {
  try {
    if (!await authorized(request, Deno.env.get('BOT_API_SECRET'))) return json({error:'unauthorized'},401);
    const route = new URL(request.url).pathname.replace(/^.*\/whatsapp-session/, '');
    const chunk = /^\/chunk\/([a-f0-9]{32})\/(\d{1,2})$/.exec(route);
    if (!['','/','/qr','/manifest','/legacy'].includes(route) && !chunk)
      return json({error:'not_found'},404);
    if (chunk && Number(chunk[2]) >= 32) return json({error:'not_found'},404);
    const object = route === '/qr' ? 'qr.bin'
      : route === '/manifest' ? 'session-manifest.bin'
      : chunk ? `chunks/${chunk[1]}/${chunk[2]}.bin` : 'session.bin';
    const max = object === 'qr.bin' ? 100000
      : route === '/manifest' ? 4096
      : chunk ? 8 * 1024 * 1024 + 32 : 40 * 1024 * 1024;
    const storage = createClient(Deno.env.get('SUPABASE_URL')!, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,
      {auth:{persistSession:false,autoRefreshToken:false}}).storage.from('promos-whatsapp-private');
    if (request.method === 'HEAD') {
      const {data,error} = await storage.list('', {search:route === '' || route === '/' ? 'session' : object,limit:10});
      if (error) throw new Error('storage');
      const found = route === '' || route === '/'
        ? data.some(row=>['session.bin','session-manifest.bin'].includes(row.name))
        : data.some(row=>row.name===object.split('/').pop());
      return new Response(null,{status:found?204:404,headers});
    }
    if (request.method === 'GET') {
      const {data,error} = await storage.download(object);
      if (error) {
        if (String(error.statusCode)==='404' || String(error.statusCode)==='400') return json({error:'missing'},404);
        throw new Error('storage');
      }
      return new Response(data,{headers});
    }
    if (request.method === 'PUT') {
      if (Number(request.headers.get('content-length')) > max) return json({error:'too_large'},413);
      const bytes = new Uint8Array(await request.arrayBuffer());
      if (bytes.length > max) return json({error:'too_large'},413);
      if (bytes.length < 32 || new TextDecoder().decode(bytes.slice(0,4)) !== 'PWA1') return json({error:'invalid_envelope'},400);
      const {error} = await storage.upload(object,bytes,{upsert:true,contentType:'application/octet-stream'});
      if (error) throw new Error('storage');
      return json({saved:true});
    }
    if (request.method === 'DELETE') {
      const {error} = await storage.remove([object]);
      if (error) throw new Error('storage');
      return json({deleted:true});
    }
    return json({error:'method_not_allowed'},405);
  } catch { return json({error:'session_storage_failed'},502); }
});
