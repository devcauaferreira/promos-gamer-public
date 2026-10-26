import {createRequire} from 'node:module';
import test from 'node:test';
import assert from 'node:assert/strict';
const require = createRequire(import.meta.url);
const {classifyBridgeError} = require('../publishers/bridge_diagnostics.cjs');

test('bridge errors map to fixed diagnostics without exposing message content', () => {
  assert.equal(classifyBridgeError(new Error('Persistência WhatsApp HTTP 403 secret-token')), 'whatsapp_session_http_403');
  assert.equal(classifyBridgeError(new Error('Failed to launch the browser process! private path')), 'whatsapp_browser_launch_failed');
  assert.equal(classifyBridgeError(new Error('Protocol error (Target.createTarget): Target closed')), 'whatsapp_browser_protocol_error');
  assert.equal(classifyBridgeError(new Error('unexpected private exception')), 'whatsapp_initialization_failed');
});
