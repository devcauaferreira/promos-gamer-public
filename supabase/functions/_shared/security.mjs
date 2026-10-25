export function randomToken(bytes = 32) {
  return b64(crypto.getRandomValues(new Uint8Array(bytes))).replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '');
}
export function b64(bytes) { return btoa(String.fromCharCode(...bytes)); }
export function unb64(value) { return Uint8Array.from(atob(value), c => c.charCodeAt(0)); }
export async function digest(value) {
  return new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)));
}
export async function hash(value) { return Array.from(await digest(value), b => b.toString(16).padStart(2, '0')).join(''); }
export async function authorized(request, secret) {
  if (!secret || secret.length < 32) return false;
  const supplied = request.headers.get('authorization') || '';
  const a = await digest(supplied), b = await digest('Bearer ' + secret);
  let difference = 0;
  for (let i = 0; i < a.length; i++) difference |= a[i] ^ b[i];
  return difference === 0;
}
async function key(value) {
  const bytes = unb64(value);
  if (bytes.length !== 32) throw new Error('Invalid encryption key');
  return crypto.subtle.importKey('raw', bytes, 'AES-GCM', false, ['encrypt', 'decrypt']);
}
export async function seal(data, encryptionKey) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const bytes = await crypto.subtle.encrypt({name:'AES-GCM', iv}, await key(encryptionKey), new TextEncoder().encode(JSON.stringify(data)));
  return b64(iv) + '.' + b64(new Uint8Array(bytes));
}
export async function unseal(value, encryptionKey) {
  const [iv, data] = value.split('.');
  const bytes = await crypto.subtle.decrypt({name:'AES-GCM', iv:unb64(iv)}, await key(encryptionKey), unb64(data));
  return JSON.parse(new TextDecoder().decode(bytes));
}
export async function authorizationUrl(clientId, redirectUri, state, verifier) {
  const target = new URL(redirectUri);
  if (target.protocol !== 'https:' || target.search || target.hash || target.username || target.password)
    throw new Error('Redirect must be static HTTPS');
  const challenge = b64(await digest(verifier)).replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '');
  const url = new URL('https://auth.mercadolivre.com.br/authorization');
  url.search = new URLSearchParams({response_type:'code', client_id:clientId, redirect_uri:redirectUri,
    state, scope:'read offline_access', code_challenge:challenge, code_challenge_method:'S256'}).toString();
  return url.toString();
}
export function callbackInputs(url) {
  const state = url.searchParams.get('state');
  const code = url.searchParams.get('code');
  if (url.searchParams.getAll('state').length !== 1 || !state || !/^[A-Za-z0-9_-]{43}$/.test(state))
    throw new Error('Invalid state');
  if (url.searchParams.getAll('code').length > 1 || (!code && !url.searchParams.has('error')) || (code && code.length > 2048))
    throw new Error('Invalid callback');
  return {state, code, denied:url.searchParams.has('error')};
}
export function json(data, status = 200) {
  return new Response(JSON.stringify(data), {status, headers:{'Content-Type':'application/json',
    'Cache-Control':'no-store', 'Referrer-Policy':'no-referrer', 'X-Content-Type-Options':'nosniff'}});
}
