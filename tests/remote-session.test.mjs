import {test} from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const {encrypt,decrypt,RemoteSessionStore} = require('../publishers/remote_session.cjs');

test('session encryption authenticates bytes and rejects tampering or wrong key',()=>{
  const key = crypto.randomBytes(32);
  const plain = Buffer.from('private browser session');
  const sealed = encrypt(plain,key);
  assert.deepEqual(decrypt(sealed,key),plain);
  assert.equal(sealed.includes(plain),false);
  const modified = Buffer.from(sealed); modified[20] ^= 1;
  assert.throws(()=>decrypt(modified,key));
  assert.throws(()=>decrypt(sealed,crypto.randomBytes(32)));
  assert.throws(()=>decrypt(Buffer.from('bad'),key));
});
test('remote store restricts destination and session name',()=>{
  const config={url:'https://example.supabase.co',token:'x'.repeat(32),key:crypto.randomBytes(32).toString('base64'),dataPath:'.wwebjs_auth_cloud'};
  const store = new RemoteSessionStore(config);
  assert.throws(()=>store.validateSession('../../secret'));
  for (const url of ['http://example.supabase.co','https://example.com','https://example.supabase.co/other'])
    assert.throws(()=>new RemoteSessionStore({...config,url}));
});
test('only reads may treat 404 as missing; uploads fail closed',async()=>{
  const old = globalThis.fetch;
  const store = new RemoteSessionStore({url:'https://example.supabase.co',token:'x'.repeat(32),
    key:crypto.randomBytes(32).toString('base64'),dataPath:'.wwebjs_auth_cloud'});
  globalThis.fetch = async(url,options)=>{
    assert.equal(options.redirect,'error');
    return {status:404,ok:false};
  };
  try {
    assert.equal(await store.request('HEAD'),null);
    await assert.rejects(store.request('PUT','',Buffer.from('data')),/HTTP 404/);
    await assert.rejects(store.request('DELETE'),/HTTP 404/);
  } finally {globalThis.fetch = old;}
});
test('restoration creates a missing auth directory on a fresh runner',async()=>{
  const folder = await fs.mkdtemp(path.join(os.tmpdir(),'promos-session-test-'));
  try {
    const dataPath = path.join(folder,'auth');
    const store = new RemoteSessionStore({url:'https://example.supabase.co',token:'x'.repeat(32),
      key:crypto.randomBytes(32).toString('base64'),dataPath});
    const content = Buffer.from('private archive bytes');
    store.request = async(method,resource)=> resource === '/manifest' ? null : encrypt(content,store.key);
    const target = path.join(dataPath,'RemoteAuth-promos-gamer.zip');
    await store.extract({session:'RemoteAuth-promos-gamer',path:target});
    assert.deepEqual(await fs.readFile(target),content);
    await assert.rejects(store.extract({session:'RemoteAuth-promos-gamer',path:path.join(folder,'wrong.zip')}));
  } finally {
    if (!path.resolve(folder).startsWith(path.join(path.resolve(os.tmpdir()),'promos-session-test-'))) throw new Error('Unsafe test cleanup');
    await fs.rm(folder,{recursive:true,force:true});
  }
});
test('large session saves encrypted chunks and restores only after manifest commit',async()=>{
  const folder = await fs.mkdtemp(path.join(os.tmpdir(),'promos-session-test-'));
  try {
    const dataPath = path.join(folder,'auth');
    await fs.mkdir(dataPath);
    const target = path.join(dataPath,'RemoteAuth-promos-gamer.zip');
    const original = crypto.randomBytes(8 * 1024 * 1024 + 25);
    await fs.writeFile(target,original);
    const store = new RemoteSessionStore({url:'https://example.supabase.co',token:'x'.repeat(32),
      key:crypto.randomBytes(32).toString('base64'),dataPath});
    const objects = new Map();
    let chunksAtCommit = 0;
    store.request = async(method,resource='',body)=>{
      if (method==='GET') return objects.get(resource) || null;
      if (method==='HEAD') return objects.has(resource) ? Buffer.alloc(0) : null;
      if (method==='PUT') {
        if (resource==='/manifest') chunksAtCommit=[...objects.keys()].filter(k=>k.startsWith('/chunk/')).length;
        objects.set(resource,body); return Buffer.alloc(0);
      }
      if (method==='DELETE') { objects.delete(resource); return Buffer.alloc(0); }
      throw new Error('unexpected method');
    };
    await store.save({session:'RemoteAuth-promos-gamer'});
    assert.equal(chunksAtCommit,2);
    await fs.rm(target);
    await store.extract({session:'RemoteAuth-promos-gamer',path:target});
    assert.deepEqual(await fs.readFile(target),original);
    const committed = objects.get('/manifest');
    const normalRequest = store.request;
    let writes = 0;
    store.request = async(method,resource,body)=>{
      if (method==='PUT' && resource.startsWith('/chunk/') && ++writes===2)
        throw new Error('network interrupted');
      return normalRequest(method,resource,body);
    };
    await fs.writeFile(target,crypto.randomBytes(original.length));
    await assert.rejects(store.save({session:'RemoteAuth-promos-gamer'}),/network interrupted/);
    assert.deepEqual(objects.get('/manifest'),committed);
    assert.equal([...objects.keys()].filter(k=>k.startsWith('/chunk/')).length,2);
    store.request = normalRequest;
    await store.extract({session:'RemoteAuth-promos-gamer',path:target});
    assert.deepEqual(await fs.readFile(target),original);
    const chunkKey=[...objects.keys()].find(k=>k.startsWith('/chunk/'));
    objects.set(chunkKey,Buffer.from('invalid'));
    await assert.rejects(store.extract({session:'RemoteAuth-promos-gamer',path:target}));
  } finally {
    if (!path.resolve(folder).startsWith(path.join(path.resolve(os.tmpdir()),'promos-session-test-'))) throw new Error('Unsafe test cleanup');
    await fs.rm(folder,{recursive:true,force:true});
  }
});
