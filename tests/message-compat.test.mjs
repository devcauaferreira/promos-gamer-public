import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const {installMessageKeyCompatibility} = require('../publishers/message_compat.cjs');

test('new message key preserves native key through compatible getter',()=>{
  class Key {toString(){return 'true_group@' + 'g.us_ABC';}}
  globalThis.window = {require:()=>Key};
  try {
    assert.equal(installMessageKeyCompatibility(),true);
    const key = new Key();
    assert.equal(key._serialized,key.toString());
    key.$1 = 'true_group@g.us_DEF';
    assert.equal(key._serialized,key.$1);
    key._serialized = 'legacy_key';
    assert.equal(key._serialized,'legacy_key');
    assert.equal(installMessageKeyCompatibility(),false);
  } finally {delete globalThis.window;}
});
test('existing native getter is preserved',()=>{
  class Key {get _serialized(){return 'native';}}
  globalThis.window = {require:()=>Key};
  try { assert.equal(installMessageKeyCompatibility(),false); assert.equal(new Key()._serialized,'native'); }
  finally {delete globalThis.window;}
});
