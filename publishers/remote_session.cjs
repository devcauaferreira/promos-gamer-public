const crypto = require('node:crypto');
const fs = require('node:fs/promises');
const path = require('node:path');

const MAX_BYTES = 40 * 1024 * 1024;
const CHUNK_BYTES = 8 * 1024 * 1024;
const MAX_CHUNKS = 32;
function sessionKey(value) {
  const key = Buffer.from(value || '', 'base64');
  if (key.length !== 32) throw new Error('Configure WHATSAPP_SESSION_KEY com 32 bytes em base64');
  return key;
}
function encrypt(bytes, key) {
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv('aes-256-gcm', key, iv);
  cipher.setAAD(Buffer.from('promos-whatsapp-v1'));
  return Buffer.concat([Buffer.from('PWA1'), iv, cipher.update(bytes), cipher.final(), cipher.getAuthTag()]);
}
function decrypt(bytes, key) {
  if (bytes.length < 32 || bytes.subarray(0, 4).toString() !== 'PWA1') throw new Error('Arquivo de sessão inválido');
  const decipher = crypto.createDecipheriv('aes-256-gcm', key, bytes.subarray(4, 16));
  decipher.setAAD(Buffer.from('promos-whatsapp-v1'));
  decipher.setAuthTag(bytes.subarray(-16));
  return Buffer.concat([decipher.update(bytes.subarray(16, -16)), decipher.final()]);
}
class RemoteSessionStore {
  constructor({url, token, key, dataPath}) {
    const parsed = new URL(url);
    if (parsed.protocol !== 'https:' || !parsed.hostname.endsWith('.supabase.co') || parsed.pathname !== '/' || parsed.search || parsed.hash || parsed.username || parsed.password)
      throw new Error('URL Supabase inválida');
    if (!token || token.length < 32) throw new Error('BOT_API_SECRET ausente');
    this.url = parsed.origin + '/functions/v1/whatsapp-session';
    this.token = token;
    this.key = sessionKey(key);
    this.dataPath = path.resolve(dataPath);
  }
  async request(method, resource = '', body) {
    const response = await fetch(this.url + resource, {method, body, redirect:'error',
      headers:{Authorization:'Bearer ' + this.token, 'Content-Type':'application/octet-stream'},
      signal:AbortSignal.timeout(60000)});
    if (response.status === 404 && ['GET','HEAD'].includes(method)) return null;
    if (!response.ok) throw new Error('Persistência WhatsApp HTTP ' + response.status);
    if (method === 'HEAD' || method === 'DELETE') return Buffer.alloc(0);
    if (Number(response.headers.get('content-length')) > MAX_BYTES) throw new Error('Sessão muito grande');
    const bytes = Buffer.from(await response.arrayBuffer());
    if (bytes.length > MAX_BYTES) throw new Error('Sessão muito grande');
    return bytes;
  }
  validateSession(session) {
    if (session !== 'RemoteAuth-promos-gamer') throw new Error('Nome de sessão inválido');
  }
  async sessionExists({session}) {
    this.validateSession(session);
    return await this.request('HEAD') !== null;
  }
  async readManifest() {
    const bytes = await this.request('GET', '/manifest');
    if (!bytes) return null;
    let value;
    try { value = JSON.parse(decrypt(bytes, this.key)); }
    catch { throw new Error('Manifesto da sessão inválido'); }
    if (!value || value.version !== 2 || !/^[a-f0-9]{32}$/.test(value.generation)
        || !Number.isInteger(value.length) || value.length < 1 || value.length > CHUNK_BYTES * MAX_CHUNKS
        || value.chunks !== Math.ceil(value.length / CHUNK_BYTES)
        || !/^[a-f0-9]{64}$/.test(value.sha256)) throw new Error('Manifesto da sessão inválido');
    return value;
  }
  chunkPath(generation, index) { return `/chunk/${generation}/${index}`; }
  async save({session}) {
    this.validateSession(session);
    const archive = await fs.readFile(path.join(this.dataPath, session + '.zip'));
    if (!archive.length || archive.length > CHUNK_BYTES * MAX_CHUNKS)
      throw new Error('Sessão excede 256 MB');
    const old = await this.readManifest();
    const generation = crypto.randomBytes(16).toString('hex');
    const chunks = Math.ceil(archive.length / CHUNK_BYTES);
    let uploaded = 0;
    let commitStarted = false;
    try {
      for (let index = 0; index < chunks; index++) {
        const chunk = archive.subarray(index * CHUNK_BYTES, (index + 1) * CHUNK_BYTES);
        await this.request('PUT', this.chunkPath(generation, index), encrypt(chunk, this.key));
        uploaded++;
      }
      const manifest = {version:2, generation, length:archive.length, chunks,
        sha256:crypto.createHash('sha256').update(archive).digest('hex')};
      // O manifesto é a troca atômica: até aqui a sessão antiga permanece válida.
      commitStarted = true;
      await this.request('PUT', '/manifest', encrypt(Buffer.from(JSON.stringify(manifest)), this.key));
    } catch (error) {
      if (!commitStarted) await Promise.allSettled(Array.from({length:uploaded},(_,index)=>
        this.request('DELETE', this.chunkPath(generation, index))));
      throw error;
    }
    if (old) for (let index = 0; index < old.chunks; index++)
      await this.request('DELETE', this.chunkPath(old.generation, index));
    else if (await this.request('HEAD', '/legacy') !== null) await this.request('DELETE', '/legacy');
  }
  async extract({session, path:target}) {
    this.validateSession(session);
    if (path.resolve(target) !== path.join(this.dataPath, session + '.zip')) throw new Error('Destino de sessão inválido');
    const manifest = await this.readManifest();
    let archive;
    if (manifest) {
      const parts = [];
      for (let index = 0; index < manifest.chunks; index++) {
        const bytes = await this.request('GET', this.chunkPath(manifest.generation, index));
        if (!bytes) throw new Error('Parte da sessão ausente');
        parts.push(decrypt(bytes, this.key));
      }
      archive = Buffer.concat(parts);
      if (archive.length !== manifest.length ||
          crypto.createHash('sha256').update(archive).digest('hex') !== manifest.sha256)
        throw new Error('Sessão remota incompleta');
    } else {
      const bytes = await this.request('GET', '/legacy');
      if (!bytes) throw new Error('Sessão remota ausente');
      archive = decrypt(bytes, this.key);
    }
    await fs.mkdir(this.dataPath, {recursive:true,mode:0o700});
    await fs.writeFile(target, archive, {mode:0o600});
  }
  async delete({session}) {
    this.validateSession(session);
    const manifest = await this.readManifest();
    await this.request('DELETE', '/manifest');
    await this.request('DELETE', '/legacy');
    if (manifest) for (let index = 0; index < manifest.chunks; index++)
      await this.request('DELETE', this.chunkPath(manifest.generation, index));
  }
  async saveQR(dataURL) {
    const bytes = Buffer.from(JSON.stringify({dataURL, created_at:Date.now()}));
    await this.request('PUT', '/qr', encrypt(bytes, this.key));
  }
  async readQR() {
    const bytes = await this.request('GET', '/qr');
    if (!bytes) return null;
    const data = JSON.parse(decrypt(bytes, this.key));
    if (Date.now() - data.created_at > 60000 || !data.dataURL?.startsWith('data:image/png;base64,')) return null;
    return data.dataURL;
  }
  async clearQR() { await this.request('DELETE', '/qr'); }
}
module.exports = {RemoteSessionStore, encrypt, decrypt, sessionKey};
