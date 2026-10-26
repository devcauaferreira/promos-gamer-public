'use strict';

const fs = require('node:fs');
const path = require('node:path');

const SUPPORTED_VERSION = '1.34.7';
const MESSAGE_BLOCK = `        const message = {
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
        };`;
const FOLLOWING_COMMENT = "        // Bot's won't reply if canonicalUrl is set (linking)";
const FIX = '        delete message.__x_id;';

function count(source, needle) {
    return source.split(needle).length - 1;
}

/** Apply only the known 1.34.7 media-id fix; never guess at changed upstream code. */
function patchSource(source, version) {
    if (version !== SUPPORTED_VERSION) {
        throw new Error('Unsupported whatsapp-web.js version for the media patch.');
    }
    if (typeof source !== 'string') {
        throw new TypeError('Expected whatsapp-web.js source text.');
    }
    const eol = source.includes('\r\n') ? '\r\n' : '\n';
    const block = MESSAGE_BLOCK.replace(/\n/g, eol);
    const original = `${block}${eol}${eol}${FOLLOWING_COMMENT}`;
    const patched = `${block}${eol}${FIX}${eol}${eol}${FOLLOWING_COMMENT}`;

    if (count(source, '        const message = {') !== 1 ||
        count(source, FOLLOWING_COMMENT) !== 1 || count(source, block) !== 1) {
        throw new Error('The whatsapp-web.js media patch anchors are missing or ambiguous.');
    }
    if (count(source, patched) === 1 && count(source, 'delete message.__x_id') === 1) return source;
    if (count(source, original) !== 1 || count(source, 'delete message.__x_id') !== 0) {
        throw new Error('The whatsapp-web.js media patch target has unexpected changes.');
    }
    return source.replace(original, patched);
}

function main() {
    const packagePath = require.resolve('whatsapp-web.js/package.json');
    const {version} = JSON.parse(fs.readFileSync(packagePath, 'utf8'));
    const utilsPath = path.join(path.dirname(packagePath), 'src', 'util', 'Injected', 'Utils.js');
    const source = fs.readFileSync(utilsPath, 'utf8');
    const patched = patchSource(source, version);
    if (patched !== source) fs.writeFileSync(utilsPath, patched, 'utf8');
    console.log(patched === source ? 'WhatsApp media patch already applied.' : 'WhatsApp media patch applied.');
}

module.exports = {patchSource};

if (require.main === module) {
    try {
        main();
    } catch {
        // Keep installation failures actionable without leaking paths or source contents.
        console.error('WhatsApp media patch failed: verify the pinned dependency and patch anchors.');
        process.exitCode = 1;
    }
}
