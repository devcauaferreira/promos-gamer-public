async function confirmedMessageId(message, {sleep = ms=>new Promise(resolve=>setTimeout(resolve,ms)), attempts = 20} = {}) {
  const id = message?.id?._serialized || message?.id?.$1;
  if (typeof id !== 'string' || !id) throw new Error('Envio sem identificador; resultado incerto');
  for (let attempt = 0; attempt <= attempts; attempt++) {
    if (message.ack >= 1) return id;
    if (message.ack === -1) throw new Error('Mensagem rejeitada pelo WhatsApp');
    if (attempt === attempts) break;
    await sleep(1000);
    const reloaded = await message.reload();
    if (!reloaded) break;
    message = reloaded;
  }
  throw new Error('Sem confirmação do servidor; resultado incerto, não repetir automaticamente');
}
module.exports = {confirmedMessageId};
