import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
import path from 'node:path';

const require = createRequire(import.meta.url);
const {patchSource} = require('../scripts/patch_wwebjs_media.cjs');
// This fixture is the upstream 1.34.7 construction, including its spread order.
const fixture = `before();
        const message = {
            ...options,
            id: newMsgKey,
            ack: 0,
            body: content,
            from: from,
            to: chat.id,
            local: true,
            self: 'out',
            t: parseInt(new Date().getTime() / 1000),
            isNewMsg: true,
            type: 'chat',
            ...ephemeralFields,
            ...mediaOptions,
            ...(mediaOptions.toJSON ? mediaOptions.toJSON() : {}),
            ...quotedMsgOptions,
            ...locationOptions,
            ...pollOptions,
            ...eventOptions,
            ...vcardOptions,
            ...buttonOptions,
            ...listOptions,
            ...botOptions,
            ...extraOptions,
        };

        // Bot's won't reply if canonicalUrl is set (linking)
after();
`;

function buildMessage(source, mediaOptions = {}) {
    const start = source.indexOf('        const message = {');
    const end = source.indexOf("        // Bot's won't reply");
    const variables = {
        options: {}, newMsgKey: {id: 'real-message-key'}, content: 'Product caption',
        from: 'sender', chat: {id: 'destination'}, ephemeralFields: {}, mediaOptions,
        quotedMsgOptions: {}, locationOptions: {}, pollOptions: {}, eventOptions: {},
        vcardOptions: {}, buttonOptions: {}, listOptions: {}, botOptions: {}, extraOptions: {},
    };
    const names = Object.keys(variables);
    const build = new Function(...names, `${source.slice(start, end)}\nreturn message;`);
    return {message: build(...Object.values(variables)), realId: variables.newMsgKey};
}

// The upstream model consumes __x_ fields as attributes, so a copied media __x_id
// can replace the freshly generated id even though message.id is correct initially.
function hydrateModel(message) {
    const attributes = {};
    for (const [key, value] of Object.entries(message)) {
        attributes[key.startsWith('__x_') ? key.slice(4) : key] = value;
    }
    return attributes;
}

test('patch removes only the media id alias and preserves the real id and upload fields', () => {
    const mediaId = {id: 'temporary-upload-key'};
    const media = {
        __x_id: mediaId, mimetype: 'image/jpeg', directPath: '/upload/fixture',
        mediaKey: 'fixture-key', filehash: 'fixture-hash', size: 123,
        toJSON() { return {__x_id: mediaId, uploadhash: 'fixture-upload-hash'}; },
    };
    assert.equal(hydrateModel(buildMessage(fixture, media).message).id, mediaId);
    const {message, realId} = buildMessage(patchSource(fixture, '1.34.7'), media);
    assert.equal(message.id, realId);
    assert.equal(hydrateModel(message).id, realId);
    assert.equal(Object.hasOwn(message, '__x_id'), false);
    for (const key of ['mimetype', 'directPath', 'mediaKey', 'filehash', 'size']) {
        assert.equal(message[key], media[key]);
    }
    assert.equal(message.uploadhash, 'fixture-upload-hash');
    assert.equal(message.body, 'Product caption');
    assert.equal(media.__x_id, mediaId, 'patch must not mutate the upload object');
});

test('text-only construction preserves its fields and does not add an id alias', () => {
    const {message: original} = buildMessage(fixture);
    const {message: patched} = buildMessage(patchSource(fixture, '1.34.7'));
    // Timestamps can cross a second boundary while these two fixtures execute.
    assert.equal(typeof patched.t, 'number');
    delete original.t;
    delete patched.t;
    assert.deepEqual(patched, original);
    assert.equal(hydrateModel(patched).id, patched.id);
});

test('patch is idempotent, inserts immediately after the object, and preserves line endings', () => {
    for (const source of [fixture, fixture.replace(/\n/g, '\r\n')]) {
        const patched = patchSource(source, '1.34.7');
        const eol = source.includes('\r\n') ? '\r\n' : '\n';
        assert.ok(patched.includes(`        };${eol}        delete message.__x_id;${eol}${eol}`));
        assert.equal(patchSource(patched, '1.34.7'), patched);
        assert.equal(patched.replace(`        delete message.__x_id;${eol}`, ''), source);
    }
});

test('unsupported dependency versions fail closed even if the source is already patched', () => {
    for (const version of ['1.34.6', '1.34.8', '^1.34.7', '', undefined]) {
        assert.throws(() => patchSource(fixture, version), /Unsupported/);
        assert.throws(() => patchSource(patchSource(fixture, '1.34.7'), version), /Unsupported/);
    }
});

test('missing, changed, repeated or misplaced anchors fail closed', () => {
    const invalidSources = [
        fixture.replace('id: newMsgKey,', 'id: changedKey,'),
        fixture.replace("Bot's won't reply", 'changed comment'),
        fixture + fixture,
        fixture + '        const message = {\n',
        fixture + "        // Bot's won't reply if canonicalUrl is set (linking)\n",
        fixture + '        delete message.__x_id;\n',
        fixture.replace('        };\n\n', '        };\n        changed();\n\n'),
        patchSource(fixture, '1.34.7') + '        delete message.__x_id;\n',
        patchSource(fixture, '1.34.7') + 'delete message.__x_id;\n',
    ];
    for (const source of invalidSources) {
        assert.throws(() => patchSource(source, '1.34.7'), /anchors|unexpected changes/);
    }
    assert.throws(() => patchSource(null, '1.34.7'), /source text/);
});

test('installed pinned source accepts the patch without modifying the dependency file', () => {
    const packagePath = require.resolve('whatsapp-web.js/package.json');
    const {version} = JSON.parse(readFileSync(packagePath, 'utf8'));
    assert.equal(version, '1.34.7');
    const sourcePath = path.join(path.dirname(packagePath), 'src', 'util', 'Injected', 'Utils.js');
    const original = readFileSync(sourcePath, 'utf8');
    const patched = patchSource(original, version);
    assert.equal(patchSource(patched, version), patched);
    assert.equal(readFileSync(sourcePath, 'utf8'), original);
    assert.equal((patched.match(/delete message\.__x_id;/g) || []).length, 1);
});
