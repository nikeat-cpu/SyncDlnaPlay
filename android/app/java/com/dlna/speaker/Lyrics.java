package com.dlna.speaker;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.util.Map;

/**
 * 本地歌词
 * ========
 * 找同目录同名的 .lrc（也支持放在 lyrics/ 子目录里）。
 * 支持本机下载目录、媒体库曲目、SAF 目录与 SMB 共享。
 *
 * 在线曲目的歌词不走这里 —— 那由 WebView 里的插件运行时直接向音源要。
 */
public final class Lyrics {

    private static final int MAX_LRC = 512 * 1024;

    public static String find(Api api, String id) {
        if (api == null || id == null || id.isEmpty()) return "";
        try {
            if (id.startsWith("f:")) return readPath(id.substring(2));
            if (id.startsWith("m:")) {
                Map<String, Object> t = api.trackById(id);
                String p = t == null ? "" : Json.s(t, "path");
                return p.isEmpty() ? "" : readPath(p);
            }
            if (MusicDirs.isUserTrack(id)) {
                MusicDirs dirs = api.musicDirsRef();
                if (dirs != null) return dirs.readSiblingText(id, "lrc");
            }
        } catch (Throwable ignore) { }
        return "";
    }

    private static String readPath(String mediaPath) {
        try {
            File lrc = new File(brother(mediaPath, "lrc"));
            if (!lrc.isFile()) {
                File alt = new File(new File(lrc.getParentFile(), "lyrics"), lrc.getName());
                if (alt.isFile()) lrc = alt;
                else return "";
            }
            InputStream in = new FileInputStream(lrc);
            try { return readText(in); } finally { try { in.close(); } catch (Throwable ignore) { } }
        } catch (Throwable t) {
            return "";
        }
    }

    /** 把 xxx.mp3 变成 xxx.lrc */
    static String brother(String p, String ext) {
        if (p == null) return "";
        int dot = p.lastIndexOf('.');
        int slash = p.lastIndexOf('/');
        String base = dot > slash ? p.substring(0, dot) : p;
        return base + "." + ext;
    }

    static String stripExt(String n) {
        if (n == null) return "";
        int d = n.lastIndexOf('.');
        return d > 0 ? n.substring(0, d) : n;
    }

    static String readText(InputStream in) {
        try {
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n, total = 0;
            while ((n = in.read(buf)) > 0 && total < MAX_LRC) {
                bos.write(buf, 0, n);
                total += n;
            }
            return decode(bos.toByteArray());
        } catch (Throwable t) {
            return "";
        }
    }

    /** 中文歌词常是 GBK：先按 UTF-8 解，出现替换字符再退回 GBK */
    static String decode(byte[] data) {
        if (data == null || data.length == 0) return "";
        try {
            String s = new String(data, "UTF-8");
            if (s.indexOf('\uFFFD') < 0) {
                if (!s.isEmpty() && s.charAt(0) == '\uFEFF') s = s.substring(1);
                return s;
            }
            return new String(data, "GBK");
        } catch (Throwable t) {
            return new String(data);
        }
    }
}
