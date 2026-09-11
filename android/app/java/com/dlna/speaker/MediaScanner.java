package com.dlna.speaker;

import android.content.ContentResolver;
import android.content.ContentUris;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;

import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 基于 MediaStore 的曲库扫描与读取
 * ================================
 * 为什么不直接遍历文件系统：Android 10 起的分区存储（Scoped Storage）让
 * 「直接读 /storage/emulated/0/Music」在很多机型上拿不到文件，而 MediaStore
 * 是官方通道，只要拿到 READ_MEDIA_AUDIO（Android 13+）或
 * READ_EXTERNAL_STORAGE（Android 12 及以下）就能完整列出系统音频库。
 *
 * 同时会把 App 自己的下载目录也扫进来（那是应用专属目录，任何权限都能读），
 * 这样「下载到本机」的歌马上就能在曲库里看到。
 *
 * 另外还会合并「用户添加的音乐目录」——SAF 选的文件夹、SMB 网络共享，
 * 见 {@link MusicDirs}。
 */
public class MediaScanner implements Library.Scanner {

    private final Context ctx;
    private final MusicDirs dirs;

    public MediaScanner(Context ctx) {
        this(ctx, new MusicDirs(ctx));
    }

    public MediaScanner(Context ctx, MusicDirs dirs) {
        this.ctx = ctx;
        this.dirs = dirs;
    }

    @Override
    public List<Map<String, Object>> scan() {
        List<Map<String, Object>> out = new ArrayList<Map<String, Object>>();
        Set<String> seenPaths = new HashSet<String>();
        scanMediaStore(out, seenPaths);
        scanAppDownloads(out, seenPaths);
        scanUserDirs(out);
        return out;
    }

    /** 合并用户自己添加的目录（SAF / SMB）。网络共享可能很慢，给一个总时限。 */
    private void scanUserDirs(List<Map<String, Object>> out) {
        if (dirs == null) return;
        List<Map<String, Object>> extra;
        try {
            extra = dirs.scan(Math.max(0, Library.MAX_FILES - out.size()), 45000);
        } catch (Throwable t) {
            return;   // 网络共享掉线等，不能影响其它来源
        }
        for (Map<String, Object> t : extra) {
            if (out.size() >= Library.MAX_FILES) return;
            out.add(t);
        }
    }

    /* ---------------------------------------------------- MediaStore */

    private void scanMediaStore(List<Map<String, Object>> out, Set<String> seenPaths) {
        boolean hasRelative = Build.VERSION.SDK_INT >= 29;
        List<String> cols = new ArrayList<String>();
        cols.add(MediaStore.Audio.Media._ID);
        cols.add(MediaStore.Audio.Media.TITLE);
        cols.add(MediaStore.Audio.Media.ARTIST);
        cols.add(MediaStore.Audio.Media.ALBUM);
        cols.add(MediaStore.Audio.Media.DURATION);
        cols.add(MediaStore.Audio.Media.DISPLAY_NAME);
        cols.add(MediaStore.Audio.Media.DATA);
        cols.add(MediaStore.Audio.Media.TRACK);
        if (hasRelative) cols.add(MediaStore.Audio.Media.RELATIVE_PATH);

        Cursor c = null;
        try {
            c = ctx.getContentResolver().query(
                    MediaStore.Audio.Media.EXTERNAL_CONTENT_URI,
                    cols.toArray(new String[0]),
                    null, null,
                    MediaStore.Audio.Media.TITLE + " ASC");
            if (c == null) return;
            int idxId = c.getColumnIndex(MediaStore.Audio.Media._ID);
            int idxTitle = c.getColumnIndex(MediaStore.Audio.Media.TITLE);
            int idxArtist = c.getColumnIndex(MediaStore.Audio.Media.ARTIST);
            int idxAlbum = c.getColumnIndex(MediaStore.Audio.Media.ALBUM);
            int idxDur = c.getColumnIndex(MediaStore.Audio.Media.DURATION);
            int idxName = c.getColumnIndex(MediaStore.Audio.Media.DISPLAY_NAME);
            int idxData = c.getColumnIndex(MediaStore.Audio.Media.DATA);
            int idxTrack = c.getColumnIndex(MediaStore.Audio.Media.TRACK);
            int idxRel = hasRelative ? c.getColumnIndex(MediaStore.Audio.Media.RELATIVE_PATH) : -1;

            while (c.moveToNext() && out.size() < Library.MAX_FILES) {
                long id = idxId >= 0 ? c.getLong(idxId) : 0;
                String display = idxName >= 0 ? safe(c.getString(idxName)) : "";
                String data = idxData >= 0 ? safe(c.getString(idxData)) : "";
                if (!data.isEmpty()) seenPaths.add(data);

                String folder;
                if (idxRel >= 0) {
                    folder = safe(c.getString(idxRel));
                    while (folder.endsWith("/")) folder = folder.substring(0, folder.length() - 1);
                } else {
                    folder = parentOf(data);
                }

                Map<String, Object> m = Json.map();
                m.put("id", "m:" + id);
                String title = idxTitle >= 0 ? safe(c.getString(idxTitle)) : "";
                m.put("title", title.isEmpty() ? stripExt(display) : title);
                m.put("artist", idxArtist >= 0 ? nullSafe(c.getString(idxArtist)) : "");
                m.put("album", idxAlbum >= 0 ? nullSafe(c.getString(idxAlbum)) : "");
                m.put("folder", folder);
                m.put("path", data.isEmpty() ? display : data);
                m.put("duration_sec", idxDur >= 0 ? (int) (c.getLong(idxDur) / 1000) : 0);
                m.put("track_no", idxTrack >= 0 ? narrow(c.getInt(idxTrack)) : 0);
                m.put("source", "local");
                m.put("size", -1);
                out.add(m);
            }
        } catch (Throwable t) {
            // 权限不足或厂商 ROM 差异：忽略，交给应用下载目录兜底
        } finally {
            if (c != null) try { c.close(); } catch (Exception ignore) { }
        }
    }

    /* ------------------------------------------- App 自己的下载目录 */

    private void scanAppDownloads(List<Map<String, Object>> out, Set<String> seenPaths) {
        File base = ctx.getExternalFilesDir(Environment.DIRECTORY_MUSIC);
        if (base == null) base = new File(ctx.getFilesDir(), "Music");
        if (!base.isDirectory()) return;
        List<File> roots = new ArrayList<File>();
        roots.add(base);
        List<Map<String, Object>> extra = new Library.FilesScanner(roots).scan();
        for (Map<String, Object> t : extra) {
            if (out.size() >= Library.MAX_FILES) break;
            String p = Json.s(t, "path");
            if (!p.isEmpty() && seenPaths.contains(p)) continue;
            t.put("id", "f:" + p);
            t.put("src_id", "device");
            if (Json.s(t, "folder").isEmpty()) t.put("folder", "下载");
            out.add(t);
            seenPaths.add(p);
        }
    }

    /* --------------------------------------------------------- 读取 */

    /** 把曲目 id 变成可读流（MediaStore 走 ContentResolver，下载目录走文件） */
    public static class Opener implements Library.Opener {
        private final Context ctx;
        private final MusicDirs dirs;

        public Opener(Context ctx) {
            this(ctx, new MusicDirs(ctx));
        }

        public Opener(Context ctx, MusicDirs dirs) {
            this.ctx = ctx;
            this.dirs = dirs;
        }

        @Override public InputStream open(String id) throws Exception {
            if (id == null) throw new Exception("bad id");
            if (id.startsWith("m:")) {
                long raw = Long.parseLong(id.substring(2));
                Uri uri = ContentUris.withAppendedId(MediaStore.Audio.Media.EXTERNAL_CONTENT_URI, raw);
                InputStream in = ctx.getContentResolver().openInputStream(uri);
                if (in == null) throw new Exception("无法打开媒体: " + id);
                return in;
            }
            String path = id.startsWith("f:") ? id.substring(2) : id;
            return new FileInputStream(path);
        }

        @Override public long size(String id) {
            if (id == null) return -1;
            if (MusicDirs.isUserTrack(id)) return dirs.size(id);
            if (id.startsWith("m:")) {
                long raw;
                try { raw = Long.parseLong(id.substring(2)); } catch (Exception e) { return -1; }
                Uri uri = ContentUris.withAppendedId(MediaStore.Audio.Media.EXTERNAL_CONTENT_URI, raw);
                Cursor c = null;
                try {
                    ContentResolver cr = ctx.getContentResolver();
                    c = cr.query(uri, new String[]{MediaStore.Audio.Media.SIZE}, null, null, null);
                    if (c != null && c.moveToFirst()) return c.getLong(0);
                } catch (Throwable ignore) {
                } finally {
                    if (c != null) try { c.close(); } catch (Exception ignore) { }
                }
                return -1;
            }
            String path = id.startsWith("f:") ? id.substring(2) : id;
            File f = new File(path);
            return f.isFile() ? f.length() : -1;
        }
    }

    /* --------------------------------------------------------- 工具 */

    private static String safe(String s) { return s == null ? "" : s; }

    /** MediaStore 里未知歌手会写成 "<unknown>"，展示成空更自然 */
    private static String nullSafe(String s) {
        if (s == null) return "";
        if (s.startsWith("<unknown>")) return "";
        return s;
    }

    private static String parentOf(String path) {
        if (path == null || path.isEmpty()) return "";
        int slash = path.lastIndexOf('/');
        if (slash <= 0) return "";
        return path.substring(0, slash);
    }

    private static String stripExt(String n) {
        if (n == null) return "";
        int d = n.lastIndexOf('.');
        return d > 0 ? n.substring(0, d) : n;
    }

    /** MediaStore 的 TRACK 常是 "3/12" 形式 */
    private static int narrow(int v) { return v < 0 ? 0 : (v >= 1000 ? v / 1000 : v); }
}
