import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const {confirmedMessageId} = require('../publishers/message_confirmation.cjs');

test('a locally queued message is successful only after server acknowledgement',async()=>{
  const message={id:{_serialized:'true_group@g.us_ID'},ack:0};
  message.reload = async()=>{message.ack=1;return message;};
  assert.equal(await confirmedMessageId(message,{sleep:async()=>{}}),message.id._serialized);
});
test('missing id, rejected or permanently pending message never reports success',async()=>{
  await assert.rejects(confirmedMessageId(undefined));
  await assert.rejects(confirmedMessageId({id:{_serialized:'id'},ack:-1}));
  const message={id:{_serialized:'id'},ack:0};
  message.reload=async()=>message;
  await assert.rejects(confirmedMessageId(message,{sleep:async()=>{},attempts:2}),/Sem confirmação/);
});
