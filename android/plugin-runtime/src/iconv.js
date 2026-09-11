/**
 * 插件运行时 —— iconv-lite 兼容层
 * ================================
 * 中文音源普遍需要 GBK / GB18030 / BIG5 解码，而 iconv-lite 的浏览器版只支持
 * utf8/utf16，直接用会解出乱码。
 * 好在 WebView 里原生的 TextDecoder 已实现 WHATWG Encoding 标准，完整支持
 * gbk / gb18030 / big5 / euc-kr / shift_jis / euc-jp / windows-1252 等，
 * 所以这里把 iconv-lite 的 API 桥接到 TextDecoder 上即可。
 */

// iconv-lite 的编码别名 -> TextDecoder 可识别的标签
const ALIAS = {
  'utf8': 'utf-8',
  'utf-8': 'utf-8',
  'utf16le': 'utf-16le',
  'utf-16le': 'utf-16le',
  'ucs2': 'utf-16le',
  'ucs-2': 'utf-16le',
  'utf16be': 'utf-16be',
  'utf-16be': 'utf-16be',
  'latin1': 'windows-1252',
  'binary': 'windows-1252',
  'iso-8859-1': 'windows-1252',
  'ascii': 'windows-1252',
  'gbk': 'gbk',
  'cp936': 'gbk',
  'gb2312': 'gbk',
  'gb18030': 'gb18030',
  'big5': 'big5',
  'big5-hkscs': 'big5',
  'cp950': 'big5',
  'shift_jis': 'shift_jis',
  'shift-jis': 'shift_jis',
  'sjis': 'shift_jis',
  'cp932': 'shift_jis',
  'euc-jp': 'euc-jp',
  'euc-kr': 'euc-kr',
  'cp949': 'euc-kr',
  'koi8-r': 'koi8-r',
  'koi8-u': 'koi8-u',
  'windows-1250': 'windows-1250',
  'windows-1251': 'windows-1251',
  'windows-1252': 'windows-1252',
  'windows-1253': 'windows-1253',
  'windows-1254': 'windows-1254',
  'windows-1255': 'windows-1255',
  'windows-1256': 'windows-1256',
  'windows-1257': 'windows-1257',
  'windows-1258': 'windows-1258',
  'iso-8859-2': 'iso-8859-2',
  'iso-8859-3': 'iso-8859-3',
  'iso-8859-4': 'iso-8859-4',
  'iso-8859-5': 'iso-8859-5',
  'iso-8859-6': 'iso-8859-6',
  'iso-8859-7': 'iso-8859-7',
  'iso-8859-8': 'iso-8859-8',
  'iso-8859-9': 'iso-8859-9',
  'iso-8859-10': 'iso-8859-10',
  'iso-8859-13': 'iso-8859-13',
  'iso-8859-14': 'iso-8859-14',
  'iso-8859-15': 'iso-8859-15',
  'iso-8859-16': 'iso-8859-16',
};

const decoderCache = new Map();

function labelOf(enc) {
  const k = String(enc == null ? 'utf-8' : enc).trim().toLowerCase().replace(/[_\s]/g, '-');
  return ALIAS[k] || k;
}

function getDecoder(enc) {
  const label = labelOf(enc);
  if (decoderCache.has(label)) return decoderCache.get(label);
  let dec;
  try {
    dec = new TextDecoder(label, { fatal: false, ignoreBOM: false });
  } catch (e) {
    try {
      dec = new TextDecoder('utf-8', { fatal: false });
    } catch (e2) {
      dec = null;
    }
  }
  decoderCache.set(label, dec);
  return dec;
}

export function toUint8(buf) {
  if (buf == null) return new Uint8Array(0);
  if (buf instanceof Uint8Array) return buf;
  if (buf instanceof ArrayBuffer) return new Uint8Array(buf);
  if (ArrayBuffer.isView(buf)) return new Uint8Array(buf.buffer, buf.byteOffset, buf.byteLength);
  if (Array.isArray(buf)) return new Uint8Array(buf);
  if (typeof buf === 'string') return new TextEncoder().encode(buf);
  return new Uint8Array(0);
}

function decode(buf, encoding) {
  const u8 = toUint8(buf);
  if (!u8.length) return '';
  const dec = getDecoder(encoding);
  if (!dec) return '';
  try {
    return dec.decode(u8);
  } catch (e) {
    return '';
  }
}

function encode(str, encoding) {
  const label = labelOf(encoding);
  if (label === 'utf-8' || label === 'utf-16le') {
    const u8 = new TextEncoder().encode(String(str));
    return Buffer.from(u8);
  }
  // 非 UTF 编码的"编码"极少被插件使用；GBK 等无法用 TextEncoder 生成。
  // 退化为 UTF-8，避免直接抛错中断整个流程。
  return Buffer.from(new TextEncoder().encode(String(str)));
}

function encodingExists(name) {
  return !!getDecoder(name);
}

function decodeStream() {
  throw new Error('iconv-lite 流式接口在 App 内不支持');
}

const iconv = {
  decode,
  encode,
  encodingExists,
  decodeStream,
  getDecoder,
  getEncoder: () => ({ write: encode, end: () => {}, convert: encode }),
  default: null,
};
iconv.default = iconv;
iconv.__esModule = true;

export default iconv;
