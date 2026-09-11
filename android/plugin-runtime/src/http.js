/**
 * 插件运行时 —— HTTP 传输层 + axios 兼容层
 * =========================================
 * 为什么不能直接用浏览器自带的 XHR/fetch 请求音源：
 *   1. 音源接口不返回 CORS 头，跨域会被 WebView 拦掉；
 *   2. 多数音源要求 Referer / Cookie / 自定义 UA，而这些头是 W3C 规范里的
 *      "禁止由 JS 设置"的请求头（Cookie、Referer、Origin 等），fetch/XHR 设了也没用。
 * 因此所有请求都改为 POST 给本地 Java 服务的 /__proxy，由原生侧带着任意头去请求，
 * 再把结果原样回灌。代理是同源的，不存在跨域问题。
 *
 * 传输层可替换：如果 globalThis.__PH_TRANSPORT__ 存在则用它（PC 上跑测试用，
 * 直接用 Node 的 http 直连，无 CORS 概念）。
 */

const DEFAULT_TIMEOUT = 20000;
const MAX_BODY = 64 * 1024 * 1024;

export function bytesToBase64(u8) {
  let out = '';
  const CHUNK = 0x8000;
  for (let i = 0; i < u8.length; i += CHUNK) {
    out += String.fromCharCode.apply(null, u8.subarray(i, i + CHUNK));
  }
  return btoa(out);
}

export function base64ToBytes(b64) {
  const bin = atob(b64);
  const u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  return u8;
}

/** 把各种形态的 body 统一成 Uint8Array / null */
export function toBytes(body) {
  if (body == null) return null;
  if (body instanceof Uint8Array) return body;
  if (body instanceof ArrayBuffer) return new Uint8Array(body);
  if (ArrayBuffer.isView(body)) return new Uint8Array(body.buffer, body.byteOffset, body.byteLength);
  if (typeof body === 'string') return new TextEncoder().encode(body);
  return new TextEncoder().encode(String(body));
}

let _proxyBase = null;
export function setProxyBase(base) {
  _proxyBase = base ? String(base).replace(/\/+$/, '') : null;
}
export function getProxyBase() {
  return _proxyBase || globalThis.__PH_PROXY_BASE__ || 'http://127.0.0.1:8765';
}

/**
 * 发一个请求。
 * @param {{url,method,headers,body,timeout}} req
 * @returns {Promise<{status,statusText,headers,bodyBase64,finalUrl,errorText}>}
 */
export async function transport(req) {
  const injected = globalThis.__PH_TRANSPORT__;
  if (typeof injected === 'function') return await injected(req);

  const payload = {
    url: req.url,
    method: (req.method || 'GET').toUpperCase(),
    headers: req.headers || {},
    body: req.body ? bytesToBase64(req.body) : null,
    timeout: req.timeout || DEFAULT_TIMEOUT,
  };
  const ctrl = new AbortController();
  const tid = setTimeout(() => ctrl.abort(), (payload.timeout || DEFAULT_TIMEOUT) + 5000);
  let r;
  try {
    r = await fetch(getProxyBase() + '/__proxy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: ctrl.signal,
    });
  } finally {
    clearTimeout(tid);
  }
  if (!r.ok) throw new Error('本地代理异常 HTTP ' + r.status);
  const j = await r.json();
  if (j && j.transportError) {
    const e = new Error(j.transportError);
    e.isTransport = true;
    throw e;
  }
  return {
    status: j.status || 0,
    statusText: j.statusText || '',
    headers: j.headers || {},
    bodyBase64: j.body || '',
    truncated: !!j.truncated,
    finalUrl: j.finalUrl || req.url,
  };
}

/* ------------------------------------------------------------------ axios */
/** 小写化 header 名，便于大小写无关查找 */
function lowerHeaders(h) {
  const out = {};
  if (!h) return out;
  for (const k of Object.keys(h)) {
    if (h[k] === undefined || h[k] === null) continue;
    out[String(k).toLowerCase()] = h[k];
  }
  return out;
}

function buildQuery(params) {
  if (!params) return '';
  const usp = new URLSearchParams();
  const add = (k, v) => {
    if (v === undefined || v === null) return;
    if (v instanceof Date) v = v.toISOString();
    usp.append(k, typeof v === 'object' ? JSON.stringify(v) : String(v));
  };
  if (params instanceof URLSearchParams) return params.toString();
  if (typeof params === 'string') return params.replace(/^\?/, '');
  if (typeof params.append === 'function' && typeof params.toString === 'function') {
    return params.toString();          // qs / 上一代 URLSearchParams 形态
  }
  if (Array.isArray(params)) {         // axios 支持 [[k,v],...]
    for (const pair of params) if (pair && pair.length >= 2) add(pair[0], pair[1]);
  } else {
    for (const k of Object.keys(params)) {
      const v = params[k];
      if (Array.isArray(v)) v.forEach((one) => add(k, one));
      else add(k, v);
    }
  }
  return usp.toString();
}

function appendQuery(url, qs) {
  if (!qs) return url;
  return url + (url.indexOf('?') >= 0 ? '&' : '?') + qs;
}

/** 按 axios 默认规则准备 body 与 content-type */
function prepareData(data, headers) {
  if (data === undefined || data === null) return { body: null };
  if (typeof data === 'string') return { body: new TextEncoder().encode(data) };
  if (data instanceof Uint8Array || data instanceof ArrayBuffer || ArrayBuffer.isView(data)) {
    return { body: toBytes(data) };
  }
  if (data instanceof URLSearchParams || (typeof data.append === 'function' && typeof data.toString === 'function')) {
    if (!headers['content-type']) {
      headers['content-type'] = 'application/x-www-form-urlencoded';
    }
    return { body: new TextEncoder().encode(data.toString()) };
  }
  if (typeof FormData !== 'undefined' && data instanceof FormData) {
    return { body: null, formData: data };     // 交给代理侧不支持，插件极少用
  }
  if (!headers['content-type']) headers['content-type'] = 'application/json';
  return { body: new TextEncoder().encode(JSON.stringify(data)) };
}

function defaultTransformResponse(rawText, contentType) {
  const ct = String(contentType || '').toLowerCase();
  const looksJson = ct.indexOf('json') >= 0 ||
    /^\s*[[{]/.test(rawText || '');
  if (looksJson && rawText) {
    try { return JSON.parse(rawText); } catch (e) { /* 保持原文 */ }
  }
  return rawText;
}

export function createAxios() {
  async function request(config) {
    if (typeof config === 'string') config = { url: config };
    config = config || {};

    const method = String(config.method || 'get').toUpperCase();
    let url = config.url || '';
    if (config.baseURL && !/^https?:\/\//i.test(url)) {
      url = String(config.baseURL).replace(/\/+$/, '') + '/' + url.replace(/^\/+/, '');
    }
    url = appendQuery(url, buildQuery(config.params));

    const headers = lowerHeaders(config.headers);
    if (!headers['user-agent'] && config.userAgent) headers['user-agent'] = config.userAgent;

    const prep = prepareData(config.data, headers);
    if (prep.formData) throw new Error('插件使用了 FormData，暂不支持');

    const validateStatus = config.validateStatus ||
      ((s) => s >= 200 && s < 300);
    const timeout = config.timeout || DEFAULT_TIMEOUT;

    let res;
    try {
      res = await transport({ url, method, headers, body: prep.body, timeout });
    } catch (e) {
      const err = new Error(e.message || 'Network Error');
      err.config = config;
      err.code = 'ERR_NETWORK';
      err.isAxiosError = true;
      throw err;
    }

    const respHeaders = lowerHeaders(res.headers);
    const bytes = res.bodyBase64 ? base64ToBytes(res.bodyBase64) : new Uint8Array(0);
    const responseType = config.responseType;

    let data;
    if (responseType === 'arraybuffer') {
      // 复制到独立 ArrayBuffer，避免与共享 buffer 纠缠
      data = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    } else if (responseType === 'blob') {
      data = new Blob([bytes], { type: respHeaders['content-type'] || '' });
    } else {
      const text = new TextDecoder('utf-8').decode(bytes);
      data = defaultTransformResponse(text, respHeaders['content-type']);
    }

    const response = {
      data,
      status: res.status,
      statusText: res.statusText,
      headers: respHeaders,
      config,
      request: { responseURL: res.finalUrl },
    };

    if (typeof config.transformResponse === 'function' && responseType !== 'arraybuffer') {
      response.data = config.transformResponse(response.data, response.headers);
    }

    if (!validateStatus(res.status)) {
      const err = new Error(
        'Request failed with status code ' + res.status);
      err.response = response;
      err.config = config;
      err.isAxiosError = true;
      err.code = 'ERR_BAD_RESPONSE';
      throw err;
    }
    return response;
  }

  const axios = function (config) { return request(config); };
  axios.request = request;
  axios.get = (url, config) => request(Object.assign({}, config, { url, method: 'get' }));
  axios.delete = (url, config) => request(Object.assign({}, config, { url, method: 'delete' }));
  axios.head = (url, config) => request(Object.assign({}, config, { url, method: 'head' }));
  axios.options = (url, config) => request(Object.assign({}, config, { url, method: 'options' }));
  axios.post = (url, data, config) => request(Object.assign({}, config, { url, method: 'post', data }));
  axios.put = (url, data, config) => request(Object.assign({}, config, { url, method: 'put', data }));
  axios.patch = (url, data, config) => request(Object.assign({}, config, { url, method: 'patch', data }));
  axios.all = (list) => Promise.all(list);
  axios.spread = (fn) => (arr) => fn.apply(null, arr);
  axios.create = (defaults) => {
    const inst = (config) => request(Object.assign({}, defaults, config));
    inst.request = (config) => request(Object.assign({}, defaults, config));
    inst.get = (url, config) => request(Object.assign({}, defaults, config, { url, method: 'get' }));
    inst.post = (url, data, config) => request(Object.assign({}, defaults, config, { url, method: 'post', data }));
    inst.defaults = defaults || {};
    inst.interceptors = { request: { use() {} }, response: { use() {} } };
    return inst;
  };
  axios.defaults = {
    headers: { common: {} },
    timeout: DEFAULT_TIMEOUT,
    validateStatus: (s) => s >= 200 && s < 300,
  };
  axios.isAxiosError = (e) => !!(e && e.isAxiosError);
  axios.CancelToken = { source: () => ({ token: {}, cancel() {} }) };
  axios.isCancel = () => false;
  axios.__esModule = true;
  axios.default = axios;

  return axios;
}
