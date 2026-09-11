package com.dlna.speaker;

import java.io.File;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/**
 * HTTP API 层
 * ===========
 * 把前端（WebView 里的 SPA）原本调用的那套接口在本机实现出来，
 * 于是整个 App 不再依赖 iStoreOS 上的服务，换任何网络都能独立运行。
 *
 * 在线音乐部分与旧架构的区别：
 *   旧：前端 -> Python 服务 -> Node 桥(bridge) -> 音源插件
 *   新：前端就地用 WebView 里的插件运行时搜索/解析，再把「直链 + 请求头」
 *       通过 /api/online/register 交给本层，由本层代理成音响可拉取的地址。
 */
public final class Api implements HttpSrv.Handler {

    /** 由宿主（Android 或桌面）提供静态资源读取 */
    public interface AssetLoader {
        byte[] load(String path);
        String mimeType(String path);
        /** 列目录（音源插件需要枚举 assets/plugins）。默认空实现，兼容老宿主。 */
        default String[] list(String dir) { return new String[0]; }
    }

    private final DeviceManager dm = new DeviceManager();
    private final Player player = new Player(dm);
    private final Library library = new Library();
    private final AssetLoader assets;
    private final Downloader downloader;
    private final Storage storage;
    private final MusicDirs musicDirs;
    private final int port;

    /** 宿主数据目录（音源插件用），可空 */
    private volatile File dataDir;
    private volatile Plugins pluginStore;

    /** sid -> {url, headers, expires}：前端解析出的在线直链 */
    private final Map<String, Map<String, Object>> streams = new ConcurrentHashMap<String, Map<String, Object>>();
    private static final long STREAM_TTL_MS = 30 * 60 * 1000L;

    private volatile String cachedIp = "";
    private volatile long cachedIpAt = 0;

    public Api(int port, AssetLoader assets, Storage storage, MusicDirs musicDirs) {
        this.port = port;
        this.assets = assets;
        this.storage = storage;
        this.musicDirs = musicDirs;
        this.downloader = new Downloader(storage);
        this.player.setUrlBuilder(new Player.UrlBuilder() {
            @Override public String build(Map<String, Object> t) {
                String src = Json.s(t, "source", "local");
                if ("online".equals(src)) {
                    String sid = Json.s(t, "sid");
                    if (sid.isEmpty()) return Json.s(t, "url");
                    return baseUrl() + "/stream?sid=" + Util.urlEncode(sid);
                }
                if ("dlna".equals(src)) return Json.s(t, "url");
                String id = Json.s(t, "id");
                if (id.isEmpty()) return Json.s(t, "url");
                return baseUrl() + "/media?id=" + Util.urlEncode(id);
            }
        });
    }

    public DeviceManager devices() { return dm; }
    public Player player() { return player; }
    public Library library() { return library; }

    /**
     * 给宿主的数据目录，音源插件的用户自建部分存放在这里。
     * Android 传 getFilesDir()，桌面回归传 build/live。
     */
    public void setDataDir(File d) {
        this.dataDir = d;
        this.pluginStore = null;
    }

    /** 音源仓库（懒加载，避免每次请求都扫一遍磁盘） */
    private Plugins plugins() {
        Plugins p = pluginStore;
        if (p == null) {
            synchronized (this) {
                p = pluginStore;
                if (p == null) {
                    p = new Plugins(assets, dataDir);
                    pluginStore = p;
                }
            }
        }
        return p;
    }

    /** 启动后台调度器 */
    public void startScheduler() {
        Thread t = new Thread(new Runnable() {
            @Override public void run() { player.schedulerLoop(1000); }
        }, "player-sched");
        t.setDaemon(true);
        t.start();
        // 设备在线状态轮询：让设备列表显示实时状态，而不是等选中后才更新
        Thread p = new Thread(new Runnable() {
            @Override public void run() {
                while (!Thread.currentThread().isInterrupted()) {
                    try {
                        if (!player.isPlaying()) {
                            List<String> udns = new ArrayList<String>();
                            for (Dlna.DeviceInfo d : dm.allRenderers()) udns.add(d.udn);
                            if (!udns.isEmpty()) dm.pollStatus(udns);
                        }
                    } catch (Throwable ignore) {
                        // 轮询失败不能终止线程
                    }
                    try { Thread.sleep(4000); } catch (InterruptedException e) { return; }
                }
            }
        }, "dev-poll");
        p.setDaemon(true);
        p.start();
    }

    /** 本机在局域网中的地址（音响要能访问到，所以不能是 127.0.0.1） */
    public String hostIp() {
        long now = System.currentTimeMillis();
        if (!cachedIp.isEmpty() && now - cachedIpAt < 30000) return cachedIp;
        String ip = "";
        // 优先选与已发现音响同网段的本机地址
        for (Dlna.DeviceInfo d : dm.allRenderers()) {
            int dot = d.ip.lastIndexOf('.');
            if (dot > 0) {
                String prefix = d.ip.substring(0, dot + 1);
                for (String mine : Dlna.localIps()) {
                    if (mine.startsWith(prefix)) { ip = mine; break; }
                }
            }
            if (!ip.isEmpty()) break;
        }
        if (ip.isEmpty()) {
            List<String> ips = Dlna.localIps();
            ip = ips.isEmpty() ? "127.0.0.1" : ips.get(0);
        }
        cachedIp = ip;
        cachedIpAt = now;
        return ip;
    }

    public String baseUrl() { return "http://" + hostIp() + ":" + port; }

    /* ------------------------------------------------------------ 分发 */

    @Override public void handle(HttpSrv.Req req, HttpSrv.Res res) throws Exception {
        String p = req.path;
        if (p == null) p = "/";
        try {
            if ("OPTIONS".equals(req.method)) { res.status = 204; return; }

            if (p.equals("/") || p.equals("/index.html")) { serveAsset("www/index.html", res); return; }
            if (p.equals("/media")) { media(req, res); return; }
            if (p.equals("/stream")) { stream(req, res); return; }
            if (p.equals("/__proxy")) { proxy(req, res); return; }

            if (p.startsWith("/api/")) { api(req, res, p); return; }

            // 其余当静态资源（assets/www 下）
            if (assets != null) {
                String rel = p.startsWith("/") ? p.substring(1) : p;
                byte[] data = assets.load("www/" + rel);
                if (data != null) {
                    res.send(200, assets.mimeType(rel), data);
                    res.set("Cache-Control", "no-cache");
                    return;
                }
            }
            res.text(404, "not found");
        } catch (Throwable e) {
            res.json(500, Json.map("ok", false, "msg", String.valueOf(e)));
        }
    }

    private void serveAsset(String path, HttpSrv.Res res) {
        if (assets == null) { res.text(404, "no assets"); return; }
        byte[] data = assets.load(path);
        if (data == null) { res.text(404, "not found: " + path); return; }
        res.send(200, assets.mimeType(path), data);
        res.set("Cache-Control", "no-cache");
    }

    /* ------------------------------------------------------------ API */

    private void api(HttpSrv.Req req, HttpSrv.Res res, String path) throws Exception {
        // ---------------------------------------------------- 基础状态
        if (path.equals("/api/health")) {
            dm.refreshAsync();
            res.json(Json.map(
                    "ok", true,
                    "host_ip", hostIp(),
                    "base_url", baseUrl(),
                    "music_dir", dirProviderHint(),
                    "renderers", dm.allRenderers().size(),
                    "servers", dm.allServers().size(),
                    "library", library.count(),
                    "library_scanning", library.isScanning(),
                    "last_scan", dm.getLastScan()
            ));
            return;
        }

        if (path.equals("/api/state")) {
            List<Object> devices = new ArrayList<Object>();
            Map<String, Map<String, Object>> status = dm.statusMap();
            for (Dlna.DeviceInfo r : dm.allRenderers()) {
                Map<String, Object> d = r.toMap();
                Map<String, Object> st = status.get(r.udn);
                if (st != null) {
                    d.put("online", st.get("online"));
                    d.put("state", st.get("state"));
                    d.put("volume", st.get("volume"));
                    d.put("mute", st.get("mute"));
                    d.put("position", st.get("position"));
                    d.put("duration", st.get("duration"));
                    d.put("title", st.get("title"));
                    d.put("uri", st.get("uri"));
                    d.put("position_sec", st.get("position_sec"));
                    d.put("duration_sec", st.get("duration_sec"));
                } else {
                    d.put("online", false);
                    d.put("state", "UNKNOWN");
                }
                d.put("selected", player.getTargets().contains(r.udn));
                d.put("delay_ms", player.getDelays().containsKey(r.udn) ? player.getDelays().get(r.udn) : 0);
                devices.add(d);
            }
            List<Object> servers = new ArrayList<Object>();
            for (Dlna.DeviceInfo s : dm.allServers()) servers.add(s.toMap());
            res.json(Json.map(
                    "devices", devices,
                    "servers", servers,
                    "player", player.snapshot(),
                    "host_ip", hostIp(),
                    "base_url", baseUrl(),
                    "last_scan", dm.getLastScan(),
                    "scanning", dm.isScanning(),
                    "library", library.count(),
                    "library_scanning", library.isScanning()
            ));
            return;
        }

        if (path.equals("/api/scan")) {
            dm.refreshAsync();
            res.json(Json.map("ok", true, "async", true));
            return;
        }

        if (path.equals("/api/targets")) {
            Map<String, Object> body = req.json();
            List<String> udns = new ArrayList<String>();
            Object raw = body.get("udns");
            if (raw instanceof List) {
                for (Object o : (List<?>) raw) if (o != null) udns.add(String.valueOf(o));
            } else if (raw instanceof String) {
                udns.add((String) raw);
            }
            player.setTargets(udns);
            res.json(Json.map("ok", true, "targets", new ArrayList<Object>(player.getTargets())));
            return;
        }

        if (path.equals("/api/delay")) {
            Map<String, Object> body = req.json();
            String udn = Json.s(body, "udn");
            if (udn.isEmpty()) { res.json(400, Json.map("ok", false, "msg", "缺少 udn")); return; }
            int d = player.setDelay(udn, Json.i(body, "delay_ms", 0));
            res.json(Json.map("ok", true, "udn", udn, "delay_ms", d));
            return;
        }

        // ---------------------------------------------------- 曲库
        if (path.equals("/api/library")) {
            libraryApi(req, res);
            return;
        }

        if (path.equals("/api/search")) {
            List<Object> out = new ArrayList<Object>();
            for (Map<String, Object> t : library.search(req.param("q", ""))) out.add(player.publicTrack(t));
            res.json(Json.map("ok", true, "items", out, "total", out.size()));
            return;
        }

        if (path.equals("/api/library/rescan") || path.equals("/api/music/rescan")) {
            library.scanAsync();
            res.json(Json.map("ok", true, "msg", "已开始扫描", "scanning", true));
            return;
        }

        if (path.equals("/api/music/sources")) {
            res.json(Json.map(
                    "ok", true, "sources", sourceList(), "active", "device",
                    "active_dir", storage == null ? "" : storage.describe(),
                    "nsenter", false, "host_mount_root", "",
                    "download_dir", storage == null ? "" : storage.describe(),
                    "custom_dir", storage != null && storage.isCustom(),
                    "custom_name", storage == null ? "" : storage.customName()
            ));
            return;
        }

        if (path.equals("/api/music/sources/add")) {
            addSource(req, res);
            return;
        }

        if (path.equals("/api/music/sources/test")) {
            testSource(req, res);
            return;
        }

        if (path.equals("/api/music/sources/remove")) {
            Map<String, Object> b = req.json();
            String sid = Json.s(b, "id");
            boolean ok = musicDirs != null && musicDirs.remove(sid);
            if (ok) library.scanAsync();
            res.json(Json.map("ok", ok, "msg", ok ? "已删除" : "没找到该目录"));
            return;
        }

        // 扫描局域网里开着 445 的机器（SMB 服务器），顺便枚举共享名
        if (path.equals("/api/smb/scan")) {
            Map<String, Object> b = req.json();
            res.json(Smb.discover(Json.s(b, "user"), Json.s(b, "password"),
                    Json.b(b, "guest", false), 12000));
            return;
        }

        // 浏览：share 为空 → 列出服务器上的共享；否则列出该共享下的子目录
        if (path.equals("/api/smb/browse")) {
            Map<String, Object> b = req.json();
            String host = Json.s(b, "host");
            String share = Json.s(b, "share");
            String sub = Json.s(b, "subpath");
            String user = Json.s(b, "user");
            String pass = Json.s(b, "password");
            boolean guest = Json.b(b, "guest", false);
            if (host.isEmpty()) {
                res.json(Json.map("ok", false, "error", "请先填写主机名或 IP"));
                return;
            }
            if (share.isEmpty()) {
                res.json(Smb.shares(host, user, pass, guest));
                return;
            }
            res.json(Smb.browseDir(new Smb.Conn(host, share, "", user, pass, guest), sub));
            return;
        }

        /* ---------------------------------------------------- 音源插件 */
        if (path.equals("/api/plugins")) {
            res.json(Json.map("ok", true, "list", plugins().list(),
                    "dir", plugins().dirPath()));
            return;
        }
        if (path.equals("/api/plugins/code")) {
            res.json(Json.map("ok", true, "list", plugins().loadEnabled()));
            return;
        }
        if (path.equals("/api/plugins/install")) {
            Map<String, Object> b = req.json();
            res.json(plugins().install(Json.s(b, "url"), Json.s(b, "code"),
                    Json.s(b, "name"), 0));
            return;
        }
        if (path.equals("/api/plugins/remove")) {
            res.json(plugins().remove(Json.s(req.json(), "name")));
            return;
        }
        if (path.equals("/api/plugins/toggle")) {
            Map<String, Object> b = req.json();
            res.json(plugins().toggle(Json.s(b, "name"), Json.b(b, "enabled", true)));
            return;
        }

        // 本机模式没有「挂载 / 切换激活源」这套概念：添加过的目录始终都生效
        if (path.equals("/api/music/sources/active")
                || path.equals("/api/music/sources/mount")
                || path.equals("/api/music/sources/unmount")) {
            res.json(Json.map("ok", true, "msg", "本机模式下所有目录同时生效，无需挂载"));
            return;
        }

        // 下载目录设置
        if (path.equals("/api/storage")) {
            storageApi(req, res);
            return;
        }

        // 歌词
        if (path.equals("/api/lyric")) {
            lyricApi(req, res);
            return;
        }

        if (path.equals("/api/music/browse")) {
            String dir = req.param("path", "");
            List<Object> dirs = new ArrayList<Object>();
            for (Map<String, Object> f : library.folders(dir)) dirs.add(f);
            String parent = "";
            if (!dir.isEmpty()) {
                int s = dir.lastIndexOf('/');
                parent = s > 0 ? dir.substring(0, s) : "";
            }
            List<Object> roots = new ArrayList<Object>();
            roots.add(Json.map("name", "手机音乐", "path", "", "desc", "按文件夹浏览已扫描到的音乐"));
            res.json(Json.map(
                    "ok", true, "path", dir, "parent", parent,
                    "root", "", "root_name", "手机音乐", "roots", roots,
                    "dirs", dirs, "audio_files", 0, "writable", true
            ));
            return;
        }

        // ---------------------------------------------------- 播放控制
        if (path.equals("/api/play")) { play(req, res); return; }
        if (path.equals("/api/play-container")) { playContainer(req, res); return; }
        if (path.equals("/api/mode")) {
            Map<String, Object> b = req.json();
            String rep = b.get("repeat") == null ? null : Json.s(b, "repeat");
            Boolean shf = b.get("shuffle") == null ? null : Boolean.valueOf(Json.b(b, "shuffle", false));
            player.setMode(rep, shf);
            res.json(Json.map("ok", true, "repeat", player.getRepeat(), "shuffle", player.isShuffle()));
            return;
        }
        if (path.equals("/api/control")) {
            Map<String, Object> b = req.json();
            boolean ok = player.control(Json.s(b, "action"), stringList(b.get("udns")));
            res.json(Json.map("ok", ok, "result", ok ? "ok" : player.getLastError()));
            return;
        }
        if (path.equals("/api/volume")) {
            Map<String, Object> b = req.json();
            boolean ok = player.setVolume(Json.i(b, "volume", 50), stringList(b.get("udns")));
            res.json(Json.map("ok", ok, "result", ok ? "ok" : "音量设置失败"));
            return;
        }
        if (path.equals("/api/seek")) {
            Map<String, Object> b = req.json();
            boolean ok = player.seek(Json.i(b, "position", 0), stringList(b.get("udns")));
            res.json(Json.map("ok", ok, "result", ok ? "ok" : "跳转失败"));
            return;
        }
        if (path.equals("/api/resync")) {
            boolean ok = player.resync();
            res.json(Json.map("ok", ok, "result", ok ? "ok" : "校准失败"));
            return;
        }
        if (path.equals("/api/jump")) {
            Map<String, Object> b = req.json();
            boolean ok = player.jump(Json.i(b, "index", 0));
            res.json(Json.map("ok", ok, "result", ok ? "ok" : "跳转失败"));
            return;
        }
        if (path.equals("/api/queue")) {
            if ("DELETE".equals(req.method)) { player.queueClear(); res.json(Json.map("ok", true)); return; }
            Map<String, Object> b = req.json();
            String action = Json.s(b, "action", "add");
            if ("add".equals(action)) {
                player.queueAdd(trackList(b.get("tracks")));
                res.json(Json.map("ok", true, "total", player.queueSize()));
                return;
            }
            if ("remove".equals(action)) {
                boolean ok = player.queueRemove(Json.i(b, "index", -1));
                res.json(Json.map("ok", ok, "total", player.queueSize()));
                return;
            }
            if ("clear".equals(action)) { player.queueClear(); res.json(Json.map("ok", true)); return; }
            res.json(400, Json.map("ok", false, "msg", "未知 action"));
            return;
        }

        // 本机播放：前端 <audio> 播完时通报，用于自动续播
        if (path.equals("/api/phone/ended")) {
            String rep = player.getRepeat();
            boolean ok;
            if ("one".equals(rep)) ok = player.playIndex(player.getIndex());
            else ok = player.next();
            res.json(Json.map("ok", ok, "index", player.getIndex(), "playing", player.isPlaying()));
            return;
        }

        // ---------------------------------------------------- 在线相关
        if (path.equals("/api/online/register")) {
            Map<String, Object> b = req.json();
            String url = Json.s(b, "url");
            if (url.isEmpty()) { res.json(400, Json.map("ok", false, "msg", "缺少 url")); return; }
            String sid = UUID.randomUUID().toString().replace("-", "").substring(0, 16);
            Map<String, Object> entry = Json.map();
            entry.put("url", url);
            entry.put("headers", b.get("headers"));
            entry.put("expires", System.currentTimeMillis() + STREAM_TTL_MS);
            streams.put(sid, entry);
            res.json(Json.map("ok", true, "sid", sid, "url", baseUrl() + "/stream?sid=" + sid));
            return;
        }
        if (path.equals("/api/online/download")) {
            Map<String, Object> b = req.json();
            List<Object> items = Json.asList(b.get("items"));
            res.json(downloader.add(items, Json.s(b, "target_dir")));
            return;
        }
        if (path.equals("/api/online/downloads")) {
            res.json(downloader.status());
            return;
        }
        if (path.equals("/api/online/downloads/clear")) {
            downloader.clear();
            res.json(Json.map("ok", true));
            return;
        }

        res.json(404, Json.map("ok", false, "msg", "未知接口: " + path));
    }

    /* ------------------------------------------------------------ 曲库 */

    private void libraryApi(HttpSrv.Req req, HttpSrv.Res res) {
        if (!library.enabled()) {
            res.json(400, Json.map("ok", false, "msg", "本机曲库不可用"));
            return;
        }
        String container = req.param("container", "");
        if (!library.ready()) {
            if (!library.isScanning()) library.scanAsync();
            res.json(Json.map(
                    "ok", true, "source", "local", "container", container,
                    "folders", new ArrayList<Object>(), "items", new ArrayList<Object>(),
                    "total", 0, "scanning", true, "scanned", library.count(),
                    "truncated", false, "last_scan", library.getLastScan(),
                    "error", library.getLastError()
            ));
            return;
        }
        List<Object> items = new ArrayList<Object>();
        for (Map<String, Object> t : library.list(container, false)) items.add(player.publicTrack(t));
        List<Object> folders = new ArrayList<Object>();
        for (Map<String, Object> f : library.folders(container)) folders.add(f);
        res.json(Json.map(
                "ok", true, "source", "local", "container", container,
                "folders", folders, "items", items, "total", items.size(),
                "scanning", library.isScanning(), "scanned", library.count(),
                "truncated", library.isTruncated(), "last_scan", library.getLastScan(),
                "error", library.getLastError()
        ));
    }

    /* ------------------------------------------------------------ 播放 */

    private void play(HttpSrv.Req req, HttpSrv.Res res) {
        Map<String, Object> b = req.json();
        List<Map<String, Object>> tracks = trackList(b.get("tracks"));
        if (tracks.isEmpty()) { res.json(400, Json.map("ok", false, "msg", "没有曲目")); return; }
        List<String> udns = stringList(b.get("udns"));
        if (udns != null) player.setTargets(udns);
        boolean ok = player.playTracks(tracks, Json.i(b, "index", 0));
        res.json(Json.map("ok", ok, "result", ok ? "ok" : player.getLastError(),
                "output", player.getTargets().isEmpty() ? "phone" : "dlna"));
    }

    private void playContainer(HttpSrv.Req req, HttpSrv.Res res) {
        Map<String, Object> b = req.json();
        String source = Json.s(b, "source", "local");
        String container = Json.s(b, "container", "");
        List<Map<String, Object>> tracks;
        if ("dlna".equals(source)) {
            List<Dlna.DeviceInfo> servers = dm.allServers();
            if (servers.isEmpty()) { res.json(404, Json.map("ok", false, "msg", "未发现媒体服务器")); return; }
            tracks = gatherDlnaTracks(new Dlna.MediaServer(servers.get(0)), container, 0, 6);
        } else {
            if (!library.ready()) library.scanAsync();
            tracks = library.list(container, true);
        }
        if (tracks.isEmpty()) { res.json(404, Json.map("ok", false, "msg", "该目录没有可播放的曲目")); return; }
        boolean ok = player.playTracks(tracks, Json.i(b, "index", 0));
        res.json(Json.map("ok", ok, "result", ok ? "ok" : player.getLastError(), "total", tracks.size()));
    }

    private List<Map<String, Object>> gatherDlnaTracks(Dlna.MediaServer ms, String container, int depth, int maxDepth) {
        List<Map<String, Object>> out = new ArrayList<Map<String, Object>>();
        if (depth > maxDepth) return out;
        Dlna.BrowseResult br = ms.browse(container, 0, 100000, "");
        if (!br.ok) return out;
        for (Map<String, Object> it : br.items) {
            if ("item".equals(Json.s(it, "type"))) {
                out.add(normDlnaTrack(it));
            } else if ("container".equals(Json.s(it, "type"))) {
                out.addAll(gatherDlnaTracks(ms, Json.s(it, "id"), depth + 1, maxDepth));
            }
        }
        return out;
    }

    /** DLNA 媒体服务器里的曲目 -> 内部曲目结构（url 是外部 http 地址，直接推给音响） */
    private Map<String, Object> normDlnaTrack(Map<String, Object> it) {
        Map<String, Object> m = Json.map();
        String dur = Json.s(it, "duration");
        String nd = Dlna.normDuration(dur);
        m.put("id", Json.s(it, "id"));
        m.put("title", Json.s(it, "title"));
        m.put("artist", Json.s(it, "artist"));
        m.put("album", Json.s(it, "album"));
        m.put("url", Json.s(it, "url"));
        m.put("duration", nd);
        m.put("duration_sec", Dlna.tsecToSec(nd));
        m.put("source", "dlna");
        return m;
    }

    /* ------------------------------------------------------ 媒体服务 */

    /** 本地曲目：给音响拉流，支持 Range */
    private void media(HttpSrv.Req req, HttpSrv.Res res) throws Exception {
        String id = req.param("id", "");
        if (id.isEmpty()) { res.text(400, "missing id"); return; }
        Map<String, Object> track = library.byId(id);
        String name = track == null ? id : Json.s(track, "path", Json.s(track, "title"));
        String mime = Util.mimeOf(name);
        long size = library.sizeOf(id);
        final InputStream in = library.open(id);
        if (size <= 0) {
            // 大小未知：直接全量输出并断开连接
            res.set("Content-Type", mime);
            res.closeAfter = true;
            res.streamer = new HttpSrv.Streamer() {
                @Override public void write(OutputStream out) throws Exception {
                    try {
                        byte[] buf = new byte[65536];
                        int n;
                        while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
                    } finally {
                        try { in.close(); } catch (Exception ignore) { }
                    }
                }
            };
            return;
        }
        long start = 0, end = size - 1;
        boolean partial = false;
        String range = req.header("range");
        if (range != null && range.startsWith("bytes=")) {
            String spec = range.substring(6).split(",")[0].trim();
            int dash = spec.indexOf('-');
            try {
                if (dash > 0) {
                    start = Long.parseLong(spec.substring(0, dash));
                    if (dash + 1 < spec.length()) end = Long.parseLong(spec.substring(dash + 1));
                } else if (dash == 0 && spec.length() > 1) {
                    start = Math.max(0, size - Long.parseLong(spec.substring(1)));
                }
                if (end >= size) end = size - 1;
                if (start > end || start >= size) {
                    in.close();
                    res.set("Content-Range", "bytes */" + size);
                    res.text(416, "range not satisfiable");
                    return;
                }
                partial = true;
            } catch (Exception ignore) { partial = false; start = 0; end = size - 1; }
        }
        final long fStart = start;
        final long len = end - start + 1;
        res.set("Content-Type", mime);
        res.set("Accept-Ranges", "bytes");
        res.set("Content-Length", String.valueOf(len));
        if (partial) {
            res.status = 206;
            res.set("Content-Range", "bytes " + start + "-" + end + "/" + size);
        } else {
            res.status = 200;
        }
        res.closeAfter = true;
        res.streamer = new HttpSrv.Streamer() {
            @Override public void write(OutputStream out) throws Exception {
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

    /** 在线直链：带 Referer/Cookie 等请求头去抓，边下边回灌，并透传 Range */
    private void stream(HttpSrv.Req req, HttpSrv.Res res) throws Exception {
        String sid = req.param("sid", "");
        Map<String, Object> entry = streams.get(sid);
        if (entry == null) { res.text(404, "stream expired"); return; }
        long expires = Json.l(entry, "expires", 0L);
        if (expires > 0 && System.currentTimeMillis() > expires) {
            streams.remove(sid);
            res.text(410, "stream expired");
            return;
        }
        String url = Json.s(entry, "url");
        @SuppressWarnings("unchecked")
        Map<String, Object> hdrs = (Map<String, Object>) entry.get("headers");

        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setConnectTimeout(15000);
        c.setReadTimeout(30000);
        c.setInstanceFollowRedirects(true);
        if (hdrs != null) {
            for (Map.Entry<String, Object> e : hdrs.entrySet()) {
                if (e.getValue() == null) continue;
                String k = e.getKey().toLowerCase(Locale.ROOT);
                if ("host".equals(k) || "content-length".equals(k) || "connection".equals(k)) continue;
                c.setRequestProperty(e.getKey(), String.valueOf(e.getValue()));
            }
        }
        String range = req.header("range");
        if (range != null && !range.isEmpty()) c.setRequestProperty("Range", range);

        int code = c.getResponseCode();
        res.status = code;
        String ct = c.getContentType();
        res.set("Content-Type", ct == null ? "audio/mpeg" : ct);
        copyHeader(c, res, "Content-Length", "Content-Length");
        copyHeader(c, res, "Content-Range", "Content-Range");
        copyHeader(c, res, "Accept-Ranges", "Accept-Ranges");
        res.set("Cache-Control", "no-cache");
        res.closeAfter = true;
        final HttpURLConnection conn = c;
        res.streamer = new HttpSrv.Streamer() {
            @Override public void write(OutputStream out) throws Exception {
                InputStream in = null;
                try {
                    in = conn.getInputStream();
                    byte[] buf = new byte[65536];
                    int n;
                    while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
                } finally {
                    try { if (in != null) in.close(); } catch (Exception ignore) { }
                    try { conn.disconnect(); } catch (Exception ignore) { }
                }
            }
        };
    }

    private static void copyHeader(HttpURLConnection c, HttpSrv.Res res, String from, String to) {
        String v = c.getHeaderField(from);
        if (v != null && !v.isEmpty()) res.set(to, v);
    }

    /* ---------------------------------------------------- 插件通用代理 */

    /**
     * 插件运行时的请求出口。
     * 请求体：{url, method, headers:{}, body:<base64>, timeout}
     * 响应体：{status, statusText, headers:{}, body:<base64>, finalUrl}
     *
     * 之所以要这一层：音源接口不带 CORS 头，且需要 Referer/Cookie 等
     * 浏览器禁止 JS 设置的请求头，必须由原生侧代发。
     */
    private void proxy(HttpSrv.Req req, HttpSrv.Res res) {
        Map<String, Object> b = req.json();
        String url = Json.s(b, "url");
        if (url.isEmpty()) { res.json(400, Json.map("transportError", "缺少 url")); return; }
        String method = Json.s(b, "method", "GET");
        int timeout = Json.i(b, "timeout", 20000) / 1000;
        if (timeout <= 0) timeout = 20;

        Map<String, String> headers = new LinkedHashMap<String, String>();
        Object h = b.get("headers");
        if (h instanceof Map) {
            for (Map.Entry<String, Object> e : Json.asMap(h).entrySet()) {
                if (e.getValue() != null) headers.put(e.getKey(), String.valueOf(e.getValue()));
            }
        }
        byte[] body = null;
        String b64 = Json.s(b, "body");
        if (!b64.isEmpty()) body = Util.unbase64(b64);

        Util.Resp r = Util.fetch(url, method, headers, body, Math.max(5, Math.min(timeout, 120)));
        if (r.error != null && r.status == 0) {
            res.json(Json.map("transportError", r.error));
            return;
        }
        Map<String, Object> out = Json.map();
        out.put("status", r.status);
        out.put("statusText", r.statusText);
        out.put("headers", r.headers);
        out.put("body", Util.base64(r.body));
        out.put("finalUrl", r.finalUrl);
        out.put("truncated", r.truncated);
        res.json(out);
    }

    /* ------------------------------------------------ 曲库源 / 下载目录 */

    /** 曲库来源清单：系统媒体库 + 用户添加的每个目录 */
    private List<Object> sourceList() {
        List<Object> src = new ArrayList<Object>();
        src.add(Json.map(
                "id", "device", "name", "手机媒体库", "type", "path",
                "path", "", "container_path", "系统媒体库 + 本机下载",
                "host", "", "share", "", "subpath", "", "guest", false,
                "readable", true, "writable", false,
                "audio_files", library.countBySrc("device"), "mounted", true,
                "desc", "系统媒体库 + 本机下载目录"
        ));
        if (musicDirs != null) {
            for (MusicDirs.Entry e : musicDirs.list()) {
                src.add(Json.map(
                        "id", e.id, "name", e.displayName(),
                        "type", e.type, "path", e.addr(),
                        "container_path", e.addr(),
                        "host", e.host, "share", e.share, "subpath", e.subpath,
                        "guest", e.guest,
                        "readable", true, "writable", true,
                        "audio_files", library.countBySrc(e.id), "mounted", true,
                        "desc", "smb".equals(e.type) ? "SMB 网络共享" : "本机目录"
                ));
            }
        }
        return src;
    }

    /** 添加曲库目录：SMB 直接连，SAF 用原生选择器给过来的 uri */
    private void addSource(HttpSrv.Req req, HttpSrv.Res res) throws Exception {
        if (musicDirs == null) {
            res.json(400, Json.map("ok", false, "msg", "当前环境不支持添加目录"));
            return;
        }
        Map<String, Object> b = req.json();
        String type = Json.s(b, "type", "smb");
        if ("smb".equals(type)) {
            Smb.Conn c = new Smb.Conn(
                    Json.s(b, "host"), Json.s(b, "share"), Json.s(b, "subpath"),
                    Json.s(b, "user"), Json.s(b, "password"), Json.b(b, "guest", false));
            if (c.host.isEmpty() || c.share.isEmpty()) {
                res.json(400, Json.map("ok", false, "msg", "请填主机和共享名"));
                return;
            }
            MusicDirs.Entry e = musicDirs.addSmb(c, Json.s(b, "name"));
            library.scanAsync();
            res.json(Json.map("ok", true, "id", e.id, "name", e.displayName(), "msg", "已添加"));
            return;
        }
        String uri = Json.s(b, "uri", Json.s(b, "path"));
        if (uri.isEmpty()) {
            res.json(400, Json.map("ok", false, "msg", "缺少目录地址"));
            return;
        }
        MusicDirs.Entry e = musicDirs.addSaf(android.net.Uri.parse(uri), Json.s(b, "name"));
        library.scanAsync();
        res.json(Json.map("ok", true, "id", e.id, "name", e.displayName(), "msg", "已添加"));
    }

    /** 测试 SMB 连接（会真的连一次，所以前端要给足超时） */
    private void testSource(HttpSrv.Req req, HttpSrv.Res res) throws Exception {
        Map<String, Object> b = req.json();
        Smb.Conn c = new Smb.Conn(
                Json.s(b, "host"), Json.s(b, "share"), Json.s(b, "subpath"),
                Json.s(b, "user"), Json.s(b, "password"), Json.b(b, "guest", false));
        if (c.host.isEmpty() || c.share.isEmpty()) {
            res.json(Json.map("ok", false, "error", "请填主机和共享名"));
            return;
        }
        Map<String, Object> r = Smb.probe(c);
        r.put("probe", Json.map("files", r.get("files"), "dirs", r.get("dirs")));
        res.json(r);
    }

    /** 下载目录：查询 / 自定义 / 恢复默认 / 改子目录名 */
    private void storageApi(HttpSrv.Req req, HttpSrv.Res res) throws Exception {
        if (storage == null) {
            res.json(400, Json.map("ok", false, "msg", "当前环境不支持"));
            return;
        }
        String method = req.method == null ? "GET" : req.method.toUpperCase(Locale.ROOT);
        if (!"GET".equals(method) && !"HEAD".equals(method)) {
            Map<String, Object> b = req.json();
            String action = Json.s(b, "action", "set");
            if ("reset".equals(action)) storage.clearCustom();
            else if ("custom".equals(action)) storage.setCustom(Json.s(b, "uri"), Json.s(b, "name"));
            else if ("subdir".equals(action)) storage.setSubDir(Json.s(b, "subdir"));
        }
        res.json(Json.map(
                "ok", true,
                "dir", storage.describe(),
                "custom", storage.isCustom(),
                "name", storage.customName(),
                "subdir", storage.subDir(),
                "path", storage.defaultDir().getAbsolutePath()
        ));
    }

    /** 本地歌词（同目录同名 .lrc）；在线曲目的歌词由前端插件运行时直接取 */
    private void lyricApi(HttpSrv.Req req, HttpSrv.Res res) {
        String id = req.param("id", "");
        String lrc = "";
        try {
            lrc = Lyrics.find(this, id);
        } catch (Throwable ignore) { }
        res.json(Json.map("ok", true, "lrc", lrc == null ? "" : lrc));
    }

    Map<String, Object> trackById(String id) { return library.byId(id); }

    MusicDirs musicDirsRef() { return musicDirs; }

    /* ------------------------------------------------------------ 工具 */

    private String dirProviderHint() {
        return storage == null ? "" : storage.describe();
    }

    private List<String> stringList(Object o) {
        if (o == null) return null;
        List<String> out = new ArrayList<String>();
        if (o instanceof List) {
            for (Object one : Json.asList(o)) if (one != null) out.add(String.valueOf(one));
        } else {
            out.add(String.valueOf(o));
        }
        return out;
    }

    private List<Map<String, Object>> trackList(Object o) {
        List<Map<String, Object>> out = new ArrayList<Map<String, Object>>();
        for (Object one : Json.asList(o)) {
            Map<String, Object> t = Json.asMap(one);
            if (t.isEmpty()) continue;
            out.add(t);
        }
        return out;
    }

    /** 取某个下载目录（供宿主展示） */
    public static File defaultDownloadsDir(File base) {
        File d = new File(base, "Music");
        if (!d.exists()) d.mkdirs();
        return d;
    }
}
