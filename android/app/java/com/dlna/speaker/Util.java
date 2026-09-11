package com.dlna.speaker;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.Charset;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.zip.GZIPInputStream;
import java.util.zip.InflaterInputStream;

/**
 * 通用工具：Base64、URL 编解码、带任意请求头的 HTTP 抓取（供在线音源代理使用）
 * 同样不依赖 android.*，可在桌面 JVM 上运行以便验证。
 */
public final class Util {

    private Util() {}

    private static final char[] B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/".toCharArray();
    private static final int[] B64INV = new int[128];
    static {
        for (int i = 0; i < B64INV.length; i++) B64INV[i] = -1;
        for (int i = 0; i < B64.length; i++) B64INV[B64[i]] = i;
    }

    public static String base64(byte[] data) {
        if (data == null) return "";
        StringBuilder sb = new StringBuilder((data.length + 2) / 3 * 4);
        int i = 0;
        while (i + 2 < data.length) {
            int n = ((data[i] & 0xFF) << 16) | ((data[i + 1] & 0xFF) << 8) | (data[i + 2] & 0xFF);
            sb.append(B64[(n >> 18) & 63]).append(B64[(n >> 12) & 63])
              .append(B64[(n >> 6) & 63]).append(B64[n & 63]);
            i += 3;
        }
        int rem = data.length - i;
        if (rem == 1) {
            int n = (data[i] & 0xFF) << 16;
            sb.append(B64[(n >> 18) & 63]).append(B64[(n >> 12) & 63]).append("==");
        } else if (rem == 2) {
            int n = ((data[i] & 0xFF) << 16) | ((data[i + 1] & 0xFF) << 8);
            sb.append(B64[(n >> 18) & 63]).append(B64[(n >> 12) & 63])
              .append(B64[(n >> 6) & 63]).append('=');
        }
        return sb.toString();
    }

    public static byte[] unbase64(String s) {
        if (s == null || s.isEmpty()) return new byte[0];
        ByteArrayOutputStream out = new ByteArrayOutputStream(s.length() * 3 / 4 + 3);
        int buf = 0, bits = 0;
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c == '=' || c == '\n' || c == '\r') continue;
            if (c >= 128) continue;
            int v = B64INV[c];
            if (v < 0) continue;
            buf = (buf << 6) | v;
            bits += 6;
            if (bits >= 8) {
                bits -= 8;
                out.write((buf >> bits) & 0xFF);
            }
        }
        return out.toByteArray();
    }

    /* --------------------------------------------------------- URL 编解码 */

    public static String urlEncode(String s) {
        if (s == null) return "";
        StringBuilder sb = new StringBuilder(s.length() + 16);
        byte[] bytes = s.getBytes(Charset.forName("UTF-8"));
        for (byte value : bytes) {
            int b = value & 0xFF;
            if ((b >= 'A' && b <= 'Z') || (b >= 'a' && b <= 'z') || (b >= '0' && b <= '9')
                    || b == '-' || b == '_' || b == '.' || b == '~') {
                sb.append((char) b);
            } else {
                sb.append('%').append(Character.toUpperCase(Character.forDigit((b >> 4) & 15, 16)))
                  .append(Character.toUpperCase(Character.forDigit(b & 15, 16)));
            }
        }
        return sb.toString();
    }

    public static String urlDecode(String s) {
        if (s == null) return "";
        ByteArrayOutputStream out = new ByteArrayOutputStream(s.length());
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c == '%' && i + 2 < s.length()) {
                try {
                    out.write(Integer.parseInt(s.substring(i + 1, i + 3), 16));
                    i += 2;
                    continue;
                } catch (NumberFormatException ignore) { }
            }
            if (c == '+') { out.write(' '); continue; }
            byte[] bs = String.valueOf(c).getBytes(Charset.forName("UTF-8"));
            out.write(bs, 0, bs.length);
        }
        return new String(out.toByteArray(), Charset.forName("UTF-8"));
    }

    /** 解析 query string 为 Map（重复键保留第一个） */
    public static Map<String, String> parseQuery(String qs) {
        Map<String, String> m = new LinkedHashMap<String, String>();
        if (qs == null || qs.isEmpty()) return m;
        for (String pair : qs.split("&")) {
            if (pair.isEmpty()) continue;
            int eq = pair.indexOf('=');
            String k = eq >= 0 ? pair.substring(0, eq) : pair;
            String v = eq >= 0 ? pair.substring(eq + 1) : "";
            k = urlDecode(k);
            if (!m.containsKey(k)) m.put(k, urlDecode(v));
        }
        return m;
    }

    /* --------------------------------------------------------- HTTP 抓取 */

    /** HTTP 响应 */
    public static final class Resp {
        public int status;
        public String statusText = "";
        public Map<String, String> headers = new LinkedHashMap<String, String>();
        public byte[] body = new byte[0];
        public String finalUrl = "";
        public String error;
        /** 响应体超过 MAX_FETCH_BYTES 被截断了 */
        public boolean truncated;
    }

    /**
     * 单次抓取允许的最大响应体（解压后）。
     * 在线音源偶尔会返回异常巨大的响应，而它后面还要经过 base64（x1.33）、
     * JSON 序列化（x2）再交给 WebView 解码，内存会成倍放大 —— 不设上限的话
     * 很容易把渲染进程撑爆。到限就截断，让插件自己报解析失败，而不是拖垮 App。
     */
    public static final int MAX_FETCH_BYTES = 16 * 1024 * 1024;

    /**
     * 携带任意请求头的 HTTP 请求（会自动跟随跳转、解压 gzip/deflate）。
     * HttpURLConnection 禁止设置若干保留头，这里统一过滤掉。
     */
    public static Resp fetch(String url, String method, Map<String, String> headers,
                             byte[] body, int timeoutSec) {
        return fetch(url, method, headers, body, timeoutSec, 0);
    }

    private static Resp fetch(String url, String method, Map<String, String> headers,
                              byte[] body, int timeoutSec, int depth) {
        Resp out = new Resp();
        out.finalUrl = url;
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(url).openConnection();
            c.setRequestMethod(method == null || method.isEmpty() ? "GET" : method.toUpperCase(Locale.ROOT));
            c.setConnectTimeout(Math.max(1000, timeoutSec * 1000));
            c.setReadTimeout(Math.max(1000, timeoutSec * 1000));
            c.setInstanceFollowRedirects(false);
            c.setUseCaches(false);
            c.setRequestProperty("Accept-Encoding", "gzip, deflate");

            if (headers != null) {
                for (Map.Entry<String, String> e : headers.entrySet()) {
                    String k = e.getKey();
                    if (k == null || e.getValue() == null) continue;
                    if (RESTRICTED.contains(k.toLowerCase(Locale.ROOT))) continue;
                    c.setRequestProperty(k, e.getValue());
                }
            }
            if (body != null && body.length > 0) {
                c.setDoOutput(true);
                c.setFixedLengthStreamingMode(body.length);
                OutputStream os = c.getOutputStream();
                os.write(body);
                os.flush();
                os.close();
            }

            int code = c.getResponseCode();
            out.status = code;
            out.statusText = c.getResponseMessage() == null ? "" : c.getResponseMessage();

            // 跳转：按浏览器语义处理（303 / 301,302 的 POST 都转成 GET）
            if (code >= 300 && code < 400 && depth < 6) {
                String loc = c.getHeaderField("Location");
                if (loc != null && !loc.isEmpty()) {
                    String next = new URL(new URL(url), loc).toString();
                    String nextMethod = method;
                    byte[] nextBody = body;
                    if (code == 303 || ((code == 301 || code == 302)
                            && "POST".equalsIgnoreCase(method))) {
                        nextMethod = "GET";
                        nextBody = null;
                    }
                    c.disconnect();
                    return fetch(next, nextMethod, headers, nextBody, timeoutSec, depth + 1);
                }
            }

            for (Map.Entry<String, java.util.List<String>> e : c.getHeaderFields().entrySet()) {
                if (e.getKey() == null) continue;
                StringBuilder v = new StringBuilder();
                for (String one : e.getValue()) {
                    if (v.length() > 0) v.append(", ");
                    v.append(one);
                }
                out.headers.put(e.getKey(), v.toString());
            }

            InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
            byte[] raw = readAll(in, MAX_FETCH_BYTES);
            if (raw.length >= MAX_FETCH_BYTES) out.truncated = true;
            String enc = lower(c.getHeaderField("Content-Encoding"));
            byte[] plain = raw;
            if (enc.contains("gzip")) {
                try {
                    plain = readAll(new GZIPInputStream(new ByteArrayInputStream(raw)), MAX_FETCH_BYTES);
                } catch (Exception ignore) { }
            } else if (enc.contains("deflate")) {
                try {
                    plain = readAll(new InflaterInputStream(new ByteArrayInputStream(raw)), MAX_FETCH_BYTES);
                } catch (Exception ignore) { }
            }
            if (plain.length >= MAX_FETCH_BYTES) out.truncated = true;
            out.body = plain;
            // 已解压，去掉会让 JS 侧误解的头
            out.headers.remove("Content-Encoding");
            out.headers.remove("content-encoding");
            out.headers.remove("Content-Length");
            out.headers.remove("content-length");
            out.headers.remove("Transfer-Encoding");
            out.headers.remove("transfer-encoding");
            return out;
        } catch (Exception e) {
            out.error = String.valueOf(e.getMessage() == null ? e : e.getMessage());
            return out;
        } finally {
            if (c != null) try { c.disconnect(); } catch (Exception ignore) { }
        }
    }

    private static final Set<String> RESTRICTED = new LinkedHashSet<String>();
    static {
        RESTRICTED.add("connection");
        RESTRICTED.add("content-length");
        RESTRICTED.add("host");
        RESTRICTED.add("upgrade");
        RESTRICTED.add("keep-alive");
        RESTRICTED.add("transfer-encoding");
        RESTRICTED.add("proxy-connection");
        RESTRICTED.add("te");
        RESTRICTED.add("trailer");
    }

    private static String lower(String s) { return s == null ? "" : s.toLowerCase(Locale.ROOT); }

    public static byte[] readAll(InputStream in) throws Exception {
        return readAll(in, 0);
    }

    /** maxBytes<=0 表示不限量；到达上限即停止读取，返回已读到的部分 */
    public static byte[] readAll(InputStream in, int maxBytes) throws Exception {
        if (in == null) return new byte[0];
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        byte[] buf = new byte[16384];
        int n;
        while ((n = in.read(buf)) > 0) {
            if (maxBytes > 0 && bos.size() + n > maxBytes) {
                bos.write(buf, 0, maxBytes - bos.size());
                break;
            }
            bos.write(buf, 0, n);
        }
        try { in.close(); } catch (Exception ignore) { }
        return bos.toByteArray();
    }

    /* --------------------------------------------------------- 杂项 */

    private static final Map<String, String> MIME = new LinkedHashMap<String, String>();
    static {
        MIME.put("mp3", "audio/mpeg");
        MIME.put("flac", "audio/flac");
        MIME.put("wav", "audio/wav");
        MIME.put("m4a", "audio/mp4");
        MIME.put("aac", "audio/aac");
        MIME.put("ogg", "audio/ogg");
        MIME.put("oga", "audio/ogg");
        MIME.put("opus", "audio/ogg");
        MIME.put("wma", "audio/x-ms-wma");
        MIME.put("ape", "audio/x-ape");
        MIME.put("aif", "audio/aiff");
        MIME.put("aiff", "audio/aiff");
        MIME.put("mp4", "audio/mp4");
        MIME.put("m3u8", "application/x-mpegURL");
        MIME.put("mpd", "application/dash+xml");
        MIME.put("jpg", "image/jpeg");
        MIME.put("jpeg", "image/jpeg");
        MIME.put("png", "image/png");
        MIME.put("webp", "image/webp");
        MIME.put("gif", "image/gif");
        MIME.put("html", "text/html; charset=utf-8");
        MIME.put("js", "application/javascript; charset=utf-8");
        MIME.put("css", "text/css; charset=utf-8");
        MIME.put("json", "application/json; charset=utf-8");
        MIME.put("txt", "text/plain; charset=utf-8");
    }

    public static String mimeOf(String pathOrUrl) {
        if (pathOrUrl == null) return "application/octet-stream";
        String s = pathOrUrl;
        int q = s.indexOf('?');
        if (q >= 0) s = s.substring(0, q);
        int dot = s.lastIndexOf('.');
        if (dot < 0) return "application/octet-stream";
        String ext = s.substring(dot + 1).toLowerCase(Locale.ROOT);
        String m = MIME.get(ext);
        return m == null ? "application/octet-stream" : m;
    }

    /** 音频扩展名集合（小写，不含点） */
    public static final Set<String> AUDIO_EXTS = new LinkedHashSet<String>();
    static {
        String[] exts = {"mp3", "flac", "wav", "m4a", "aac", "ogg", "oga", "opus",
                         "wma", "ape", "aif", "aiff", "mp4", "mpc", "wv", "dsf", "dff"};
        for (String e : exts) AUDIO_EXTS.add(e);
    }

    public static boolean isAudio(String name) {
        if (name == null) return false;
        int dot = name.lastIndexOf('.');
        if (dot < 0) return false;
        return AUDIO_EXTS.contains(name.substring(dot + 1).toLowerCase(Locale.ROOT));
    }

    /** 去掉文件名里的非法字符（用于下载落盘） */
    public static String sanitizeName(String s, String fallback) {
        if (s == null) s = "";
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c == '\\' || c == '/' || c == ':' || c == '*' || c == '?' || c == '"'
                    || c == '<' || c == '>' || c == '|' || c < 0x20) {
                sb.append(' ');
            } else {
                sb.append(c);
            }
        }
        String n = sb.toString().replaceAll("\\s+", " ").trim();
        if (n.isEmpty()) n = fallback == null ? "未知" : fallback;
        return n.length() > 80 ? n.substring(0, 80) : n;
    }

    public static String pickExt(String url, String contentType) {
        if (url != null) {
            String s = url;
            int q = s.indexOf('?');
            if (q >= 0) s = s.substring(0, q);
            int dot = s.lastIndexOf('.');
            if (dot >= 0) {
                String ext = s.substring(dot + 1).toLowerCase(Locale.ROOT);
                if (Util.AUDIO_EXTS.contains(ext)) return ext;
            }
        }
        String ct = lower(contentType);
        if (ct.contains("flac")) return "flac";
        if (ct.contains("mp4") || ct.contains("m4a")) return "m4a";
        if (ct.contains("ogg")) return "ogg";
        if (ct.contains("wav")) return "wav";
        if (ct.contains("aac")) return "aac";
        return "mp3";
    }

    /** 秒 -> H:MM:SS */
    public static String secToTsec(int s) { return Dlna.secToTsec(s); }
}
