import com.dlna.speaker.Smb;

import java.io.InputStream;
import java.util.List;
import java.util.Map;

/**
 * SMB 客户端的桌面验证
 * ====================
 * jcifs-ng 是纯 Java 实现，所以可以在 PC 上直接连 iStoreOS 的 Samba 共享，
 * 把「探测 -> 扫描 -> 读流」整条链路先跑通，再到手机上看表现。
 *
 * 用法: java SmbProbe [host] [share]
 */
public class SmbProbe {

    public static void main(String[] args) throws Exception {
        String host = args.length > 0 ? args[0] : "192.168.1.10";
        String share = args.length > 1 ? args[1] : "Tiny";
        Smb.Conn c = new Smb.Conn(host, share, "", "", "", true);

        System.out.println("=== 1. 探测共享 " + c.baseUrl() + " ===");
        Map<String, Object> p = Smb.probe(c);
        System.out.println("  " + p);
        boolean ok = Boolean.TRUE.equals(p.get("ok"));
        System.out.println("  " + (ok ? "[通过] 能连上共享" : "[失败] 连不上"));

        System.out.println("\n=== 2. 扫描音频（上限 40 个 / 深度 3 / 20 秒）===");
        long t0 = System.currentTimeMillis();
        List<Map<String, Object>> files = Smb.scan(c, 40, 3, 20000);
        long ms = System.currentTimeMillis() - t0;
        System.out.println("  耗时 " + ms + " ms，找到 " + files.size() + " 个音频");
        for (int i = 0; i < Math.min(10, files.size()); i++) {
            Map<String, Object> f = files.get(i);
            System.out.println("    " + f.get("rel") + "  (" + f.get("size") + " bytes)");
        }

        if (!files.isEmpty()) {
            String rel = String.valueOf(files.get(0).get("rel"));
            String url = Smb.url(c, rel);
            System.out.println("\n=== 3. 读流测试：" + rel + " ===");
            InputStream in = Smb.open(url, c);
            byte[] head = new byte[16];
            int n = in.read(head);
            in.close();
            System.out.println("  读到 " + n + " 字节，头部: " + toHex(head, n));
            System.out.println("  文件大小: " + Smb.size(url, c) + " bytes");
            System.out.println("  " + (n > 0 ? "[通过] 能真的读出数据" : "[失败] 读不到"));
        } else {
            System.out.println("\n  [跳过] 共享里没有音频，读流测试略过");
        }

        System.out.println("\n=== 4. 错误路径（不存在的共享，不能崩）===");
        Smb.Conn bad = new Smb.Conn(host, "no_such_share_xyz", "", "", "", true);
        Map<String, Object> bp = Smb.probe(bad);
        System.out.println("  " + bp);
        System.out.println("  " + (Boolean.TRUE.equals(bp.get("ok")) ? "[失败] 不该成功" : "[通过] 优雅报错，没抛异常"));
    }

    private static String toHex(byte[] b, int n) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < n; i++) sb.append(String.format("%02X ", b[i]));
        return sb.toString().trim();
    }
}
