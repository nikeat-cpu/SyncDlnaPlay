package com.dlna.speaker;

import android.content.ContentResolver;
import android.content.ContentUris;
import android.content.ContentValues;
import android.content.Context;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.DocumentsContract;
import android.provider.MediaStore;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;

/**
 * Android 上的下载落盘实现
 * ========================
 * 两种目标：
 *   1) 默认 —— 公共音乐目录 Music/音响管家/，走 MediaStore。
 *      API 29+ 不需要任何存储权限，文件在「文件管理」里可见，
 *      系统媒体库会自动收录，因此曲库也能直接扫到。
 *      这是旧版「下载了却找不到」的根治办法。
 *   2) 自定义 —— 用户用系统目录选择器（SAF）挑的任意目录树。
 *      支持 SD 卡、U 盘，以及系统「文件」App 里挂载好的网络位置。
 *      授权持久化（takePersistableUriPermission），重启后依然有效。
 */
public final class AndroidStorage implements Storage {

    private static final String PREF = "storage_cfg";
    private static final String K_MODE = "dl_mode";        // "public" | "saf"
    private static final String K_TREE = "dl_tree_uri";
    private static final String K_TREE_NAME = "dl_tree_name";
    private static final String K_SUBDIR = "dl_subdir";

    public static final String PUBLIC_ROOT = "Music";
    private static final String DEFAULT_SUBDIR = "音响管家";

    private final Context ctx;
    private final SharedPreferences sp;

    public AndroidStorage(Context ctx) {
        this.ctx = ctx.getApplicationContext();
        this.sp = this.ctx.getSharedPreferences(PREF, Context.MODE_PRIVATE);
    }

    /* --------------------------------------------------------------- 配置 */

    public Uri treeUri() {
        String s = sp.getString(K_TREE, "");
        return s.isEmpty() ? null : Uri.parse(s);
    }

    @Override public boolean isCustom() {
        return "saf".equals(sp.getString(K_MODE, "public")) && treeUri() != null;
    }

    @Override public String customName() {
        return sp.getString(K_TREE_NAME, "自定义目录");
    }

    @Override public void setCustom(String uri, String name) {
        if (uri == null || uri.isEmpty()) return;
        sp.edit().putString(K_MODE, "saf")
                .putString(K_TREE, uri)
                .putString(K_TREE_NAME, name == null || name.isEmpty() ? "自定义目录" : name)
                .apply();
    }

    @Override public void clearCustom() {
        sp.edit().putString(K_MODE, "public").apply();
    }

    @Override public String subDir() {
        String s = sp.getString(K_SUBDIR, DEFAULT_SUBDIR);
        return (s == null || s.trim().isEmpty()) ? DEFAULT_SUBDIR : s.trim();
    }

    @Override public void setSubDir(String name) {
        String v = (name == null || name.trim().isEmpty())
                ? DEFAULT_SUBDIR : Util.sanitizeName(name, DEFAULT_SUBDIR);
        sp.edit().putString(K_SUBDIR, v).apply();
    }

    /* --------------------------------------------------------------- 描述 */

    @Override public String describe() {
        if (isCustom()) {
            return PUBLIC_ROOT + " 之外的自定义目录 · " + customName() + "\n" + shortUri(treeUri());
        }
        if (Build.VERSION.SDK_INT >= 29) {
            return "Music/" + subDir() + "/\n（手机「文件管理」里可见，系统音乐 App 也能扫到）";
        }
        return defaultDir().getAbsolutePath() + "/";
    }

    @Override public File defaultDir() {
        File base = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MUSIC);
        if (base == null) base = new File(Environment.getExternalStorageDirectory(), PUBLIC_ROOT);
        return new File(base, subDir());
    }

    @Override public File tmpDir() {
        File d = new File(ctx.getCacheDir(), "dl");
        if (!d.exists()) d.mkdirs();
        return d;
    }

    private static String shortUri(Uri u) {
        if (u == null) return "";
        String s = u.toString();
        int i = s.indexOf("/tree/");
        if (i >= 0) s = s.substring(i + 6);
        try { s = java.net.URLDecoder.decode(s, "UTF-8"); } catch (Throwable ignore) { }
        return s;
    }

    /* --------------------------------------------------------------- 落盘 */

    @Override public Sink sink() {
        if (isCustom()) {
            Uri t = treeUri();
            if (t != null) return new SafSink(ctx, t);
        }
        if (Build.VERSION.SDK_INT >= 29) return new MediaStoreSink(ctx, subDir());
        return new AppFileSink(defaultDir());
    }

    /* --------------------- 实现一：公共目录（MediaStore） --------------------- */

    /**
     * API 29+ 走 MediaStore：无需存储权限，文件进系统媒体库，用户和音乐 App 都能看见。
     * 用 IS_PENDING 标记，写完才对外可见，避免出现半截文件。
     */
    static final class MediaStoreSink implements Sink {
        private final Context ctx;
        private final String sub;
        MediaStoreSink(Context c, String sub) { this.ctx = c; this.sub = sub; }

        @Override public String describe() { return "Music/" + sub + "/"; }

        private String relPath(String artist) {
            return PUBLIC_ROOT + "/" + sub + "/" + artist + "/";
        }

        private Uri queryByName(String artist, String fileName) {
            try {
                ContentResolver cr = ctx.getContentResolver();
                String[] proj = { MediaStore.Audio.Media._ID };
                String sel = MediaStore.Audio.Media.DISPLAY_NAME + "=? AND "
                        + MediaStore.Audio.Media.RELATIVE_PATH + " LIKE ?";
                String[] args = { fileName, relPath(artist) + "%" };
                Cursor c = cr.query(MediaStore.Audio.Media.EXTERNAL_CONTENT_URI, proj, sel, args, null);
                try {
                    if (c != null && c.moveToFirst()) return ContentUris.withAppendedId(
                            MediaStore.Audio.Media.EXTERNAL_CONTENT_URI, c.getLong(0));
                } finally { if (c != null) c.close(); }
            } catch (Throwable ignore) { }
            return null;
        }

        @Override public long existingSize(String artist, String fileName) {
            try {
                Uri u = queryByName(artist, fileName);
                if (u == null) return 0;
                Cursor c = ctx.getContentResolver().query(u,
                        new String[]{ MediaStore.Audio.Media.SIZE }, null, null, null);
                try {
                    if (c != null && c.moveToFirst()) {
                        long n = c.getLong(0);
                        return n > 0 ? n : -1;
                    }
                } finally { if (c != null) c.close(); }
                return -1;
            } catch (Throwable t) { return 0; }
        }

        @Override public long put(String artist, String fileName, File local, String mime, String title) throws Exception {
            ContentResolver cr = ctx.getContentResolver();
            ContentValues v = new ContentValues();
            v.put(MediaStore.Audio.Media.DISPLAY_NAME, fileName);
            v.put(MediaStore.Audio.Media.TITLE, title);
            v.put(MediaStore.Audio.Media.ARTIST, artist);
            v.put(MediaStore.Audio.Media.MIME_TYPE, mime);
            v.put(MediaStore.Audio.Media.RELATIVE_PATH, relPath(artist));
            v.put(MediaStore.Audio.Media.IS_PENDING, 1);
            Uri item = cr.insert(MediaStore.Audio.Media.EXTERNAL_CONTENT_URI, v);
            if (item == null) throw new Exception("系统媒体库拒绝创建文件（可能同名冲突）");
            try {
                OutputStream os = cr.openOutputStream(item, "w");
                if (os == null) throw new Exception("无法打开输出流");
                copy(local, os);
                ContentValues done = new ContentValues();
                done.put(MediaStore.Audio.Media.IS_PENDING, 0);
                cr.update(item, done, null, null);
                return local.length();
            } catch (Exception e) {
                try { cr.delete(item, null, null); } catch (Throwable ignore) { }
                throw e;
            }
        }
    }

    /* --------------------- 实现二：SAF 自定义目录 --------------------- */

    /**
     * 用户指定的目录树。全部走 DocumentsContract 原生接口（不引 androidx）。
     */
    static final class SafSink implements Sink {
        private final Context ctx;
        private final Uri tree;
        SafSink(Context c, Uri tree) { this.ctx = c; this.tree = tree; }

        @Override public String describe() { return "自定义目录（SAF）"; }

        private String rootDocId() { return DocumentsContract.getTreeDocumentId(tree); }

        private Uri childrenUri(String docId) {
            return DocumentsContract.buildChildDocumentsUriUsingTree(tree, docId);
        }

        private String findChild(String parentDocId, String name, boolean dir) {
            try {
                ContentResolver cr = ctx.getContentResolver();
                String[] proj = {
                        DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                        DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                        DocumentsContract.Document.COLUMN_MIME_TYPE,
                };
                Cursor c = cr.query(childrenUri(parentDocId), proj, null, null, null);
                try {
                    if (c == null) return null;
                    while (c.moveToNext()) {
                        String id = c.getString(0), dn = c.getString(1), mt = c.getString(2);
                        if (name.equals(dn) && (!dir || DocumentsContract.Document.MIME_TYPE_DIR.equals(mt))) return id;
                    }
                } finally { if (c != null) c.close(); }
            } catch (Throwable ignore) { }
            return null;
        }

        private long sizeOf(String docId) {
            try {
                Uri u = DocumentsContract.buildDocumentUriUsingTree(tree, docId);
                Cursor c = ctx.getContentResolver().query(u,
                        new String[]{ DocumentsContract.Document.COLUMN_SIZE }, null, null, null);
                try {
                    if (c != null && c.moveToFirst()) {
                        if (c.isNull(0)) return -1;
                        long n = c.getLong(0);
                        return n > 0 ? n : -1;
                    }
                } finally { if (c != null) c.close(); }
            } catch (Throwable ignore) { }
            return -1;
        }

        private String ensureDir(String parentDocId, String name) throws Exception {
            String id = findChild(parentDocId, name, true);
            if (id != null) return id;
            Uri dir = DocumentsContract.createDocument(ctx.getContentResolver(),
                    DocumentsContract.buildDocumentUriUsingTree(tree, parentDocId),
                    DocumentsContract.Document.MIME_TYPE_DIR, name);
            if (dir == null) throw new Exception("无法创建目录: " + name);
            return DocumentsContract.getDocumentId(dir);
        }

        @Override public long existingSize(String artist, String fileName) {
            try {
                String dir = findChild(rootDocId(), artist, true);
                if (dir == null) return 0;
                String f = findChild(dir, fileName, false);
                if (f == null) return 0;
                return sizeOf(f);
            } catch (Throwable t) { return 0; }
        }

        @Override public long put(String artist, String fileName, File local, String mime, String title) throws Exception {
            ContentResolver cr = ctx.getContentResolver();
            String dir = ensureDir(rootDocId(), artist);
            String exist = findChild(dir, fileName, false);
            if (exist != null) {
                try {
                    DocumentsContract.deleteDocument(cr, DocumentsContract.buildDocumentUriUsingTree(tree, exist));
                } catch (Throwable ignore) { }
            }
            Uri doc = DocumentsContract.createDocument(cr,
                    DocumentsContract.buildDocumentUriUsingTree(tree, dir), mime, fileName);
            if (doc == null) throw new Exception("目录不可写或空间不足");
            try {
                OutputStream os = cr.openOutputStream(doc, "w");
                if (os == null) throw new Exception("无法打开输出流");
                copy(local, os);
                return local.length();
            } catch (Exception e) {
                try { DocumentsContract.deleteDocument(cr, doc); } catch (Throwable ignore) { }
                throw e;
            }
        }
    }

    /* --------------------- 实现三：应用目录（兜底） --------------------- */

    /** API < 29 又没有写外部存储权限时的退路 */
    static final class AppFileSink implements Sink {
        private final File root;
        AppFileSink(File root) { this.root = root; }

        @Override public String describe() { return root.getAbsolutePath(); }

        @Override public long existingSize(String artist, String fileName) {
            try {
                File f = new File(new File(root, artist), fileName);
                if (!f.isFile()) return 0;
                return f.length() > 0 ? f.length() : -1;
            } catch (Throwable t) { return 0; }
        }

        @Override public long put(String artist, String fileName, File local, String mime, String title) throws Exception {
            File dir = new File(root, artist);
            if (!dir.exists() && !dir.mkdirs() && !dir.isDirectory()) throw new Exception("无法创建目录: " + dir);
            File dst = new File(dir, fileName);
            if (dst.exists() && !dst.delete()) throw new Exception("无法覆盖已存在的文件");
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
    }

    private static void copy(File src, OutputStream os) throws Exception {
        InputStream in = new FileInputStream(src);
        try {
            byte[] buf = new byte[65536];
            int n;
            while ((n = in.read(buf)) > 0) os.write(buf, 0, n);
            os.flush();
        } finally {
            try { in.close(); } catch (Throwable ignore) { }
            try { os.close(); } catch (Throwable ignore) { }
        }
    }
}
