import test from 'node:test';
import assert from 'node:assert/strict';
import {exchangeTokens,OAuthFailure,safeFailure} from '../supabase/functions/_shared/oauth.mjs';

const credentials = {clientId:'123',clientSecret:'DO-NOT-LOG'};
test('troca do código preserva tokens somente em resultado válido', async () => {
  let calls = 0;
  const tokens = await exchangeTokens({grant_type:'authorization_code',code:'PRIVATE-CODE'},credentials,
    async (url,options) => {
      calls++;
      assert.equal(options.redirect,'error');
      assert.equal(new URLSearchParams(options.body).get('client_secret'),credentials.clientSecret);
      return Response.json({access_token:'PRIVATE-ACCESS',refresh_token:'PRIVATE-REFRESH',expires_in:21600});
    });
  assert.equal(calls,1);
  assert.equal(tokens.expires_in,21600);
});
test('invalid_client é identificado sem vazar mensagem, código ou token', async () => {
  try {
    await exchangeTokens({code:'PRIVATE-CODE'},credentials,
      async () => Response.json({error:'invalid_client',message:'DO-NOT-LOG PRIVATE-CODE'}, {status:400}));
    assert.fail('Expected failure');
  } catch (error) {
    const safe = safeFailure(error,'authorization_exchange','reference');
    assert.equal(safe.provider_code,'invalid_client');
    assert.equal(safe.provider_status,400);
    assert.ok(!JSON.stringify(safe).includes('PRIVATE-CODE'));
    assert.ok(!JSON.stringify(safe).includes('DO-NOT-LOG'));
  }
});
test('falta de refresh token gera diagnóstico específico de offline_access', async () => {
  await assert.rejects(exchangeTokens({},credentials,
    async () => Response.json({access_token:'PRIVATE',expires_in:21600})),
    error => error instanceof OAuthFailure && error.code==='offline_access_missing');
});
test('erro desconhecido do provedor é omitido e a troca nunca é repetida', async () => {
  let calls = 0;
  try {
    await exchangeTokens({},credentials,async () => {
      calls++; return Response.json({error:'PRIVATE-SECRET'}, {status:403});
    });
  } catch(error) {
    assert.equal(safeFailure(error,'authorization_exchange','id').provider_code,null);
  }
  assert.equal(calls,1);
});
