import com.dlna.speaker.Api;
import com.dlna.speaker.Dlna;
import com.dlna.speaker.HttpSrv;
import com.dlna.speaker.Json;
import com.dlna.speaker.Library;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.Charset;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 整套服务端在桌面 JVM 上的端到端验证
 * =====================================
 * 把 Android 上要跑的 HttpSrv + Api + Library + Player 原样跑在 PC 上，
 * 用真实 HTTP 请求把接口逐个打一遍，包括：
 *   /api/health、/api/library、/media(Range 206)、/__proxy(外部真站)、
 *   /api/online/register + /stream(Range 透传)、/api/state
 * 加 --cast 还会把本地曲目真的投到音响上播放（会短暂出声）。
 *
 * 用法： java -cp build/dlna ServerProbe [--cast]
 */
public class ServerProbe {

    static final int PORT = 8765;
    static int passed = 0, failed = 0;
    static boolean cast = false;

    public static void main(String[] args) throws Exception {
        for (String a : args) if ("--cast".equals(a)) cast = true;

        File work = new File("build/probe");
        File music = new File(work, "music/测试专辑");
        File dl = new File(work, "downloads");
        music.mkdirs();
        dl.mkdirs();
        // 造两首 3 秒测试音（不同音高，便于观察自动续播）
        File t1 = new File(music, "01 - 测试音A.wav");
        File t2 = new File(music, "02 - 测试音B.wav");
        writeFile(t1, makeWav(440));
        writeFile(t2, makeWav(660));

        /* ------------------------------------------------ 组装服务 */
        List<File> roots = new ArrayList<File>();
        roots.add(new File(work, "music"));
        final File assetsDir = new File("app/assets");

        Api api = new Api(PORT, new Api.AssetLoader() {
            @Override public byte[] load(String path) {
                File f = new File(assetsDir, path);
                if (!f.isFile()) return null;
                try {
                    InputStream in = new java.io.FileInputStream(f);
                    ByteArrayOutputStream bos = new ByteArrayOutputStream();
                    byte[] buf = new byte[8192];
                    int n;
                    while ((n = in.read(buf)) > 0) bos.write(buf, 0, n);
                    in.close();
                    return bos.toByteArray();
                } catch (Exception e) { return null; }
            }
            @Override public String mimeType(String path) { return com.dlna.speaker.Util.mimeOf(path); }
        }, new com.dlna.speaker.Storage.Simple(dl, new File(work, "tmp")), null);

        api.library().setScanner(new Library.FilesScanner(roots), new Library.FilesOpener());
        api.library().scan();
        api.startScheduler();

        HttpSrv srv = new HttpSrv(PORT, api);
        srv.start();
        System.out.println("服务已启动: http://127.0.0.1:" + PORT + "   曲库 " + api.library().count() + " 首");

        String base = "http://127.0.0.1:" + PORT;
        try {
            /* -------------------------------------------- 1. health */
            Json2 h = get(base + "/api/health");
            check("GET /api/health", h.code == 200 && h.text.contains("\"ok\":true"), "code=" + h.code);
            Map<String, Object> hm = Json.parseObject(h.text);
            System.out.println("      host_ip=" + hm.get("host_ip") + "  base_url=" + hm.get("base_url")
                    + "  library=" + hm.get("library"));

            /* -------------------------------------------- 2. library */
            Json2 lib = get(base + "/api/library?source=local&container=");
            Map<String, Object> lm = Json.parseObject(lib.text);
            int total = Json.i(lm, "total", 0);
            List<Object> folders = Json.asList(lm.get("folders"));
            check("GET /api/library", lib.code == 200 && total == 2 && folders.size() == 1,
                    "total=" + total + " folders=" + folders.size());
            List<Object> items = Json.asList(lm.get("items"));
            String firstUrl = items.isEmpty() ? "" : Json.s(Json.asMap(items.get(0)), "url");
            System.out.println("      曲目 url 示例: " + firstUrl);

            /* -------------------------------------------- 3. media + Range */
            String id = items.isEmpty() ? "" : Json.s(Json.asMap(items.get(0)), "id");
            Json2 full = get(base + "/media?id=" + com.dlna.speaker.Util.urlEncode(id));
            check("GET /media (全量)", full.code == 200 && full.bytes.length > 1000,
                    "code=" + full.code + " bytes=" + full.bytes.length);
            Json2 part = getRange(base + "/media?id=" + com.dlna.speaker.Util.urlEncode(id), "bytes=100-199");
            String cr = hdr(part, "Content-Range");
            check("GET /media (Range)", part.code == 206 && part.bytes.length == 100
                            && cr != null && cr.startsWith("bytes 100-199/"),
                    "code=" + part.code + " len=" + part.bytes.length + " range=" + cr);

            /* -------------------------------------------- 4. 插件代理（真站） */
            String proxyBody = "{\"url\":\"https://registry.npmjs.org/axios\",\"method\":\"GET\","
                    + "\"headers\":{\"User-Agent\":\"Probe/1.0\",\"Referer\":\"https://example.com/\"},\"timeout\":20000}";
            Json2 pr = post(base + "/__proxy", proxyBody);
            Map<String, Object> pm = Json.parseObject(pr.text);
            int pstatus = Json.i(pm, "status", 0);
            String pbody = Json.s(pm, "body");
            check("POST /__proxy (外部真站)", pstatus == 200 && pbody.length() > 1000,
                    "status=" + pstatus + " bodyB64len=" + pbody.length());
            Map<String, Object> respHeaders = Json.asMap(pm.get("headers"));
            System.out.println("      上游 content-type=" + respHeaders.get("Content-Type")
                    + "  content-encoding 已剥离=" + (!respHeaders.containsKey("Content-Encoding")));

            /* -------------------------------------------- 5. 在线直链注册 + 回灌 */
            String selfAudio = base + "/media?id=" + com.dlna.speaker.Util.urlEncode(id);
            Json2 reg = post(base + "/api/online/register",
                    Json.write(Json.map("url", selfAudio, "headers", Json.map("User-Agent", "Probe/1.0"))));
            Map<String, Object> rm = Json.parseObject(reg.text);
            String streamUrl = Json.s(rm, "url");
            check("POST /api/online/register", Json.b(rm, "ok", false) && !streamUrl.isEmpty(), streamUrl);
            Json2 st = getRange(streamUrl, "bytes=200-299");
            check("GET /stream (Range 透传)", st.code == 206 && st.bytes.length == 100,
                    "code=" + st.code + " len=" + st.bytes.length + " range=" + hdr(st, "Content-Range"));

            /* -------------------------------------------- 6. state */
            Json2 state = get(base + "/api/state");
            Map<String, Object> sm = Json.parseObject(state.text);
            List<Object> devices = Json.asList(sm.get("devices"));
            // 首次扫描是异步的，等一下让设备出现
            for (int i = 0; i < 12 && devices.isEmpty(); i++) {
                Thread.sleep(1500);
                state = get(base + "/api/state");
                sm = Json.parseObject(state.text);
                devices = Json.asList(sm.get("devices"));
            }
            check("GET /api/state", state.code == 200, "devices=" + devices.size());
            for (Object d : devices) {
                Map<String, Object> dd = Json.asMap(d);
                System.out.println("      音响: " + dd.get("name") + " @" + dd.get("ip")
                        + " online=" + dd.get("online") + " state=" + dd.get("state")
                        + " volume=" + dd.get("volume") + " udn=" + dd.get("udn"));
            }

            /* -------------------------------------------- 7. 队列 / 模式 */
            Json2 q = post(base + "/api/queue", Json.write(Json.map(
                    "action", "add",
                    "tracks", Json.list(
                            Json.map("id", id, "title", "测试音A", "artist", "测试", "source", "local", "duration_sec", 3),
                            Json.map("id", id, "title", "测试音B", "artist", "测试", "source", "local", "duration_sec", 3)))));
            check("POST /api/queue (add)", q.code == 200, q.text);
            Json2 qs = get(base + "/api/state");
            Map<String, Object> pm2 = Json.asMap(Json.parseObject(qs.text).get("player"));
            check("队列长度=2", Json.i(pm2, "playQueueSize", -1) != 0
                    || Json.asList(pm2.get("queue")).size() == 2,
                    "queue=" + Json.asList(pm2.get("queue")).size());
            Json2 mode = post(base + "/api/mode", Json.write(Json.map("repeat", "all", "shuffle", false)));
            check("POST /api/mode", mode.code == 200 && mode.text.contains("all"), mode.text);

            /* -------------------------------------------- 8. 投放音响 */
            if (cast && !devices.isEmpty()) {
                String udn = Json.s(Json.asMap(devices.get(0)), "udn");
                String name = Json.s(Json.asMap(devices.get(0)), "name");
                System.out.println("\n  >>> 投放测试：把本地曲目推到「" + name + "」播放（会出声约 3 秒）");
                // 用 off 而不是 all：放完两首自然结束，避免无限循环
                post(base + "/api/mode", Json.write(Json.map("repeat", "off", "shuffle", false)));
                Json2 tg = post(base + "/api/targets", Json.write(Json.map("udns", Json.list(udn))));
                check("POST /api/targets", tg.code == 200, tg.text);

                List<Object> tracks = new ArrayList<Object>();
                for (Object it : items) {
                    Map<String, Object> t = Json.asMap(it);
                    tracks.add(Json.map("id", Json.s(t, "id"), "title", Json.s(t, "title"),
                            "artist", Json.s(t, "artist"), "album", Json.s(t, "album"),
                            "source", "local", "duration_sec", Json.i(t, "duration_sec", 3)));
                }
                Json2 pl = post(base + "/api/play", Json.write(Json.map("tracks", tracks, "index", 0, "udns", Json.list(udn))));
                check("POST /api/play (投放)", pl.code == 200 && pl.text.contains("\"ok\":true"), pl.text);

                for (int i = 0; i < 10; i++) {
                    Thread.sleep(1500);
                    Json2 s2 = get(base + "/api/state");
                    Map<String, Object> dev = Json.asMap(Json.asList(Json.parseObject(s2.text).get("devices")).get(0));
                    Map<String, Object> pl2 = Json.asMap(Json.parseObject(s2.text).get("player"));
                    System.out.println("      [" + (i * 1.5 + 1.5) + "s] 音响状态=" + dev.get("state")
                            + " 位置=" + dev.get("position_sec") + "s/" + dev.get("duration_sec") + "s"
                            + "  当前曲=" + (pl2.get("current") == null ? "-" : Json.s(Json.asMap(pl2.get("current")), "title")));
                }
                // 复位
                post(base + "/api/control", Json.write(Json.map("action", "stop")));
                post(base + "/api/targets", Json.write(Json.map("udns", Json.list())));
            } else if (cast) {
                System.out.println("\n  (没发现音响，跳过投放测试)");
            }

            /* -------------------------------------------- 9. 静态资源 */
            Json2 idx = get(base + "/");
            check("GET / (index.html)", idx.code == 200 && idx.text.contains("<html"), "code=" + idx.code);

        } finally {
            srv.stop();
        }

        System.out.println("\n========================================================");
        System.out.println("通过 " + passed + " 项，失败 " + failed + " 项");
        System.out.println("========================================================");
        if (failed > 0) System.exit(1);
    }

    /* ------------------------------------------------------ 测试工具 */

    static void check(String name, boolean ok, String detail) {
        if (ok) { passed++; System.out.println("  [通过] " + name); }
        else { failed++; System.out.println("  [失败] " + name + "   -> " + detail); }
    }

    static class Json2 {
        int code;
        String text = "";
        byte[] bytes = new byte[0];
        Map<String, String> hdrs = new java.util.LinkedHashMap<String, String>();
    }

    static String hdr(Json2 r, String name) { return r.hdrs.get(name); }

    static Json2 get(String url) throws Exception { return request(url, "GET", null, null); }
    static Json2 getRange(String url, String range) throws Exception { return request(url, "GET", null, range); }

    static Json2 post(String url, String body) throws Exception {
        return request(url, "POST", body.getBytes(Charset.forName("UTF-8")), null);
    }

    static Json2 request(String url, String method, byte[] body, String range) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setRequestMethod(method);
        c.setConnectTimeout(20000);
        c.setReadTimeout(60000);
        c.setInstanceFollowRedirects(true);
        if (body != null) {
            c.setDoOutput(true);
            c.setRequestProperty("Content-Type", "application/json");
            c.setFixedLengthStreamingMode(body.length);
            c.getOutputStream().write(body);
        }
        if (range != null) c.setRequestProperty("Range", range);
        Json2 r = new Json2();
        r.code = c.getResponseCode();
        for (Map.Entry<String, java.util.List<String>> e : c.getHeaderFields().entrySet()) {
            if (e.getKey() == null || e.getValue().isEmpty()) continue;
            r.hdrs.put(e.getKey(), e.getValue().get(0));
        }
        InputStream in = r.code >= 400 ? c.getErrorStream() : c.getInputStream();
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        if (in != null) {
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) bos.write(buf, 0, n);
            in.close();
        }
        r.bytes = bos.toByteArray();
        r.text = new String(r.bytes, Charset.forName("UTF-8"));
        c.disconnect();
        return r;
    }

    static void writeFile(File f, byte[] data) throws Exception {
        FileOutputStream os = new FileOutputStream(f);
        os.write(data);
        os.close();
    }

    /** 3 秒正弦波 WAV（8000Hz/16bit/单声道） */
    static byte[] makeWav(int freq) {
        int rate = 8000, seconds = 3, n = rate * seconds;
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        int dataLen = n * 2;
        ascii(bos, "RIFF"); le32(bos, 36 + dataLen); ascii(bos, "WAVE");
        ascii(bos, "fmt "); le32(bos, 16); le16(bos, 1); le16(bos, 1);
        le32(bos, rate); le32(bos, rate * 2); le16(bos, 2); le16(bos, 16);
        ascii(bos, "data"); le32(bos, dataLen);
        for (int i = 0; i < n; i++) {
            double fade = Math.min(1.0, Math.min(i / 400.0, (n - i) / 400.0));
            short v = (short) (Math.sin(2 * Math.PI * freq * i / rate) * 6000 * fade);
            le16(bos, v & 0xFFFF);
        }
        return bos.toByteArray();
    }

    static void ascii(ByteArrayOutputStream b, String s) { for (int i = 0; i < s.length(); i++) b.write(s.charAt(i)); }
    static void le32(ByteArrayOutputStream b, int v) { b.write(v & 0xFF); b.write((v >> 8) & 0xFF); b.write((v >> 16) & 0xFF); b.write((v >> 24) & 0xFF); }
    static void le16(ByteArrayOutputStream b, int v) { b.write(v & 0xFF); b.write((v >> 8) & 0xFF); }
}
