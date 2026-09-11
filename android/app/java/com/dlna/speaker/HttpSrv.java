package com.dlna.speaker;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.Charset;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * 极简 HTTP/1.1 服务（多线程 + keep-alive + Range 断点续传 + 流式响应）
 * =====================================================================
 * Android 上没有 com.sun.net.httpserver，所以这里基于 ServerSocket 自己实现。
 * 只用 Java 标准库，桌面 JVM 上也能跑，便于先在本机把全部接口验证一遍。
 */

public final class HttpSrv {

    /* ------------------------------------------------------------ 请求 */

    public static final class Req {
        public String method = "GET";
        public String path = "/";           // 已 URL 解码的路径
        public String rawPath = "/";
        public String query = "";
        public Map<String, String> params = new LinkedHashMap<String, String>();
        public Map<String, String> headers = new LinkedHashMap<String, String>();  // 键统一小写
        public byte[] body = new byte[0];
        public String remoteIp = "";

        public String header(String name) {
            return headers.get(name == null ? "" : name.toLowerCase(Locale.ROOT));
        }

        public String param(String name) { return params.get(name); }
        public String param(String name, String def) {
            String v = params.get(name);
            return v == null ? def : v;
        }
        public int paramInt(String name, int def) {
            String v = params.get(name);
            if (v == null) return def;
            try { return (int) Double.parseDouble(v.trim()); } catch (Exception e) { return def; }
        }
        public String bodyText() { return new String(body, Charset.forName("UTF-8")); }
        public Map<String, Object> json() { return Json.parseObject(bodyText()); }
    }

    /* ------------------------------------------------------------ 响应 */

    public interface Streamer { void write(OutputStream out) throws Exception; }

    public static final class Res {
        public int status = 200;
        public Map<String, String> headers = new LinkedHashMap<String, String>();
        public byte[] body;
        public Streamer streamer;
        public long streamLength = -1;
        public boolean closeAfter = false;

        public void set(String k, String v) { headers.put(k, v); }

        public void send(int code, String contentType, byte[] data) {
            this.status = code;
            if (contentType != null) headers.put("Content-Type", contentType);
            this.body = data == null ? new byte[0] : data;
            headers.put("Content-Length", String.valueOf(this.body.length));
        }

        public void text(int code, String s) {
            send(code, "text/plain; charset=utf-8", s == null ? new byte[0] : s.getBytes(Charset.forName("UTF-8")));
        }

        public void json(Object o) {
            send(200, "application/json; charset=utf-8", Json.write(o).getBytes(Charset.forName("UTF-8")));
        }

        public void json(int code, Object o) {
            send(code, "application/json; charset=utf-8", Json.write(o).getBytes(Charset.forName("UTF-8")));
        }

        public void cors() {
            headers.put("Access-Control-Allow-Origin", "*");
            headers.put("Access-Control-Allow-Headers", "*");
            headers.put("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS");
            headers.put("Access-Control-Max-Age", "86400");
        }
    }

    public interface Handler { void handle(Req req, Res res) throws Exception; }

    /* ------------------------------------------------------------ 服务 */

    private final int port;
    private final Handler handler;
    private ServerSocket server;
    private ExecutorService pool;
    private final AtomicBoolean running = new AtomicBoolean(false);

    public HttpSrv(int port, Handler handler) {
        this.port = port;
        this.handler = handler;
    }

    public int port() {
        return server == null ? port : server.getLocalPort();
    }

    public void start() throws IOException {
        server = new ServerSocket();
        server.setReuseAddress(true);
        server.bind(new InetSocketAddress(port));
        pool = Executors.newCachedThreadPool();
        running.set(true);
        Thread t = new Thread(new Runnable() {
            @Override public void run() {
                try {
                    acceptLoop();
                } catch (Throwable ignore) {
                    // 接入线程绝不能带着未捕获异常退出（Android 会直接杀掉进程）
                }
            }
        }, "http-accept");
        t.setDaemon(true);
        t.start();
    }

    public void stop() {
        running.set(false);
        try { if (server != null) server.close(); } catch (Exception ignore) { }
        if (pool != null) pool.shutdownNow();
    }

    private void acceptLoop() {
        while (running.get()) {
            Socket sock;
            try {
                sock = server.accept();
            } catch (Throwable e) {
                if (running.get()) continue;
                break;
            }
            try {
                pool.execute(new Worker(sock));
            } catch (Throwable e) {
                try { sock.close(); } catch (Throwable ignore) { }
            }
        }
    }

    private final class Worker implements Runnable {
        private final Socket sock;

        Worker(Socket s) { this.sock = s; }

        @Override public void run() {
            try {
                sock.setTcpNoDelay(true);
                sock.setSoTimeout(60000);
                BufferedInputStream in = new BufferedInputStream(sock.getInputStream(), 16384);
                OutputStream out = new BufferedOutputStream(sock.getOutputStream(), 32768);
                while (running.get()) {
                    Req req = readRequest(in);
                    if (req == null) break;
                    boolean keepAlive = handleOne(req, out);
                    out.flush();
                    if (!keepAlive) break;
                }
            } catch (Throwable ignore) {
                // 客户端断开属正常；Error 也必须吞掉，否则 Android 会杀掉整个进程
            } finally {
                try { sock.close(); } catch (Throwable ignore) { }
            }
        }
    }

    private boolean handleOne(Req req, OutputStream out) {
        Res res = new Res();
        boolean keepAlive = !"close".equalsIgnoreCase(req.header("connection"));
        try {
            handler.handle(req, res);
        } catch (Throwable e) {
            // 单个请求出错只该返回 500，绝不能让工作线程带着未捕获异常退出
            res.body = null;
            res.streamer = null;
            res.text(500, "服务内部错误: " + e);
        }
        if ("OPTIONS".equalsIgnoreCase(req.method) && res.status == 200 && res.body == null) {
            res.status = 204;
            res.body = new byte[0];
        }
        if (res.closeAfter) keepAlive = false;
        if (res.status == 204 || res.status == 304) {
            res.body = new byte[0];
            res.headers.remove("Content-Length");
        }
        if (!res.headers.containsKey("Access-Control-Allow-Origin")) res.cors();

        try {
            writeResponse(out, req, res, keepAlive);
        } catch (Exception e) {
            keepAlive = false;
        }
        return keepAlive;
    }

    private void writeResponse(OutputStream out, Req req, Res res, boolean keepAlive) throws Exception {
        StringBuilder sb = new StringBuilder(256);
        sb.append("HTTP/1.1 ").append(res.status).append(' ').append(reason(res.status)).append("\r\n");
        if (!res.headers.containsKey("Date")) {
            sb.append("Date: ").append(httpDate()).append("\r\n");
        }
        sb.append("Server: DlnaSpeaker/1.0\r\n");
        for (Map.Entry<String, String> e : res.headers.entrySet()) {
            sb.append(e.getKey()).append(": ").append(e.getValue()).append("\r\n");
        }
        if (!res.headers.containsKey("Content-Length") && res.streamer == null) {
            sb.append("Content-Length: ").append(res.body == null ? 0 : res.body.length).append("\r\n");
        }
        sb.append("Connection: ").append(keepAlive ? "keep-alive" : "close").append("\r\n\r\n");
        out.write(sb.toString().getBytes(Charset.forName("ISO-8859-1")));

        if (res.streamer != null) {
            res.streamer.write(out);
        } else if (res.body != null && res.body.length > 0) {
            out.write(res.body);
        }
        out.flush();
    }

    private static String reason(int code) {
        switch (code) {
            case 200: return "OK";
            case 204: return "No Content";
            case 206: return "Partial Content";
            case 301: return "Moved Permanently";
            case 302: return "Found";
            case 304: return "Not Modified";
            case 400: return "Bad Request";
            case 403: return "Forbidden";
            case 404: return "Not Found";
            case 405: return "Method Not Allowed";
            case 416: return "Range Not Satisfiable";
            case 500: return "Internal Server Error";
            case 502: return "Bad Gateway";
            case 503: return "Service Unavailable";
            default: return "OK";
        }
    }

    private static String httpDate() {
        java.text.SimpleDateFormat f = new java.text.SimpleDateFormat(
                "EEE, dd MMM yyyy HH:mm:ss 'GMT'", Locale.US);
        f.setTimeZone(java.util.TimeZone.getTimeZone("GMT"));
        return f.format(new java.util.Date());
    }

    /* ------------------------------------------------------- 请求解析 */

    private Req readRequest(InputStream in) throws IOException {
        String requestLine = readLine(in);
        if (requestLine == null) return null;
        requestLine = requestLine.trim();
        if (requestLine.isEmpty()) return null;

        Req req = new Req();
        String[] parts = requestLine.split(" ");
        if (parts.length < 2) return null;
        req.method = parts[0].toUpperCase(Locale.ROOT);
        String target = parts[1];
        int q = target.indexOf('?');
        req.rawPath = q >= 0 ? target.substring(0, q) : target;
        req.query = q >= 0 ? target.substring(q + 1) : "";
        req.path = Util.urlDecode(req.rawPath);
        req.params = Util.parseQuery(req.query);

        String line;
        while ((line = readLine(in)) != null) {
            if (line.isEmpty()) break;
            int c = line.indexOf(':');
            if (c <= 0) continue;
            String k = line.substring(0, c).trim().toLowerCase(Locale.ROOT);
            String v = line.substring(c + 1).trim();
            req.headers.put(k, v);
        }

        String te = req.header("transfer-encoding");
        String cl = req.header("content-length");
        if (te != null && te.toLowerCase(Locale.ROOT).contains("chunked")) {
            req.body = readChunked(in);
        } else if (cl != null) {
            int n;
            try { n = Integer.parseInt(cl.trim()); } catch (Exception e) { n = 0; }
            if (n > 0) req.body = readN(in, n);
        }
        return req;
    }

    private static String readLine(InputStream in) throws IOException {
        ByteArrayOutputStream bos = new ByteArrayOutputStream(128);
        int c;
        boolean any = false;
        while ((c = in.read()) >= 0) {
            any = true;
            if (c == '\n') break;
            if (c != '\r') bos.write(c);
        }
        if (!any && bos.size() == 0) return null;
        return new String(bos.toByteArray(), Charset.forName("ISO-8859-1"));
    }

    private static byte[] readN(InputStream in, int n) throws IOException {
        byte[] buf = new byte[n];
        int off = 0;
        while (off < n) {
            int r = in.read(buf, off, n - off);
            if (r < 0) break;
            off += r;
        }
        if (off == n) return buf;
        byte[] cut = new byte[off];
        System.arraycopy(buf, 0, cut, 0, off);
        return cut;
    }

    private static byte[] readChunked(InputStream in) throws IOException {
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        while (true) {
            String sizeLine = readLine(in);
            if (sizeLine == null) break;
            sizeLine = sizeLine.trim();
            int semi = sizeLine.indexOf(';');
            if (semi >= 0) sizeLine = sizeLine.substring(0, semi);
            if (sizeLine.isEmpty()) continue;
            int size;
            try { size = Integer.parseInt(sizeLine, 16); } catch (Exception e) { break; }
            if (size == 0) {
                readLine(in);            // 结尾空行
                break;
            }
            byte[] chunk = readN(in, size);
            bos.write(chunk);
            readLine(in);                // chunk 后的 CRLF
        }
        return bos.toByteArray();
    }

    /* ------------------------------------------- 静态文件（含 Range） */

    /** 提供一个本地文件，支持 Range 请求（音响拖进度条/断点续传依赖它） */
    public static void serveFile(File f, String mime, Req req, Res res) throws Exception {
        if (f == null || !f.isFile()) {
            res.text(404, "not found");
            return;
        }
        long total = f.length();
        String range = req.header("range");
        long start = 0, end = total - 1;
        boolean partial = false;
        if (range != null && range.startsWith("bytes=")) {
            String spec = range.substring(6).split(",")[0].trim();
            int dash = spec.indexOf('-');
            try {
                if (dash > 0) {
                    start = Long.parseLong(spec.substring(0, dash));
                    if (dash + 1 < spec.length()) end = Long.parseLong(spec.substring(dash + 1));
                } else if (dash == 0 && spec.length() > 1) {
                    long suffix = Long.parseLong(spec.substring(1));
                    start = Math.max(0, total - suffix);
                }
                if (end >= total) end = total - 1;
                if (start > end || start >= total) {
                    res.status = 416;
                    res.set("Content-Range", "bytes */" + total);
                    res.text(416, "range not satisfiable");
                    return;
                }
                partial = true;
            } catch (Exception ignore) {
                partial = false;
                start = 0;
                end = total - 1;
            }
        }
        final long fStart = start;
        final long fEnd = end;
        final long len = fEnd - fStart + 1;
        final File file = f;
        if (mime != null) res.set("Content-Type", mime);
        res.set("Accept-Ranges", "bytes");
        if (partial) {
            res.status = 206;
            res.set("Content-Range", "bytes " + fStart + "-" + fEnd + "/" + total);
        } else {
            res.status = 200;
        }
        res.set("Content-Length", String.valueOf(len));
        res.closeAfter = true;
        res.streamer = new Streamer() {
            @Override public void write(OutputStream out) throws Exception {
                InputStream in = new FileInputStream(file);
                try {
                    long skip = fStart;
                    while (skip > 0) {
                        long s = in.skip(skip);
                        if (s <= 0) break;
                        skip -= s;
                    }
                    byte[] buf = new byte[65536];
                    long left = len;
                    while (left > 0) {
                        int r = in.read(buf, 0, (int) Math.min(buf.length, left));
                        if (r < 0) break;
                        out.write(buf, 0, r);
                        left -= r;
                    }
                } finally {
                    try { in.close(); } catch (Exception ignore) { }
                }
            }
        };
    }
}
