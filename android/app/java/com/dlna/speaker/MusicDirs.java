package com.dlna.speaker;

import android.content.ContentResolver;
import android.content.Context;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.net.Uri;
import android.provider.DocumentsContract;

import java.io.InputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 用户添加的音乐目录
 * ==================
 * 支持两类来源：
 *   1) SAF —— 系统目录选择器挑的目录树。本地文件夹、SD 卡、U 盘，
 *      以及系统「文件」App 里挂载好的网络位置都能这么加。授权是持久化的。
 *   2) SMB —— 直接填 IP / 共享名 / 账号，走 {@link Smb} 连 NAS 或路由器共享。
 *
 * 目录配置存在 SharedPreferences 里，扫描时与系统媒体库合并成一份曲库。
 */
public final class MusicDirs {

    private static final String PREF = "music_dirs";
    private static final String K_LIST = "list";

    /** 曲目 id 前缀 */
    public static final String P_SAF = "c:";
    public static final String P_SMB = "n:";

    public static final class Entry {
        public String id = "";
        public String type = "saf";        // "saf" | "smb"
        public String name = "";
        public String uri = "";            // SAF
        public String host = "";           // SMB
        public String share = "";
        public String subpath = "";
        public String user = "";
        public String password = "";
        public boolean guest = false;

        public Map<String, Object> toJson() {
            Map<String, Object> m = Json.map();
            m.put("id", id);
            m.put("type", type);
            m.put("name", name);
            m.put("uri", uri);
            m.put("host", host);
            m.put("share", share);
            m.put("subpath", subpath);
            m.put("user", user);
            m.put("password", password);
            m.put("guest", guest);
            return m;
        }

        public static Entry from(Map<String, Object> m) {
            Entry e = new Entry();
            e.id = Json.s(m, "id");
            e.type = Json.s(m, "type", "saf");
            e.name = Json.s(m, "name");
            e.uri = Json.s(m, "uri");
            e.host = Json.s(m, "host");
            e.share = Json.s(m, "share");
            e.subpath = Json.s(m, "subpath");
            e.user = Json.s(m, "user");
            e.password = Json.s(m, "password");
            e.guest = Json.b(m, "guest", false);
            return e;
        }

        public Smb.Conn conn() {
            return new Smb.Conn(host, share, subpath, user, password, guest);
        }

        /** 给人看的地址 */
        public String addr() {
            if ("smb".equals(type)) {
                String s = host + "/" + share + (subpath.isEmpty() ? "" : "/" + subpath);
                return guest ? s + " · 匿名" : s;
            }
            return shortUri(uri);
        }

        public String displayName() {
            if (!name.isEmpty()) return name;
            if ("smb".equals(type)) return share.isEmpty() ? host : share;
            return shortUri(uri);
        }
    }

    private final Context ctx;
    private final SharedPreferences sp;

    public MusicDirs(Context ctx) {
        this.ctx = ctx.getApplicationContext();
        this.sp = this.ctx.getSharedPreferences(PREF, Context.MODE_PRIVATE);
    }

    /* ------------------------------------------------------------ 持久化 */

    @SuppressWarnings("unchecked")
    public synchronized List<Entry> list() {
        List<Entry> out = new ArrayList<Entry>();
        try {
            String raw = sp.getString(K_LIST, "");
            if (raw == null || raw.isEmpty()) return out;
            List<Object> arr = Json.asList(Json.parse(raw));
            for (Object o : arr) out.add(Entry.from(Json.asMap(o)));
        } catch (Throwable ignore) { }
        return out;
    }

    private synchronized void save(List<Entry> es) {
        List<Object> arr = new ArrayList<Object>();
        for (Entry e : es) arr.add(e.toJson());
        sp.edit().putString(K_LIST, Json.write(arr)).apply();
    }

    public Entry find(String id) {
        if (id == null) return null;
        for (Entry e : list()) if (id.equals(e.id)) return e;
        return null;
    }

    private static String newId() {
        return "d" + Long.toString(System.currentTimeMillis(), 36) + Integer.toString((int) (Math.random() * 46656), 36);
    }

    /** 同名同地址的目录不重复添加 */
    private boolean dup(List<Entry> es, Entry n) {
        for (Entry e : es) {
            if (!e.type.equals(n.type)) continue;
            if ("saf".equals(n.type) && e.uri.equals(n.uri)) return true;
            if ("smb".equals(n.type) && e.host.equalsIgnoreCase(n.host) && e.share.equalsIgnoreCase(n.share)
                    && e.subpath.equalsIgnoreCase(n.subpath)) return true;
        }
        return false;
    }

    public Entry addSaf(Uri tree, String name) {
        List<Entry> es = list();
        Entry e = new Entry();
        e.id = newId();
        e.type = "saf";
        e.uri = tree.toString();
        e.name = (name == null || name.trim().isEmpty()) ? guessSafName(tree) : name.trim();
        if (dup(es, e)) {
            for (Entry x : es) if ("saf".equals(x.type) && x.uri.equals(e.uri)) return x;
        }
        es.add(e);
        save(es);
        return e;
    }

    public Entry addSmb(Smb.Conn c, String name) {
        List<Entry> es = list();
        Entry e = new Entry();
        e.id = newId();
        e.type = "smb";
        e.host = c.host;
        e.share = c.share;
        e.subpath = c.subpath;
        e.user = c.user;
        e.password = c.password;
        e.guest = c.guest;
        e.name = (name == null || name.trim().isEmpty())
                ? (c.share.isEmpty() ? c.host : c.share) : name.trim();
        if (dup(es, e)) {
            for (Entry x : es) {
                if ("smb".equals(x.type) && x.host.equalsIgnoreCase(e.host)
                        && x.share.equalsIgnoreCase(e.share) && x.subpath.equalsIgnoreCase(e.subpath)) return x;
            }
        }
        es.add(e);
        save(es);
        return e;
    }

    public boolean remove(String id) {
        List<Entry> es = list();
        boolean hit = false;
        for (int i = es.size() - 1; i >= 0; i--) {
            if (es.get(i).id.equals(id)) { es.remove(i); hit = true; }
        }
        if (hit) save(es);
        return hit;
    }

    public boolean rename(String id, String name) {
        List<Entry> es = list();
        for (Entry e : es) {
            if (e.id.equals(id)) {
                e.name = name == null ? "" : name.trim();
                save(es);
                return true;
            }
        }
        return false;
    }

    /* -------------------------------------------------------------- 扫描 */

    /**
     * 扫描全部用户目录。返回的每项已经是可以直接用的曲目结构。
     * filesLeft 是全局剩余配额，避免多个源加起来把内存撑爆。
     */
    public List<Map<String, Object>> scan(int maxFiles, long maxMillis) {
        List<Map<String, Object>> out = new ArrayList<Map<String, Object>>();
        long deadline = System.currentTimeMillis() + maxMillis;
        for (Entry e : list()) {
            if (out.size() >= maxFiles) break;
            if (System.currentTimeMillis() > deadline) break;
            try {
                if ("saf".equals(e.type)) scanSaf(e, out, maxFiles, deadline);
                else scanSmb(e, out, maxFiles, deadline);
            } catch (Throwable ignore) { }
        }
        return out;
    }

    /* ---- SAF ---- */

    private void scanSaf(Entry e, List<Map<String, Object>> out, int maxFiles, long deadline) {
        Uri tree;
        try { tree = Uri.parse(e.uri); } catch (Throwable t) { return; }
        String rootId;
        try { rootId = DocumentsContract.getTreeDocumentId(tree); } catch (Throwable t) { return; }
        walkSaf(e, tree, rootId, "", out, 0, maxFiles, deadline);
    }

    private void walkSaf(Entry e, Uri tree, String docId, String rel,
                         List<Map<String, Object>> out, int depth, int maxFiles, long deadline) {
        if (depth > 8 || out.size() >= maxFiles) return;
        if (System.currentTimeMillis() > deadline) return;
        ContentResolver cr = ctx.getContentResolver();
        Uri children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, docId);
        Cursor c = null;
        try {
            String[] proj = {
                    DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                    DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                    DocumentsContract.Document.COLUMN_MIME_TYPE,
                    DocumentsContract.Document.COLUMN_SIZE,
            };
            c = cr.query(children, proj, null, null, null);
            if (c == null) return;
            while (c.moveToNext()) {
                if (out.size() >= maxFiles) return;
                if (System.currentTimeMillis() > deadline) return;
                String id = c.getString(0);
                String name = c.getString(1);
                String mime = c.getString(2);
                long size = c.isNull(3) ? -1 : c.getLong(3);
                if (name == null || name.startsWith(".")) continue;
                String childRel = rel.isEmpty() ? name : rel + "/" + name;
                if (DocumentsContract.Document.MIME_TYPE_DIR.equals(mime)) {
                    walkSaf(e, tree, id, childRel, out, depth + 1, maxFiles, deadline);
                } else if (Util.isAudio(name)) {
                    out.add(safTrack(e, tree, id, name, rel, childRel, size));
                }
            }
        } catch (Throwable ignore) {
        } finally {
            if (c != null) try { c.close(); } catch (Throwable ignore2) { }
        }
    }

    private static Map<String, Object> safTrack(Entry e, Uri tree, String docId, String name,
                                                String dir, String rel, long size) {
        Uri doc = DocumentsContract.buildDocumentUriUsingTree(tree, docId);
        Map<String, Object> m = Json.map();
        m.put("id", P_SAF + Util.base64(doc.toString().getBytes()));
        m.put("title", stem(name));
        m.put("artist", "");
        m.put("album", "");
        m.put("folder", e.displayName() + (dir.isEmpty() ? "" : "/" + dir));
        m.put("path", e.displayName() + "/" + rel);
        m.put("source", "local");
        m.put("duration_sec", 0);
        m.put("size", size);
        return m;
    }

    /* ---- SMB ---- */

    private void scanSmb(Entry e, List<Map<String, Object>> out, int maxFiles, long deadline) {
        List<Map<String, Object>> found = Smb.scan(e.conn(), maxFiles - out.size(), 8,
                Math.max(5000, deadline - System.currentTimeMillis()));
        for (Map<String, Object> f : found) {
            if (out.size() >= maxFiles) return;
            String rel = Json.s(f, "rel");
            String name = Json.s(f, "name");
            String dir = Json.s(f, "dir");
            Map<String, Object> m = Json.map();
            m.put("id", P_SMB + Util.base64((e.id + "|" + rel).getBytes()));
            m.put("title", stem(name));
            m.put("artist", "");
            m.put("album", "");
            m.put("folder", e.displayName() + (dir.isEmpty() ? "" : "/" + dir));
            m.put("path", e.displayName() + "/" + rel);
            m.put("source", "local");
            m.put("src_id", e.id);
            m.put("duration_sec", 0);
            m.put("size", Json.l(f, "size", -1));
            out.add(m);
        }
    }

    /* -------------------------------------------------------------- 读取 */

    public static boolean isUserTrack(String id) {
        return id != null && (id.startsWith(P_SAF) || id.startsWith(P_SMB));
    }

    /** 读取与曲目同目录、同文件名但不同扩展名的文本（用来找 .lrc 歌词） */
    public String readSiblingText(String id, String wantExt) {
        try {
            if (id.startsWith(P_SAF)) {
                Uri doc = Uri.parse(new String(Util.unbase64(id.substring(P_SAF.length()))));
                Uri tree = treeOf(doc);
                if (tree == null) return "";
                String docId;
                try { docId = DocumentsContract.getDocumentId(doc); } catch (Throwable t) { return ""; }
                int slash = docId.lastIndexOf('/');
                String parent = slash > 0 ? docId.substring(0, slash) : "";
                String name = slash >= 0 ? docId.substring(slash + 1) : docId;
                String childId = findChildId(tree, parent, Lyrics.stripExt(name) + "." + wantExt);
                if (childId == null) return "";
                Uri cu = DocumentsContract.buildDocumentUriUsingTree(tree, childId);
                InputStream in = ctx.getContentResolver().openInputStream(cu);
                if (in == null) return "";
                try { return Lyrics.readText(in); } finally { try { in.close(); } catch (Throwable ignore) { } }
            }
            if (id.startsWith(P_SMB)) {
                String raw = new String(Util.unbase64(id.substring(P_SMB.length())));
                int bar = raw.indexOf('|');
                if (bar <= 0) return "";
                Entry e = find(raw.substring(0, bar));
                if (e == null) return "";
                String rel = raw.substring(bar + 1);
                return Smb.readText(Smb.url(e.conn(), Lyrics.brother(rel, wantExt)), e.conn());
            }
        } catch (Throwable ignore) { }
        return "";
    }

    /** 从文档 URI 反推它所属的目录树 URI */
    private static Uri treeOf(Uri doc) {
        String s = doc.toString();
        int i = s.indexOf("/document/");
        if (i < 0) return null;
        try { return Uri.parse(s.substring(0, i)); } catch (Throwable t) { return null; }
    }

    private String findChildId(Uri tree, String parentDocId, String name) {
        Cursor c = null;
        try {
            Uri children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, parentDocId);
            c = ctx.getContentResolver().query(children, new String[]{
                    DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                    DocumentsContract.Document.COLUMN_DISPLAY_NAME}, null, null, null);
            if (c == null) return null;
            while (c.moveToNext()) {
                if (name.equalsIgnoreCase(c.getString(1))) return c.getString(0);
            }
        } catch (Throwable ignore) {
        } finally {
            if (c != null) try { c.close(); } catch (Throwable ignore2) { }
        }
        return null;
    }

    public InputStream open(String id) throws Exception {
        if (id.startsWith(P_SAF)) {
            Uri doc = Uri.parse(new String(Util.unbase64(id.substring(P_SAF.length()))));
            InputStream in = ctx.getContentResolver().openInputStream(doc);
            if (in == null) throw new Exception("无法打开文件（可能已被删除或权限失效）");
            return in;
        }
        if (id.startsWith(P_SMB)) {
            String raw = new String(Util.unbase64(id.substring(P_SMB.length())));
            int bar = raw.indexOf('|');
            if (bar <= 0) throw new Exception("无效的共享文件");
            Entry e = find(raw.substring(0, bar));
            if (e == null) throw new Exception("共享目录已被移除");
            return Smb.open(Smb.url(e.conn(), raw.substring(bar + 1)), e.conn());
        }
        throw new Exception("不是用户目录曲目: " + id);
    }

    public long size(String id) {
        try {
            if (id.startsWith(P_SAF)) {
                Uri doc = Uri.parse(new String(Util.unbase64(id.substring(P_SAF.length()))));
                Cursor c = ctx.getContentResolver().query(doc,
                        new String[]{ DocumentsContract.Document.COLUMN_SIZE }, null, null, null);
                try {
                    if (c != null && c.moveToFirst() && !c.isNull(0)) return c.getLong(0);
                } finally { if (c != null) try { c.close(); } catch (Throwable ignore) { } }
                return -1;
            }
            if (id.startsWith(P_SMB)) {
                String raw = new String(Util.unbase64(id.substring(P_SMB.length())));
                int bar = raw.indexOf('|');
                if (bar <= 0) return -1;
                Entry e = find(raw.substring(0, bar));
                if (e == null) return -1;
                return Smb.size(Smb.url(e.conn(), raw.substring(bar + 1)), e.conn());
            }
        } catch (Throwable ignore) { }
        return -1;
    }

    /* -------------------------------------------------------------- 工具 */

    private static String stem(String n) {
        if (n == null) return "";
        int d = n.lastIndexOf('.');
        return d > 0 ? n.substring(0, d) : n;
    }

    public static String shortUri(String uri) {
        if (uri == null || uri.isEmpty()) return "";
        String s = uri;
        int i = s.indexOf("/tree/");
        if (i >= 0) s = s.substring(i + 6);
        else if (s.startsWith("content://")) s = s.substring(s.indexOf('/', 10) + 1);
        try { s = java.net.URLDecoder.decode(s, "UTF-8"); } catch (Throwable ignore) { }
        if (s.endsWith("/")) s = s.substring(0, s.length() - 1);
        return s;
    }

    /** 从 SAF 的 tree URI 猜一个可读名字 */
    static String guessSafName(Uri tree) {
        String s = shortUri(tree.toString());
        int slash = s.lastIndexOf('/');
        String last = slash >= 0 ? s.substring(slash + 1) : s;
        int colon = last.indexOf(':');
        if (colon >= 0) last = last.substring(colon + 1);
        if (last.isEmpty() || "0".equals(last)) return "外部存储";
        return last;
    }
}
