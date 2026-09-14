package com.dlna.speaker;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;

/**
 * 下载落盘位置的抽象
 * ==================
 * 拆成接口是为了让整套后端在桌面 JVM 上也能跑（做端到端回归），
 * Android 的实现在 {@link AndroidStorage}。
 *
 * 为什么需要它：旧版把下载目录写死在 getExternalFilesDir(DIRECTORY_MUSIC)，
 * 也就是 /sdcard/Android/data/<包名>/files/Music —— 而 Android 11+ 的文件管理器
 * 默认不展示 Android/data。文件其实下好了，但用户怎么翻都找不到，
 * 体感就是「下载不了」。
 */
public interface Storage {

    /** 落盘目标：把已下好的本地文件"搬"到最终位置 */
    interface Sink {
        /** 描述，用于界面/日志 */
        String describe();
        /** 已有同名文件则返回其字节数（未知大小返回 -1），没有返回 0 */
        long existingSize(String artist, String fileName);
        /** 搬运并返回最终大小 */
        long put(String artist, String fileName, File local, String mime, String title) throws Exception;
    }

    /** 给人看的路径描述 */
    String describe();

    /** 当前生效的落盘实现 */
    Sink sink();

    /** 本地临时文件目录（先下到这儿，校验通过再搬运） */
    File tmpDir();

    /** 公共/默认目录下使用的子目录名 */
    String subDir();

    void setSubDir(String name);

    /** 是否用的是用户自定义目录 */
    boolean isCustom();

    /** 自定义目录的展示名 */
    String customName();

    /**
     * 设置自定义目录。
     * Android 上 uri 是 SAF 的 content:// 目录树；桌面上当作普通路径。
     */
    void setCustom(String uri, String name);

    /** 恢复默认目录 */
    void clearCustom();

    /** 默认（非自定义）目录的 File 形式，用于本地扫描 */
    File defaultDir();

    /** 歌词独立存储目录（纯文件、应用私有，避免把 .lrc 写进音频库造成幽灵曲目） */
    File lyricsDir();

    /** 导出的播放列表文件目录（应用私有，落地为 .m3u） */
    File playlistDir();

    /* ================================================================== */

    /**
     * 纯文件系统的实现：桌面回归用，同时作为 Android 上的兜底。
     */
    final class Simple implements Storage {
        private final File root;
        private final File tmp;
        private volatile String custom = "";

        public Simple(File root, File tmp) {
            this.root = root;
            this.tmp = tmp;
            if (!tmp.exists()) tmp.mkdirs();
            if (!root.exists()) root.mkdirs();
        }

        @Override public String describe() {
            return isCustom() ? ("自定义目录：" + custom) : root.getAbsolutePath() + "/";
        }

        @Override public Sink sink() {
            final File base = isCustom() ? new File(custom) : root;
            return new Sink() {
                @Override public String describe() { return base.getAbsolutePath(); }

                @Override public long existingSize(String artist, String fileName) {
                    File f = new File(new File(base, artist), fileName);
                    if (!f.isFile()) return 0;
                    return f.length() > 0 ? f.length() : -1;
                }

                @Override public long put(String artist, String fileName, File local, String mime, String title) throws Exception {
                    File dir = new File(base, artist);
                    if (!dir.exists() && !dir.mkdirs() && !dir.isDirectory()) throw new Exception("无法创建目录: " + dir);
                    File dst = new File(dir, fileName);
                    InputStream in = new FileInputStream(local);
                    OutputStream out = new FileOutputStream(dst);
                    try {
                        byte[] buf = new byte[65536];
                        int n;
                        while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
                        out.flush();
                    } finally {
                        try { in.close(); } catch (Throwable ignore) { }
                        try { out.close(); } catch (Throwable ignore) { }
                    }
                    return dst.length();
                }
            };
        }

        @Override public File tmpDir() { return tmp; }
        @Override public String subDir() { return ""; }
        @Override public void setSubDir(String name) { }
        @Override public boolean isCustom() { return !custom.isEmpty(); }
        @Override public String customName() { return custom; }
        @Override public void setCustom(String uri, String name) { this.custom = uri == null ? "" : uri; }
        @Override public void clearCustom() { this.custom = ""; }
        @Override public File defaultDir() { return root; }

    @Override public File lyricsDir() { return new File(root, "lyrics"); }
    @Override public File playlistDir() { return new File(root, "playlists"); }
    }
}
