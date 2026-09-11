package com.dlna.speaker;

import jcifs.CIFSContext;
import jcifs.config.PropertyConfiguration;
import jcifs.context.BaseContext;
import jcifs.smb.NtlmPasswordAuthenticator;
import jcifs.smb.SmbFile;
import jcifs.smb.SmbFileInputStream;

import java.io.InputStream;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Properties;

/**
 * SMB / CIFS 网络共享客户端
 * ========================
 * 用 jcifs-ng（纯 Java 实现，支持 SMB1/2/3）直接连 NAS 或路由器的共享目录，
 * 不需要依赖手机系统文件管理器是否支持「网络邻居」。
 *
 * 这里的每个对外方法都**不允许抛未捕获异常** —— 网络共享随时可能掉线、
 * 账号错误、权限不足，任何一种都不能把 App 带崩，只能变成一句可读的错误。
 */
public final class Smb {

    /** 连接参数 */
    public static final class Conn {
        public String host = "";
        public String share = "";
        public String subpath = "";
        public String user = "";
        public String password = "";
        public String domain = "";
        public boolean guest = false;

        public Conn() { }

        public Conn(String host, String share, String subpath, String user, String password, boolean guest) {
            this.host = host == null ? "" : host.trim();
            this.share = share == null ? "" : share.trim();
            this.subpath = subpath == null ? "" : subpath.trim();
            this.user = user == null ? "" : user.trim();
            this.password = password == null ? "" : password;
            this.guest = guest;
        }

        public String baseUrl() {
            StringBuilder sb = new StringBuilder("smb://");
            sb.append(host).append("/").append(share).append("/");
            String sub = subpath;
            while (sub.startsWith("/")) sub = sub.substring(1);
            if (!sub.isEmpty()) {
                sb.append(sub);
                if (!sub.endsWith("/")) sb.append("/");
            }
            return sb.toString();
        }
    }

    private static final int CONN_TIMEOUT = 10000;
    private static final int SO_TIMEOUT = 25000;

    private static CIFSContext ctx(Conn c) throws Exception {
        Properties p = new Properties();
        p.setProperty("jcifs.smb.client.minVersion", "SMB202");
        p.setProperty("jcifs.smb.client.maxVersion", "SMB311");
        p.setProperty("jcifs.smb.client.connTimeout", String.valueOf(CONN_TIMEOUT));
        p.setProperty("jcifs.smb.client.responseTimeout", String.valueOf(SO_TIMEOUT));
        p.setProperty("jcifs.smb.client.soTimeout", String.valueOf(SO_TIMEOUT));
        // Android 上没有 NetBIOS 名字服务，直接走 DNS / IP
        p.setProperty("jcifs.resolveOrder", "DNS");
        p.setProperty("jcifs.smb.client.dfs.disabled", "true");
        PropertyConfiguration cfg = new PropertyConfiguration(p);
        CIFSContext base = new BaseContext(cfg);
        if (c.guest || c.user.isEmpty()) {
            return base.withAnonymousCredentials();
        }
        NtlmPasswordAuthenticator auth =
                new NtlmPasswordAuthenticator(c.domain == null ? "" : c.domain, c.user, c.password);
        return base.withCredentials(auth);
    }

    private static SmbFile file(String url, Conn c) throws Exception {
        String u = url.endsWith("/") ? url : url + "/";
        return new SmbFile(u, ctx(c));
    }

    /** 拼出某个相对路径的绝对 smb URL */
    public static String url(Conn c, String relPath) {
        String base = c.baseUrl();
        String rel = relPath == null ? "" : relPath;
        while (rel.startsWith("/")) rel = rel.substring(1);
        if (rel.isEmpty()) return base;
        return base + rel;
    }

    /**
     * 探测连接 + 统计音频数量（用于「测试连接」按钮）
     * 返回 {ok, files, dirs, error}
     */
    public static Map<String, Object> probe(Conn c) {
        Map<String, Object> out = Json.map();
        try {
            SmbFile root = file(c.baseUrl(), c);
            if (!root.exists()) {
                return Json.map("ok", false, "error", "无法访问共享目录，请检查地址与账号");
            }
            SmbFile[] kids = root.listFiles();
            int files = 0, dirs = 0;
            if (kids != null) {
                for (SmbFile k : kids) {
                    try {
                        if (k.isDirectory()) dirs++;
                        else if (Util.isAudio(k.getName())) files++;
                    } catch (Throwable ignore) { }
                }
            }
            return Json.map("ok", true, "files", files, "dirs", dirs,
                    "url", c.baseUrl());
        } catch (Throwable t) {
            return Json.map("ok", false, "error", describe(t));
        }
    }

    /**
     * 递归扫描共享目录里的音频文件。
     * 每项返回 {rel, name, dir, size}，由调用方组装成曲目。
     */
    public static List<Map<String, Object>> scan(Conn c, int maxFiles, int maxDepth, long maxMillis) {
        List<Map<String, Object>> out = new ArrayList<Map<String, Object>>();
        long deadline = System.currentTimeMillis() + maxMillis;
        try {
            SmbFile root = file(c.baseUrl(), c);
            walk(root, "", out, 0, maxFiles, maxDepth, deadline);
        } catch (Throwable ignore) { }
        return out;
    }

    private static void walk(SmbFile dir, String rel, List<Map<String, Object>> out,
                             int depth, int maxFiles, int maxDepth, long deadline) {
        if (depth > maxDepth || out.size() >= maxFiles) return;
        if (System.currentTimeMillis() > deadline) return;
        SmbFile[] kids;
        try { kids = dir.listFiles(); } catch (Throwable t) { return; }
        if (kids == null) return;
        for (SmbFile k : kids) {
            if (out.size() >= maxFiles) return;
            if (System.currentTimeMillis() > deadline) return;
            try {
                String name = k.getName();
                if (name == null || name.startsWith(".")) continue;
                // jcifs 有时会把「相对共享根的路径」当名字返回（带前后斜杠），
                // 不清掉的话曲库里会出现 Music//江语晨//xxx.mp3 这种双斜杠。
                while (name.startsWith("/")) name = name.substring(1);
                while (name.endsWith("/")) name = name.substring(0, name.length() - 1);
                if (name.isEmpty()) continue;
                String childRel = rel.isEmpty() ? name : rel + "/" + name;
                childRel = childRel.replaceAll("/{2,}", "/");
                if (k.isDirectory()) {
                    walk(k, childRel, out, depth + 1, maxFiles, maxDepth, deadline);
                } else if (Util.isAudio(name)) {
                    Map<String, Object> m = new LinkedHashMap<String, Object>();
                    m.put("rel", childRel);
                    m.put("name", name);
                    m.put("dir", rel);
                    long len = -1;
                    try { len = k.length(); } catch (Throwable ignore) { }
                    m.put("size", len);
                    out.add(m);
                }
            } catch (Throwable ignore) { }
        }
    }

    public static InputStream open(String smbUrl, Conn c) throws Exception {
        return new SmbFileInputStream(file(smbUrl, c));
    }

    public static long size(String smbUrl, Conn c) {
        try { return file(smbUrl, c).length(); } catch (Throwable t) { return -1; }
    }

    /** 读取一个共享上的文本文件（找 .lrc 用），失败一律返回空串 */
    public static String readText(String smbUrl, Conn c) {
        InputStream in = null;
        try {
            in = open(smbUrl, c);
            return Lyrics.readText(in);
        } catch (Throwable t) {
            return "";
        } finally {
            if (in != null) try { in.close(); } catch (Throwable ignore) { }
        }
    }

    /** 把底层异常翻译成人能看懂的话 */
    public static String describe(Throwable t) {
        String m = t == null ? "" : String.valueOf(t.getMessage());
        String cls = t == null ? "" : t.getClass().getSimpleName();
        String low = m.toLowerCase(Locale.ROOT);
        if (cls.contains("UnknownHost") || low.contains("unknownhost")
                || low.contains("no route to host")) return "找不到主机，检查 IP 是否正确";
        if (low.contains("logon failure") || low.contains("password is incorrect")
                || low.contains("bad password") || low.contains("authentication")
                || low.contains("status_logon_failure")) return "账号或密码不对";
        if (low.contains("access is denied") || low.contains("access_denied")
                || low.contains("not authorized")) return "没有权限访问该共享";
        // jcifs-ng 对「共享名不存在」抛的就是这句英文，得专门认一下
        if (low.contains("network name cannot be found") || low.contains("bad_network_name")
                || low.contains("network path was not found")
                || low.contains("object not found")) return "共享名不存在";
        if (low.contains("specified server is unknown")
                || low.contains("cannot find the file")) return "找不到该服务器或目录";
        if (cls.contains("SocketTimeout") || low.contains("timed out")
                || low.contains("timeout")) return "连接超时，检查网络是否可达";
        if (cls.contains("Connect") || low.contains("connection refused")
                || low.contains("connection reset")) return "无法连接，检查共享是否开启";
        return (cls.isEmpty() ? "" : cls + ": ") + (m.isEmpty() ? "未知错误" : m);
    }

    /* ==================================================================
       局域网发现 + 共享浏览（给界面上的「扫描」「浏览」按钮用）

       为什么要有这两个：
       NAS / 路由器共享的「共享名」和「目录名」用户不可能都记得住，
       让他手打 `music` / `Media/无损` 这类名字是不现实的。
       所以先扫出网段里开着 445 的机器，再让用户点进去一层层看。
       ================================================================== */

    private static final int SMB_PORT = 445;

    /** 本机所在的 /24 网段前缀，例如 192.168.1。不依赖任何权限。 */
    public static List<String> localPrefixes() {
        List<String> out = new ArrayList<String>();
        try {
            java.util.Enumeration<java.net.NetworkInterface> nis =
                    java.net.NetworkInterface.getNetworkInterfaces();
            while (nis != null && nis.hasMoreElements()) {
                java.net.NetworkInterface ni = nis.nextElement();
                try {
                    if (!ni.isUp() || ni.isLoopback()) continue;
                    List<java.net.InterfaceAddress> addrs = ni.getInterfaceAddresses();
                    if (addrs == null) continue;
                    for (java.net.InterfaceAddress ia : addrs) {
                        java.net.InetAddress a = ia.getAddress();
                        if (!(a instanceof java.net.Inet4Address)) continue;
                        if (a.isLoopbackAddress() || a.isLinkLocalAddress()) continue;
                        String ip = a.getHostAddress();
                        int dot = ip.lastIndexOf('.');
                        if (dot <= 0) continue;
                        String p = ip.substring(0, dot);
                        if (!out.contains(p)) out.add(p);
                    }
                } catch (Throwable ignore) { }
            }
        } catch (Throwable ignore) { }
        return out;
    }

    /**
     * 扫描局域网里开着 445 端口的机器（也就是 SMB 服务器），
     * 并对每台尝试枚举共享名。
     *
     * 全程有总时限，任何异常都吞掉 —— 扫描按钮不能把 App 卡死或搞崩。
     *
     * @return {ok, hosts:[{host, name, shares:[{name}], error}], prefixes, ms, error}
     */
    public static Map<String, Object> discover(final String user, final String password,
                                               final boolean guest, int budgetMs) {
        long t0 = System.currentTimeMillis();
        List<String> prefixes = localPrefixes();
        if (prefixes.isEmpty()) {
            return Json.map("ok", false, "hosts", new ArrayList<Object>(), "prefixes", prefixes,
                    "error", "没有找到可扫描的局域网网段，请确认已连上 WiFi");
        }

        final List<String> ips = new ArrayList<String>();
        for (String p : prefixes) {
            for (int i = 1; i <= 254; i++) ips.add(p + "." + i);
        }

        // ---- 第一步：并行探 445 端口（只要连得上就算 SMB 服务器）----
        final int connectTimeout = 450;
        List<java.util.concurrent.Callable<String>> tasks =
                new ArrayList<java.util.concurrent.Callable<String>>();
        for (final String ip : ips) {
            tasks.add(new java.util.concurrent.Callable<String>() {
                @Override public String call() {
                    java.net.Socket s = new java.net.Socket();
                    try {
                        s.connect(new java.net.InetSocketAddress(ip, SMB_PORT), connectTimeout);
                        return ip;
                    } catch (Throwable t) {
                        return null;
                    } finally {
                        try { s.close(); } catch (Throwable ignore) { }
                    }
                }
            });
        }

        int threads = Math.min(64, Math.max(16, ips.size() / 8));
        java.util.concurrent.ExecutorService pool =
                java.util.concurrent.Executors.newFixedThreadPool(threads);
        List<String> alive = new ArrayList<String>();
        try {
            List<java.util.concurrent.Future<String>> fs = pool.invokeAll(
                    tasks, Math.max(3000, budgetMs), java.util.concurrent.TimeUnit.MILLISECONDS);
            for (java.util.concurrent.Future<String> f : fs) {
                try {
                    String ip = f.get();
                    if (ip != null) alive.add(ip);
                } catch (Throwable ignore) { }
            }
        } catch (Throwable ignore) { }

        // 按末段数字排序，看起来才像正常的地址表
        java.util.Collections.sort(alive, new java.util.Comparator<String>() {
            @Override public int compare(String a, String b) {
                return lastOctet(a) - lastOctet(b);
            }
        });

        // ---- 第二步：对每台机器枚举共享（并行、有上限）----
        final List<Map<String, Object>> hosts =
                java.util.Collections.synchronizedList(new ArrayList<Map<String, Object>>());
        int cap = Math.min(alive.size(), 16);
        if (cap > 0) {
            List<java.util.concurrent.Callable<Void>> probes =
                    new ArrayList<java.util.concurrent.Callable<Void>>();
            for (int i = 0; i < cap; i++) {
                final String ip = alive.get(i);
                probes.add(new java.util.concurrent.Callable<Void>() {
                    @Override public Void call() {
                        String nm = "";
                        try {
                            java.net.InetAddress a = java.net.InetAddress.getByName(ip);
                            String h = a.getCanonicalHostName();
                            if (h != null && !h.isEmpty() && !h.equals(ip)) nm = h;
                        } catch (Throwable ignore) { }
                        Map<String, Object> sh = shares(ip, user, password, guest);
                        String err = Json.s(sh, "error");
                        hosts.add(Json.map("host", ip, "name", nm,
                                "shares", sh.get("shares") == null ? new ArrayList<Object>() : sh.get("shares"),
                                "error", err));
                        return null;
                    }
                });
            }
            try {
                pool.invokeAll(probes, Math.max(4000, budgetMs), java.util.concurrent.TimeUnit.MILLISECONDS);
            } catch (Throwable ignore) { }
        }
        pool.shutdownNow();

        List<Object> out = new ArrayList<Object>();
        for (Map<String, Object> h : hosts) {
            out.add(Json.map("host", Json.s(h, "host"), "name", Json.s(h, "name"),
                    "shares", h.get("shares"), "error", Json.s(h, "error")));
        }
        // 没赶上枚举的机器也列出来，让用户至少能点进去看
        if (out.size() < alive.size()) {
            java.util.Set<String> done = new java.util.LinkedHashSet<String>();
            for (Object o : out) done.add(Json.s(Json.asMap(o), "host"));
            for (String ip : alive) {
                if (done.contains(ip)) continue;
                out.add(Json.map("host", ip, "name", "", "shares", new ArrayList<Object>(),
                        "error", "枚举共享超时，可直接点进去浏览"));
            }
        }

        return Json.map("ok", true, "hosts", out, "prefixes", prefixes,
                "ms", System.currentTimeMillis() - t0);
    }

    private static int lastOctet(String ip) {
        try {
            int d = ip.lastIndexOf('.');
            return Integer.parseInt(ip.substring(d + 1));
        } catch (Throwable t) { return 999; }
    }

    /**
     * 列出某台服务器上的共享名（相当于「网络邻居」里点开一台电脑）。
     * 有些服务器不允许匿名枚举，这时返回 ok=false + 提示，让用户手填共享名。
     */
    public static Map<String, Object> shares(String host, String user, String password, boolean guest) {
        List<Object> out = new ArrayList<Object>();
        try {
            Conn c = new Conn(host, "", "", user, password, guest);
            SmbFile root = new SmbFile("smb://" + host + "/", ctx(c));
            SmbFile[] kids = root.listFiles();
            if (kids != null) {
                for (SmbFile k : kids) {
                    try {
                        String n = k.getName();
                        while (n.startsWith("/")) n = n.substring(1);
                        while (n.endsWith("/")) n = n.substring(0, n.length() - 1);
                        if (n.isEmpty()) continue;
                        if ("IPC$".equalsIgnoreCase(n) || "print$".equalsIgnoreCase(n)) continue;
                        if (!k.isDirectory()) continue;
                        out.add(Json.map("name", n));
                    } catch (Throwable ignore) { }
                }
            }
            java.util.Collections.sort(out, new java.util.Comparator<Object>() {
                @Override public int compare(Object a, Object b) {
                    return Json.s(Json.asMap(a), "name").compareToIgnoreCase(Json.s(Json.asMap(b), "name"));
                }
            });
            if (out.isEmpty()) {
                return Json.map("ok", false, "shares", out,
                        "error", "服务器不允许列出共享名，请手动填写共享名");
            }
            return Json.map("ok", true, "shares", out);
        } catch (Throwable t) {
            return Json.map("ok", false, "shares", out, "error", describe(t));
        }
    }

    /**
     * 浏览共享里的子目录（逐级往下点）。
     * rel 是相对共享根的路径，空串表示共享根。
     *
     * @return {ok, path, parent, dirs:[{name,rel}], audio_files, files}
     */
    public static Map<String, Object> browseDir(Conn c, String rel) {
        String r = rel == null ? "" : rel;
        r = r.replace('\\', '/');
        while (r.startsWith("/")) r = r.substring(1);
        while (r.endsWith("/")) r = r.substring(0, r.length() - 1);
        r = r.replaceAll("/{2,}", "/");
        try {
            SmbFile dir = file(url(c, r), c);
            if (!dir.exists()) {
                return Json.map("ok", false, "error", "目录不存在或没有权限");
            }
            SmbFile[] kids = dir.listFiles();
            List<Object> dirs = new ArrayList<Object>();
            int audio = 0, files = 0;
            if (kids != null) {
                for (SmbFile k : kids) {
                    try {
                        String name = k.getName();
                        while (name.startsWith("/")) name = name.substring(1);
                        while (name.endsWith("/")) name = name.substring(0, name.length() - 1);
                        if (name.isEmpty() || name.startsWith(".")) continue;
                        String child = r.isEmpty() ? name : r + "/" + name;
                        if (k.isDirectory()) {
                            dirs.add(Json.map("name", name, "rel", child));
                        } else if (Util.isAudio(name)) {
                            audio++;
                        } else {
                            files++;
                        }
                    } catch (Throwable ignore) { }
                }
            }
            java.util.Collections.sort(dirs, new java.util.Comparator<Object>() {
                @Override public int compare(Object a, Object b) {
                    return Json.s(Json.asMap(a), "name").compareToIgnoreCase(Json.s(Json.asMap(b), "name"));
                }
            });
            String parent = "";
            if (!r.isEmpty()) {
                int s = r.lastIndexOf('/');
                parent = s > 0 ? r.substring(0, s) : "";
            }
            return Json.map("ok", true, "path", r, "parent", parent,
                    "dirs", dirs, "audio_files", audio, "files", files);
        } catch (Throwable t) {
            return Json.map("ok", false, "error", describe(t));
        }
    }
}
