const SAFE_PROVIDER_ERRORS = new Set(['invalid_client','invalid_grant','invalid_scope','invalid_request',
  'unsupported_grant_type','forbidden','local_rate_limited','unauthorized_client','unauthorized_application',
  'invalid_operator_user_id','access_denied']);

export class OAuthFailure extends Error {
  constructor(code, providerStatus = null, providerCode = null) {
    super(code);
    this.code = code;
    this.providerStatus = providerStatus;
    this.providerCode = SAFE_PROVIDER_ERRORS.has(providerCode) ? providerCode : null;
  }
}

export async function exchangeTokens(parameters, credentials, fetcher = fetch) {
  let response;
  try {
    response = await fetcher('https://api.mercadolibre.com/oauth/token', {
      method:'POST', redirect:'error', signal:AbortSignal.timeout(20000),
      headers:{'Content-Type':'application/x-www-form-urlencoded', Accept:'application/json'},
      body:new URLSearchParams({...parameters, client_id:credentials.clientId, client_secret:credentials.clientSecret})
    });
  } catch { throw new OAuthFailure('token_exchange_network_failure'); }
  let data;
  try { data = await response.json(); }
  catch { throw new OAuthFailure('token_exchange_invalid_response',response.status); }
  if (!response.ok) throw new OAuthFailure('token_exchange_rejected',response.status,data?.error);
  if (typeof data?.access_token !== 'string' || !data.access_token ||
      !Number.isFinite(data.expires_in) || data.expires_in <= 0)
    throw new OAuthFailure('token_exchange_invalid_response',response.status);
  if (typeof data.refresh_token !== 'string' || !data.refresh_token)
    throw new OAuthFailure('offline_access_missing',response.status);
  return data;
}

export function safeFailure(error, phase, id) {
  return {id, phase, code:error instanceof OAuthFailure ? error.code : 'internal_operation_failed',
    provider_status:error instanceof OAuthFailure ? error.providerStatus : null,
    provider_code:error instanceof OAuthFailure ? error.providerCode : null};
}
