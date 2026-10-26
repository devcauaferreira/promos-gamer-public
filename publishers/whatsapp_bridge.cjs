const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const readline = require('node:readline');
const { Client, LocalAuth, RemoteAuth, MessageMedia } = require('whatsapp-web.js');
const {logBridgeDiagnostic} = require('./bridge_diagnostics.cjs');
const qrcode = require('qrcode-terminal');
const root = path.resolve(__dirname, '..');
const tokenFile = path.join(root, '.bridge_token');
if (!process.env.WHATSAPP_BRIDGE_TOKEN && !fs.existsSync(tokenFile))
  fs.writeFileSync(tokenFile, crypto.randomBytes(32).toString('hex'), {flag: 'wx', mode: 0o600});
const token = process.env.WHATSAPP_BRIDGE_TOKEN || fs.readFileSync(tokenFile, 'utf8').trim();
if (token.length < 24) throw new Error('Defina WHATSAPP_BRIDGE_TOKEN com pelo menos 24 caracteres.');
const executablePath = [
  process.env.WHATSAPP_BROWSER_PATH,
  path.join(process.env.PROGRAMFILES || 'C:\\Program Files', 'Google', 'Chrome', 'Application', 'chrome.exe'),
  path.join(process.env.LOCALAPPDATA || '', 'Google', 'Chrome', 'Application', 'chrome.exe'),
  path.join(process.env['PROGRAMFILES(X86)'] || 'C:\\Program Files (x86)', 'Microsoft', 'Edge', 'Application', 'msedge.exe')
].find(candidate => candidate && fs.existsSync(candidate));
const remote = process.env.WHATSAPP_AUTH_MODE === 'supabase';
let store;
let sessionSaved = false;
let saveQueue = Promise.resolve();
let authStrategy;
if (remote) {
  const {RemoteSessionStore} = require('./remote_session.cjs');
  const dataPath = path.join(root, '.wwebjs_auth_cloud');
  store = new RemoteSessionStore({url:process.env.SUPABASE_PROJECT_URL,
    token:process.env.BOT_API_SECRET,key:process.env.WHATSAPP_SESSION_KEY,dataPath});
  authStrategy = new RemoteAuth({store,clientId:'promos-gamer',dataPath,backupSyncIntervalMs:300000});
  const save = authStrategy.storeRemoteSession.bind(authStrategy);
  authStrategy.storeRemoteSession = options => {
    saveQueue = saveQueue.then(() => save(options));
    return saveQueue;
  };
} else authStrategy = new LocalAuth({ dataPath: path.join(root, '.wwebjs_auth') });
const client = new Client({authStrategy,
  puppeteer: { headless: remote, ...(remote ? {args:['--no-sandbox','--disable-setuid-sandbox']} : {}),
    ...(executablePath ? { executablePath } : {}) }, qrMaxRetries: 10
});
let ready = false;
let busy = false;
let readySince = 0;
let phase = 'initializing';
client.on('authenticated', () => { phase = 'authenticated'; if (remote) console.log('Sessão WhatsApp autenticada; aguardando sincronização.'); });
client.on('loading_screen', percentage => {
  if (remote && Number.isFinite(Number(percentage))) console.log('Sincronização WhatsApp: ' + Number(percentage) + '%');
});
async function listGroups() {
  // Lê apenas nomes/IDs: getChats também carrega mensagens e metadados,
  // cuja serialização pode falhar em versões recentes do WhatsApp Web.
  return client.pupPage.evaluate(() => {
    const chats = window.require('WAWebCollections').Chat.getModelsArray();
    return chats.filter(chat => chat.id?._serialized?.endsWith('@g.us'))
      .map(chat => ({name: chat.formattedTitle || chat.name || chat.groupMetadata?.subject || chat.id._serialized,
                     id: chat.id._serialized}));
  });
}
client.on('qr', async qr => {
  if (remote) {
    if (process.env.WHATSAPP_ALLOW_QR !== 'true') {
      console.error('Sessão da nuvem precisa de autorização. Execute Conectar WhatsApp na nuvem.');
      await stop(2, false);
      return;
    }
    try {
      const dataURL = await require('qrcode').toDataURL(qr, {width:420, margin:4});
      await store.saveQR(dataURL);
      console.log('QR atualizado no armazenamento privado. Abra conectar-whatsapp-cloud.cmd no computador.');
    } catch { console.error('Não foi possível disponibilizar o QR privado.'); }
    return;
  }
  console.log('WhatsApp > Aparelhos conectados > Conectar aparelho. Leia o QR:');
  qrcode.generate(qr, { small: true });
});
client.on('ready', async () => {
  try {
    await client.pupPage.evaluate(require('./message_compat.cjs').installMessageKeyCompatibility);
  } catch {
    phase = 'message_compatibility_failed';
    ready = false;
    console.error('Compatibilidade de mensagens não validada; envio suspenso.');
    return;
  }
  ready = true;
  readySince = Date.now();
  phase = 'connected';
  console.log('WhatsApp conectado.');
  if (remote) {
    try {
      sessionSaved = await store.sessionExists({session:'RemoteAuth-promos-gamer'});
      await store.clearQR();
    } catch { console.error('Falha ao consultar persistência da sessão.'); }
    return;
  }
  try {
    const groups = await listGroups();
    groups.forEach((chat, index) => console.log(`${index + 1}. ${chat.name}`));
    if (!groups.length) {
      console.log('Crie o grupo no celular e reinicie esta ponte para selecioná-lo.');
      return;
    }
    const input = readline.createInterface({input: process.stdin, output: process.stdout});
    input.question('Número do grupo para as ofertas (Enter mantém a configuração): ', answer => {
      const index = Number(answer.trim()) - 1;
      if (answer.trim() && Number.isInteger(index) && groups[index]) {
        const file = path.join(root, 'settings.json');
        const settings = JSON.parse(fs.readFileSync(file, 'utf8'));
        settings.whatsapp_group_id = groups[index].id;
        fs.writeFileSync(file, JSON.stringify(settings, null, 2) + '\n');
        console.log(`Grupo configurado: ${groups[index].name}. Nenhuma mensagem enviada.`);
      } else if (answer.trim()) console.log('Seleção inválida. Grupo não alterado.');
      input.close();
    });
  } catch (error) { console.error('Não foi possível listar os grupos:', error.message); }
});
client.on('remote_session_saved', () => { sessionSaved = true; console.log('Sessão da nuvem salva com criptografia.'); });
client.on('disconnected', () => { ready = false; phase = 'disconnected'; });
client.on('auth_failure', () => { ready = false; phase = 'auth_failure'; console.error('Falha na autenticação.'); });
function respond(res, status, data) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(data));
}
const server = http.createServer(async (req, res) => {
  if (req.headers.authorization !== `Bearer ${token}`) return respond(res, 401, {error:'Não autorizado'});
  if (req.method === 'GET' && req.url === '/health') {
    try {
      if (!ready) {
        let connection_state = 'initializing';
        try {
          const value = await client.getState();
          connection_state = ['CONNECTED','OPENING','UNPAIRED','UNPAIRED_IDLE','PAIRING','UNLAUNCHED','TIMEOUT','CONFLICT'].includes(value) ? value : 'other';
        } catch {}
        return respond(res,503,{ready:false,phase,connection_state});
      }
      if (await client.getState() !== 'CONNECTED') return respond(res,503,{ready:false,phase});
      const settings = JSON.parse(fs.readFileSync(path.join(root,'settings.json'),'utf8'));
      const group_found = (await listGroups()).some(chat=>chat.id===settings.whatsapp_group_id);
      const healthy = group_found && (!remote || (sessionSaved && Date.now() - readySince >= 15000));
      return respond(res, healthy ? 200 : 503, {ready:healthy,phase,group_found,session_saved:remote ? sessionSaved : null});
    } catch { return respond(res,503,{ready:false,error:'session_check_failed'}); }
  }
  if (!ready) return respond(res, 503, {error:'WhatsApp desconectado'});
  if (remote && Date.now() - readySince < 15000) return respond(res,503,{error:'Aguardando estabilização da sessão'});
  let deliveryPhase = 'request';
  try {
    if (req.method === 'GET' && req.url === '/groups') {
      return respond(res, 200, await listGroups());
    }
    if (req.method === 'GET' && ['/test-status','/media-test-status'].includes(req.url)) {
      const mediaTest = req.url === '/media-test-status';
      const settings = JSON.parse(fs.readFileSync(path.join(root,'settings.json'),'utf8'));
      if (!(await listGroups()).some(chat=>chat.id===settings.whatsapp_group_id))
        return respond(res,400,{error:'Grupo configurado não encontrado'});
      const chat = await client.getChatById(settings.whatsapp_group_id);
      const messages = await chat.fetchMessages({limit:50,fromMe:true});
      const expected = mediaTest
        ? '🧪 Teste técnico do Promos Gamer: validação de envio com foto pelo GitHub Actions. Não é uma promoção.'
        : 'Teste técnico do Promos Gamer pelo GitHub Actions. Não é uma oferta.';
      const matches = messages.filter(message=>message.fromMe && message.body === expected && (!mediaTest || message.hasMedia));
      const confirmed = matches.find(message=>message.ack>=1);
      return respond(res,200,{found:matches.length>0,confirmed:!!confirmed,
        acks:matches.map(message=>Number.isInteger(message.ack)?message.ack:null),
        message_id:confirmed?.id?._serialized || confirmed?.id?.$1 || null});
    }
    if (req.method !== 'POST' || req.url !== '/send') return respond(res, 404, {error:'Rota inexistente'});
    if (busy) return respond(res, 429, {error:'Envio em andamento'});
    busy = true;
    try {
      let raw = '';
      for await (const chunk of req) {
        raw += chunk;
        if (Buffer.byteLength(raw) > 4_100_000) return respond(res, 413, {error:'Mensagem muito grande'});
      }
      const {group_id, message, image} = JSON.parse(raw);
      const settings = JSON.parse(fs.readFileSync(path.join(root, 'settings.json'), 'utf8'));
      if (!group_id || group_id !== settings.whatsapp_group_id || !group_id.endsWith('@g.us'))
        return respond(res, 400, {error:'Grupo diferente do configurado'});
      if (typeof message !== 'string' || !message.trim() || message.length > 4000)
        return respond(res, 400, {error:'Mensagem inválida'});
      if (image && (typeof image.data !== 'string' || image.data.length > 4_000_000 ||
          !['image/jpeg','image/png','image/webp'].includes(image.mimetype) ||
          !/^[A-Za-z0-9+/]+={0,2}$/.test(image.data)))
        return respond(res, 400, {error:'Imagem inválida'});
      if (!(await listGroups()).some(chat => chat.id === group_id))
        return respond(res, 400, {error:'Grupo não encontrado na sessão conectada'});
      deliveryPhase = 'send';
      const sent = image
        ? await client.sendMessage(group_id, new MessageMedia(image.mimetype, image.data),
            {caption:message,sendSeen:false,waitUntilMsgSent:true})
        : await client.sendMessage(group_id, message, {sendSeen:false,waitUntilMsgSent:true});
      deliveryPhase = 'confirmation';
      const message_id = await require('./message_confirmation.cjs').confirmedMessageId(sent);
      return respond(res, 200, { message_id });
    } finally { busy = false; }
  } catch (error) {
    console.error(error.message);
    respond(res, 500, {error:'Falha na ponte; confira o terminal antes de tentar novamente',
      error_code:deliveryPhase === 'confirmation' ? 'confirmation_missing' : 'send_failed'});
  }
});
server.listen(8787, '127.0.0.1', () => console.log('Ponte local: http://127.0.0.1:8787'));
async function startClient() {
  // A stale/corrupt remote archive can prevent whatsapp-web.js from reaching
  // the QR event. Reset is explicit and is only exposed by the connect job.
  if (remote && process.env.WHATSAPP_RESET_SESSION === 'true')
    await store.delete({session:'RemoteAuth-promos-gamer'});
  await client.initialize();
}
startClient().catch(error => { logBridgeDiagnostic(error); process.exit(1); });
let stopping = false;
async function stop(code = 0, save = true) {
  if (stopping) return;
  stopping = true;
  server.close();
  if (remote) {
    clearInterval(authStrategy.backupSync);
    try {
      if (save && ready && sessionSaved) await authStrategy.storeRemoteSession();
      await store.clearQR();
    } catch { code = 1; console.error('Falha ao salvar sessão antes de encerrar.'); }
  }
  await client.destroy();
  process.exit(code);
}
process.on('SIGINT', () => stop());
process.on('SIGTERM', () => stop());
