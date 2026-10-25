// Compatibilidade limitada ao MsgKey da versão fixada de whatsapp-web.js.
// Referência: upstream PR 201901; não altera autenticação nem controles de acesso.
function installMessageKeyCompatibility() {
  const MsgKey = window.require('WAWebMsgKey');
  const prototype = MsgKey.prototype;
  if (Object.getOwnPropertyDescriptor(prototype, '_serialized')) return false;
  Object.defineProperty(prototype, '_serialized', {
    configurable:true,
    get() {
      if (typeof this.$1 === 'string' && this.$1) return this.$1;
      const serialized = this.toString();
      return typeof serialized === 'string' && serialized !== '[object Object]' ? serialized : undefined;
    },
    set(serialized) {
      Object.defineProperty(this, '_serialized', {value:serialized,enumerable:true,writable:true,configurable:true});
    }
  });
  return true;
}
module.exports = {installMessageKeyCompatibility};
