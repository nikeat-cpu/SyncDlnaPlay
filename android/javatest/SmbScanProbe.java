import com.dlna.speaker.Json;
import com.dlna.speaker.Smb;

import java.util.List;
import java.util.Map;

/**
 * 桌面验证 SMB 的「扫描局域网」与「浏览共享」两条新链路。
 * 直接打用户家里的真实 Samba（iStoreOS 192.168.1.10），不是假数据。
 *
 * 用法： java -cp "build/classes;build/probe;libs/*" SmbScanProbe [host] [share] [user] [pass]
 */
public class SmbScanProbe {

    public static void main(String[] args) {
        String host = args.length > 0 ? args[0] : "192.168.1.10";
        String share = args.length > 1 ? args[1] : "Tiny";
        String user = args.length > 2 ? args[2] : "";
        String pass = args.length > 3 ? args[3] : "";

        System.out.println("== 1) 本机网段 ==");
        List<String> pfx = Smb.localPrefixes();
        System.out.println("   " + pfx + (pfx.isEmpty() ? "  （无网段，扫描会直接报错而不是卡死）" : ""));

        System.out.println("== 2) 扫描局域网（最多 12 秒）==");
        long t0 = System.currentTimeMillis();
        Map<String, Object> d = Smb.discover(user, pass, true, 12000);
        System.out.println("   耗时 " + (System.currentTimeMillis() - t0) + " ms");
        System.out.println("   ok=" + d.get("ok") + "  error=" + d.get("error"));
        for (Object o : Json.asList(d.get("hosts"))) {
            Map<String, Object> h = Json.asMap(o);
            StringBuilder names = new StringBuilder();
            for (Object s : Json.asList(h.get("shares"))) {
                names.append(Json.s(Json.asMap(s), "name")).append(" ");
            }
            System.out.println("   · " + Json.s(h, "host") + "  " + Json.s(h, "name")
                    + "  共享: [" + names.toString().trim() + "]"
                    + (Json.s(h, "error").isEmpty() ? "" : "  (" + Json.s(h, "error") + ")"));
        }

        System.out.println("== 3) 枚举 " + host + " 上的共享 ==");
        Map<String, Object> sh = Smb.shares(host, user, pass, true);
        System.out.println("   ok=" + sh.get("ok") + "  error=" + sh.get("error"));
        for (Object o : Json.asList(sh.get("shares"))) {
            System.out.println("   · " + Json.s(Json.asMap(o), "name"));
        }

        System.out.println("== 4) 浏览 " + host + "/" + share + " 的根目录 ==");
        Map<String, Object> b = Smb.browseDir(new Smb.Conn(host, share, "", user, pass, true), "");
        System.out.println("   ok=" + b.get("ok") + "  error=" + b.get("error")
                + "  音乐=" + b.get("audio_files") + " 其它=" + b.get("files"));
        List<Object> dirs = Json.asList(b.get("dirs"));
        for (int i = 0; i < Math.min(dirs.size(), 8); i++) {
            System.out.println("   · " + Json.s(Json.asMap(dirs.get(i)), "name")
                    + "   rel=" + Json.s(Json.asMap(dirs.get(i)), "rel"));
        }

        System.out.println("== 5) 往下钻一层 ==");
        if (!dirs.isEmpty()) {
            String rel = Json.s(Json.asMap(dirs.get(0)), "rel");
            Map<String, Object> b2 = Smb.browseDir(new Smb.Conn(host, share, "", user, pass, true), rel);
            System.out.println("   进入 " + rel + " -> ok=" + b2.get("ok")
                    + "  music=" + b2.get("audio_files")
                    + "  子目录=" + Json.asList(b2.get("dirs")).size()
                    + "  上一级=" + b2.get("parent"));
        }

        System.out.println("== 6) 错误路径：不存在的共享要优雅报错 ==");
        Map<String, Object> bad = Smb.browseDir(
                new Smb.Conn(host, "no-such-share-xyz", "", user, pass, true), "");
        System.out.println("   ok=" + bad.get("ok") + "  error=" + bad.get("error"));
        System.out.println("   （ok 必须是 false，且 error 是可读中文，不能抛异常）");
    }
}
