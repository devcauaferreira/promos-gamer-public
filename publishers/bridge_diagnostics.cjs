'use strict';

// Convert private runtime errors to fixed codes safe for workflow summaries.
function classifyBridgeError(error) {
  const message = String(error?.message || error || '').toLowerCase();
  const code = String(error?.code || '').toUpperCase();
  if (code === 'ENOENT') return 'whatsapp_browser_executable_missing';
  if (code === 'EACCES' || code === 'EPERM') return 'whatsapp_browser_launch_failed';
  if (code === 'ECONNRESET' || code === 'ETIMEDOUT' || code === 'ENOTFOUND') return 'whatsapp_session_network_error';
  const status = message.match(/http\s+(401|403|404|409|429|5\d\d)/);
  if (status) return `whatsapp_session_http_${status[1]}`;
  if (/configure whatsapp_session_key|session key|invalid key length/.test(message)) return 'whatsapp_session_key_invalid';
  if (/manifest|session archive|unable to decrypt|unsupported state or unable to authenticate data/.test(message)) return 'whatsapp_session_archive_invalid';
  if (/could not find chrome|browser was not found|executable doesn't exist|no usable sandbox/.test(message)) return 'whatsapp_browser_executable_missing';
  if (/failed to launch|spawn .* enoent|error while loading shared libraries|chrome failed to start/.test(message)) return 'whatsapp_browser_launch_failed';
  if (/protocol error|target closed|browser has disconnected|connection closed|execution context was destroyed|cannot find context/.test(message)) return 'whatsapp_browser_protocol_error';
  if (/timed out|timeout|navigation failed/.test(message)) return 'whatsapp_web_initialization_timeout';
  if (/fetch failed|econnreset|enotfound|eai_again|etimedout|network error/.test(message)) return 'whatsapp_session_network_error';
  if (/cannot find module|module not found/.test(message)) return 'whatsapp_dependency_missing';
  return 'whatsapp_initialization_failed';
}

function logBridgeDiagnostic(error) {
  console.error('Bridge startup diagnostic: ' + classifyBridgeError(error));
}

module.exports = {classifyBridgeError, logBridgeDiagnostic};
