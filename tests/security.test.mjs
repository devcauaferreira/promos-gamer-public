import test from 'node:test';
import assert from 'node:assert/strict';
import {randomToken, seal, unseal, b64, authorized, authorizationUrl, callbackInputs} from '../supabase/functions/_shared/security.mjs';

test('state tem entropia e validação estrita', () => {
  const state = randomToken();
  assert.equal(state.length,43);
  assert.notEqual(state,randomToken());
  assert.equal(callbackInputs(new URL(`https://example.com/callback?state=${state}&code=abc`)).state,state);
  for (const query of ['code=abc', 'state=short&code=abc', `state=${state}&state=${state}&code=abc`])
    assert.throws(() => callbackInputs(new URL('https://example.com/?'+query)));
});
test('tokens são cifrados com AES-GCM e alterações são rejeitadas', async () => {
  const key = b64(crypto.getRandomValues(new Uint8Array(32)));
  const data = {access_token:'private-access',refresh_token:'private-refresh'};
  const encrypted = await seal(data,key);
  assert.ok(!encrypted.includes('private'));
  assert.deepEqual(await unseal(encrypted,key),data);
  const [iv,cipher] = encrypted.split('.');
  await assert.rejects(unseal(iv+'.'+(cipher[0]==='A'?'B':'A')+cipher.slice(1),key));
});
test('rotas administrativas exigem segredo privado', async () => {
  const secret = randomToken();
  assert.equal(await authorized(new Request('https://example.com'),secret),false);
  assert.equal(await authorized(new Request('https://example.com',{headers:{Authorization:'Bearer '+secret}}),secret),true);
  assert.equal(await authorized(new Request('https://example.com',{headers:{Authorization:'Bearer wrong'}}),secret),false);
});
test('OAuth usa HTTPS estático, state e PKCE S256', async () => {
  const state = randomToken(), verifier = randomToken(48);
  const uri = 'https://project.supabase.co/functions/v1/mercadolivre-callback';
  const url = new URL(await authorizationUrl('123',uri,state,verifier));
  assert.equal(url.hostname,'auth.mercadolivre.com.br');
  assert.equal(url.searchParams.get('redirect_uri'),uri);
  assert.equal(url.searchParams.get('code_challenge_method'),'S256');
  assert.equal(url.searchParams.get('scope'),'read offline_access');
  assert.equal(url.searchParams.get('state'),state);
  assert.notEqual(url.searchParams.get('code_challenge'),verifier);
  await assert.rejects(authorizationUrl('123','http://localhost/callback',state,verifier));
  await assert.rejects(authorizationUrl('123',uri+'?varying=1',state,verifier));
});
