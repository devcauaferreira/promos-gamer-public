const http = require('node:http');
const crypto = require('node:crypto');
const {RemoteSessionStore} = require('./publishers/remote_session.cjs');
const store = new RemoteSessionStore({url:process.env.SUPABASE_PROJECT_URL,
  token:process.env.BOT_API_SECRET,key:process.env.WHATSAPP_SESSION_KEY,dataPath:'.wwebjs_auth_cloud'});
const nonce = crypto.randomBytes(24).toString('hex');
const server = http.createServer(async (request,response) => {
  if (request.url !== '/' + nonce && request.url !== '/' + nonce + '/qr') {
    response.writeHead(404); response.end(); return;
  }
  response.setHeader('Cache-Control','no-store');
  response.setHeader('Referrer-Policy','no-referrer');
  if (request.url.endsWith('/qr')) {
    try {
      const image = await store.readQR();
      if (!image) { response.writeHead(404); response.end(); return; }
      response.setHeader('Content-Type','image/png');
      response.end(Buffer.from(image.split(',')[1],'base64'));
    } catch { response.writeHead(503); response.end(); }
    return;
  }
  response.setHeader('Content-Type','text/html; charset=utf-8');
  response.end(`<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="5">
    <title>Conectar WhatsApp da nuvem</title><body style="font:18px sans-serif;text-align:center">
    <h1>WhatsApp do GitHub Actions</h1><p>No celular: Aparelhos conectados → Conectar aparelho.</p>
    <img width="420" height="420" src="/${nonce}/qr" alt="Aguardando QR privado do workflow...">
    <p>Execute o workflow “Conectar WhatsApp na nuvem”. O QR aparece aqui e se atualiza automaticamente.</p>
    <p>Após ler, aguarde o workflow confirmar que a sessão foi salva. Depois pode fechar esta janela.</p>`);
});
server.listen(0,'127.0.0.1',()=>{
  process.stdout.write('http://127.0.0.1:' + server.address().port + '/' + nonce + '\n');
});
setTimeout(()=>server.close(),12*60*1000).unref();
