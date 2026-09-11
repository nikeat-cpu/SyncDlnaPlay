import com.dlna.speaker.Dlna;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpServer;

import java.io.ByteArrayOutputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.util.List;
import java.util.Map;

/**
 * Dlna.java 桌面验证程序（PC 上跑，用于对着真实音响验证移植是否成功）
 * =====================================================================
 * 默认只做「只读」检查：SSDP 发现、取设备描述、GetTransportInfo / GetVolume /
 * GetPositionInfo —— 完全不影响音响当前的播放。
 * <p>
 * 加 `--load` 参数会额外做一次「写入」检查：起一个本地 HTTP 服务把生成的测试音
 * 推给音响做 SetAVTransportURI（只装载、不播放，随后立刻 Stop 复位），
 * 用来验证 SOAP 信封与 DIDL-Lite 元数据是否真被设备接受。
 */
public class DlnaProbe {

    static final int HTTP_PORT = 8788;

    public static void main(String[] args) throws Exception {
        boolean doLoad = false;
        for (String a : args) if ("--load".equals(a)) doLoad = true;

        System.out.println("========================================================");
        System.out.println("DLNA Java 移植验证");
        System.out.println("========================================================");
        List<String> ips = Dlna.localIps();
        System.out.println("可用网卡 IP : " + ips);
        System.out.println("MIME 推断   : " + String.join("/", Dlna.guessMime("http://x/a.flac")));

        /* ---------------------------------------------- 发现渲染器 */
        long t0 = System.currentTimeMillis();
        List<Dlna.DeviceInfo> all = Dlna.discover(3, 8);
        System.out.println("\nSSDP 发现到 " + all.size() + " 台设备（耗时 "
                + (System.currentTimeMillis() - t0) + " ms）");
        for (Dlna.DeviceInfo d : all) {
            System.out.println("  - " + d.name() + "  @" + d.ip
                    + "  [" + shortType(d.deviceType) + "]"
                    + "  model=" + d.modelName
                    + "  udn=" + d.udn);
            System.out.println("      服务: " + d.services.keySet());
        }

        /* ---------------------------------------------- 渲染器只读检查 */
        Dlna.Renderer target = null;
        for (Dlna.DeviceInfo d : all) {
            if (d.isRenderer()) { target = new Dlna.Renderer(d); break; }
        }
        if (target == null) {
            System.out.println("\n没发现可用的 MediaRenderer（音响），后续检查跳过。");
        } else {
            System.out.println("\n---- 渲染器检查: " + target.name + " @" + target.ip + " ----");
            System.out.println("  richMetadata = " + target.richMetadata);
            Map<String, Object> st = target.status();
            System.out.println("  online      = " + st.get("online"));
            System.out.println("  state       = " + st.get("state"));
            System.out.println("  volume      = " + st.get("volume"));
            System.out.println("  title       = " + st.get("title"));
            System.out.println("  position    = " + st.get("position") + " (" + st.get("position_sec") + "s)");
            System.out.println("  duration    = " + st.get("duration") + " (" + st.get("duration_sec") + "s)");

            if (doLoad) {
                System.out.println("\n---- 写入检查: SetAVTransportURI（只装载，不播放） ----");
                String myIp = sameSubnetIp(target.ip, ips);
                String url = "http://" + myIp + ":" + HTTP_PORT + "/tone.wav";
                HttpServer srv = startToneServer();
                System.out.println("  本机服务 : " + url);
                try {
                    Dlna.SoapResult r = target.setUri(url, "移植验证测试音", "0:00:03", "Test", "", null, null, 8);
                    System.out.println("  SetAVTransportURI -> " + r);
                    Thread.sleep(400);
                    Dlna.SoapResult mi = target.getMediaInfo();
                    System.out.println("  GetMediaInfo      -> " + mi);
                    Dlna.SoapResult pi = target.getPositionInfo();
                    System.out.println("  GetPositionInfo   -> " + pi);
                    Dlna.SoapResult stop = target.stop();
                    System.out.println("  Stop(复位)        -> " + stop);
                } finally {
                    srv.stop(0);
                }
            }
        }

        /* ---------------------------------------------- 媒体服务器 */
        System.out.println("\n---- MediaServer 检查 ----");
        int serverCount = 0;
        for (Dlna.DeviceInfo d : all) {
            if (!d.isServer()) continue;
            serverCount++;
            Dlna.MediaServer ms = new Dlna.MediaServer(d);
            System.out.println("  " + ms.name + " @" + ms.ip);
            Dlna.BrowseResult br = ms.browse("0", 0, 10, "");
            if (!br.ok) { System.out.println("    浏览失败: " + br.error); continue; }
            System.out.println("    根目录 " + br.total + " 项，前 " + Math.min(5, br.items.size()) + " 项：");
            for (int i = 0; i < Math.min(5, br.items.size()); i++) {
                Map<String, Object> it = br.items.get(i);
                System.out.println("      [" + it.get("type") + "] " + it.get("title"));
            }
        }
        if (serverCount == 0) System.out.println("  （未发现 MediaServer）");

        System.out.println("\n验证结束。");
    }

    /** urn:schemas-upnp-org:device:MediaRenderer:1 -> MediaRenderer */
    static String shortType(String t) {
        if (t == null) return "";
        String[] p = t.split(":");
        return p.length >= 2 ? p[p.length - 2] : t;
    }

    /** 找出与目标设备同 /24 网段的本机 IP */
    static String sameSubnetIp(String deviceIp, List<String> ips) {
        String prefix = deviceIp.substring(0, deviceIp.lastIndexOf('.') + 1);
        for (String ip : ips) if (ip.startsWith(prefix)) return ip;
        return ips.isEmpty() ? "0.0.0.0" : ips.get(0);
    }

    /** 起一个最小 HTTP 服务，提供一段 3 秒 440Hz 测试音（WAV），支持 Range */
    static HttpServer startToneServer() throws Exception {
        final byte[] wav = makeWav();
        HttpServer srv = HttpServer.create(new InetSocketAddress(HTTP_PORT), 0);
        srv.createContext("/tone.wav", new HttpHandler() {
            @Override public void handle(HttpExchange ex) throws java.io.IOException {
                try {
                    long total = wav.length;
                    String range = ex.getRequestHeaders().getFirst("Range");
                    long start = 0, end = total - 1;
                    boolean partial = false;
                    if (range != null && range.startsWith("bytes=")) {
                        String spec = range.substring(6).split(",")[0];
                        String[] se = spec.split("-");
                        try {
                            if (!se[0].isEmpty()) start = Long.parseLong(se[0]);
                            if (se.length > 1 && !se[1].isEmpty()) end = Long.parseLong(se[1]);
                            if (end >= total) end = total - 1;
                            partial = true;
                        } catch (Exception ignore) { partial = false; start = 0; end = total - 1; }
                    }
                    long len = end - start + 1;
                    ex.getResponseHeaders().set("Content-Type", "audio/wav");
                    ex.getResponseHeaders().set("Accept-Ranges", "bytes");
                    ex.getResponseHeaders().set("Connection", "close");
                    if (partial) {
                        ex.getResponseHeaders().set("Content-Range",
                                "bytes " + start + "-" + end + "/" + total);
                        ex.sendResponseHeaders(206, len);
                    } else {
                        ex.sendResponseHeaders(200, len);
                    }
                    OutputStream os = ex.getResponseBody();
                    os.write(wav, (int) start, (int) len);
                    os.flush();
                    os.close();
                } catch (Exception e) {
                    try { ex.close(); } catch (Exception ignore) { }
                }
            }
        });
        srv.setExecutor(null);
        srv.start();
        return srv;
    }

    /** 生成 3 秒 440Hz 正弦波 WAV（8000Hz / 16bit / 单声道），音量较低避免刺耳 */
    static byte[] makeWav() {
        int rate = 8000, seconds = 3, n = rate * seconds;
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        int dataLen = n * 2;
        writeAscii(bos, "RIFF");
        writeLE32(bos, 36 + dataLen);
        writeAscii(bos, "WAVE");
        writeAscii(bos, "fmt ");
        writeLE32(bos, 16);
        writeLE16(bos, 1);      // PCM
        writeLE16(bos, 1);      // 单声道
        writeLE32(bos, rate);
        writeLE32(bos, rate * 2);
        writeLE16(bos, 2);
        writeLE16(bos, 16);
        writeAscii(bos, "data");
        writeLE32(bos, dataLen);
        for (int i = 0; i < n; i++) {
            double fade = Math.min(1.0, Math.min(i / 400.0, (n - i) / 400.0));
            short v = (short) (Math.sin(2 * Math.PI * 440 * i / rate) * 6000 * fade);
            writeLE16(bos, v & 0xFFFF);
        }
        return bos.toByteArray();
    }

    static void writeAscii(ByteArrayOutputStream b, String s) {
        for (int i = 0; i < s.length(); i++) b.write(s.charAt(i));
    }
    static void writeLE32(ByteArrayOutputStream b, int v) {
        b.write(v & 0xFF); b.write((v >> 8) & 0xFF); b.write((v >> 16) & 0xFF); b.write((v >> 24) & 0xFF);
    }
    static void writeLE16(ByteArrayOutputStream b, int v) {
        b.write(v & 0xFF); b.write((v >> 8) & 0xFF);
    }
}
