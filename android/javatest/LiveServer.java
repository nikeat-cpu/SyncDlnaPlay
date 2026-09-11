import com.dlna.speaker.Api;
import com.dlna.speaker.Downloader;
import com.dlna.speaker.HttpSrv;
import com.dlna.speaker.Library;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.List;

/**
 * 桌面常驻服务：把 Android 上要跑的那套 HttpSrv + Api 原样跑在 PC 的 8765 端口，
 * 供无头浏览器加载真实前端（app/assets/www）做端到端联调。
 *
 * 之所以要这个，是因为 APK 装不了真机时，唯一能验证「前端 <-> 本地服务」这条链路
 * 的办法就是让浏览器当 WebView 用。
 *
 * 用法： java -cp build/dlna LiveServer [资源根目录]
 */
public class LiveServer {

    static final int PORT = 8765;

    public static void main(String[] args) throws Exception {
        File proj = new File(".").getAbsoluteFile();
        File work = new File(proj, "build/live");
        File music = new File(work, "music/测试专辑");
        File dl = new File(work, "downloads");
        music.mkdirs();
        dl.mkdirs();

        // 造几首 3 秒测试音，让「本机曲库」有内容
        writeFile(new File(music, "01 - 测试音A.wav"), makeWav(440));
        writeFile(new File(music, "02 - 测试音B.wav"), makeWav(660));
        writeFile(new File(work, "music/单曲 - 测试音C.wav"), makeWav(880));

        final File assetsDir = new File(proj, "app/assets");

        List<File> roots = new ArrayList<File>();
        roots.add(new File(work, "music"));

        Api api = new Api(PORT, new Api.AssetLoader() {
            @Override public byte[] load(String path) {
                File f = new File(assetsDir, path);
                if (!f.isFile()) return null;
                try {
                    InputStream in = new FileInputStream(f);
                    ByteArrayOutputStream bos = new ByteArrayOutputStream();
                    byte[] buf = new byte[8192];
                    int n;
                    while ((n = in.read(buf)) > 0) bos.write(buf, 0, n);
                    in.close();
                    return bos.toByteArray();
                } catch (Exception e) { return null; }
            }
            @Override public String mimeType(String path) { return com.dlna.speaker.Util.mimeOf(path); }
            @Override public String[] list(String dir) {
                String[] a = new File(assetsDir, dir).list();
                return a == null ? new String[0] : a;
            }
        }, new com.dlna.speaker.Storage.Simple(dl, new File(work, "tmp")), null);
        api.setDataDir(new File(work, "data"));

        api.library().setScanner(new Library.FilesScanner(roots), new Library.FilesOpener());
        api.library().scan();
        api.startScheduler();

        HttpSrv srv = new HttpSrv(PORT, api);
        srv.start();

        System.out.println("READY http://127.0.0.1:" + PORT
                + "  library=" + api.library().count()
                + "  assets=" + assetsDir.getAbsolutePath());
        System.out.flush();

        // 常驻
        Object lock = new Object();
        synchronized (lock) { lock.wait(); }
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
