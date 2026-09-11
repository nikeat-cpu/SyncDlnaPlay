package com.dlna.speaker;

import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * 本机音乐库
 * ==========
 * 扫描器（Scanner）与文件读取器（Opener）都是可插拔的：
 *   - Android 上注入基于 MediaStore 的实现（规避 Android 11+ 分区存储限制）
 *   - 桌面 / 有真实文件路径时用 FilesScanner + 直接文件读取
 * 索引在内存中，字段与前端约定的曲目结构一致。
 */
public final class Library {

    /** 扫描器：返回曲目列表；每项至少含 id/title/path/folder */
    public interface Scanner { List<Map<String, Object>> scan() throws Exception; }

    /** 打开某个 id 对应的音频流（用于把本地音乐喂给音响） */
    public interface Opener {
        InputStream open(String id) throws Exception;
        long size(String id);
    }

    private Scanner scanner;
    private Opener opener;

    private volatile List<Map<String, Object>> tracks = new ArrayList<Map<String, Object>>();
    private final Map<String, Map<String, Object>> byId = new LinkedHashMap<String, Map<String, Object>>();
    private final AtomicBoolean scanning = new AtomicBoolean(false);
    private volatile boolean truncated = false;
    private volatile long lastScan = 0;
    private volatile String lastError = "";

    /** 扫描上限：防止误选整个存储卡时把手机拖死 */
    public static final int MAX_FILES = 30000;
    public static final int MAX_DEPTH = 8;
    public static final int MAX_SECONDS = 90;

    public void setScanner(Scanner s, Opener o) {
        this.scanner = s;
        this.opener = o;
    }

    public boolean ready() { return !tracks.isEmpty(); }
    public boolean enabled() { return scanner != null; }
    public boolean isScanning() { return scanning.get(); }
    public boolean isTruncated() { return truncated; }
    public long getLastScan() { return lastScan; }
    public String getLastError() { return lastError; }
    public int count() { return tracks.size(); }

    public void scanAsync() {
        if (scanner == null || scanning.get()) return;
        Thread t = new Thread(new Runnable() {
            @Override public void run() {
                try {
                    scan();
                } catch (Throwable t) {
                    lastError = String.valueOf(t);
                }
            }
        }, "lib-scan");
        t.setDaemon(true);
        t.start();
    }

    public synchronized void scan() {
        if (scanner == null) return;
        if (!scanning.compareAndSet(false, true)) return;
        try {
            List<Map<String, Object>> list = scanner.scan();
            Map<String, Map<String, Object>> idx = new LinkedHashMap<String, Map<String, Object>>();
            for (Map<String, Object> t : list) {
                String id = Json.s(t, "id");
                if (!id.isEmpty()) idx.put(id, t);
            }
            tracks = list;
            byId.clear();
            byId.putAll(idx);
            truncated = list.size() >= MAX_FILES;
            lastScan = System.currentTimeMillis() / 1000L;
            lastError = "";
        } catch (Throwable e) {
            lastError = String.valueOf(e.getMessage() == null ? e : e.getMessage());
        } finally {
            scanning.set(false);
        }
    }

    public void clear() {
        tracks = new ArrayList<Map<String, Object>>();
        byId.clear();
        lastScan = 0;
    }

    public List<Map<String, Object>> all() { return tracks; }

    /** 按来源统计曲目数（对应曲目里的 src_id 字段） */
    public int countBySrc(String srcId) {
        if (srcId == null || srcId.isEmpty()) return 0;
        int n = 0;
        for (Map<String, Object> t : tracks) {
            if (srcId.equals(Json.s(t, "src_id"))) n++;
        }
        return n;
    }

    public Map<String, Object> byId(String id) { return byId.get(id); }

    public InputStream open(String id) throws Exception {
        if (opener == null) throw new IllegalStateException("曲库读取器未初始化");
        return opener.open(id);
    }

    public long sizeOf(String id) {
        return opener == null ? -1 : opener.size(id);
    }

    /** 目录树：返回指定父目录下的直接子目录（父目录为 "" 时返回顶层） */
    public List<Map<String, Object>> folders(String parent) {
        String prefix = parent == null ? "" : parent.trim();
        if (!prefix.isEmpty() && !prefix.endsWith("/")) prefix = prefix + "/";
        Map<String, int[]> agg = new LinkedHashMap<String, int[]>();
        for (Map<String, Object> t : tracks) {
            String folder = Json.s(t, "folder");
            if (!folder.startsWith(prefix)) continue;
            String rest = folder.substring(prefix.length());
            if (rest.isEmpty()) continue;
            int slash = rest.indexOf('/');
            String child = slash < 0 ? rest : rest.substring(0, slash);
            if (child.isEmpty()) continue;
            int[] c = agg.get(child);
            if (c == null) { c = new int[]{0}; agg.put(child, c); }
            c[0]++;
        }
        List<Map<String, Object>> out = new ArrayList<Map<String, Object>>();
        for (Map.Entry<String, int[]> e : agg.entrySet()) {
            Map<String, Object> m = Json.map();
            m.put("name", e.getKey());
            m.put("path", prefix + e.getKey());
            m.put("count", e.getValue()[0]);
            m.put("type", "folder");
            out.add(m);
        }
        Collections.sort(out, new java.util.Comparator<Map<String, Object>>() {
            @Override public int compare(Map<String, Object> a, Map<String, Object> b) {
                return Json.s(a, "name").compareToIgnoreCase(Json.s(b, "name"));
            }
        });
        return out;
    }

    /** 列出某目录（含子目录）下的曲目 */
    public List<Map<String, Object>> list(String folder, boolean recursive) {
        String prefix = folder == null ? "" : folder.trim();
        List<Map<String, Object>> out = new ArrayList<Map<String, Object>>();
        for (Map<String, Object> t : tracks) {
            String f = Json.s(t, "folder");
            if (prefix.isEmpty()) {
                out.add(t);
            } else if (f.equals(prefix) || (recursive && f.startsWith(prefix + "/"))) {
                out.add(t);
            }
        }
        Collections.sort(out, new java.util.Comparator<Map<String, Object>>() {
            @Override public int compare(Map<String, Object> a, Map<String, Object> b) {
                String fa = Json.s(a, "folder"), fb = Json.s(b, "folder");
                int c = fa.compareToIgnoreCase(fb);
                if (c != 0) return c;
                int na = Json.i(a, "track_no", 0), nb = Json.i(b, "track_no", 0);
                if (na != nb && na > 0 && nb > 0) return na - nb;
                return Json.s(a, "title").compareToIgnoreCase(Json.s(b, "title"));
            }
        });
        return out;
    }

    /** 关键字搜索（标题 / 歌手 / 专辑） */
    public List<Map<String, Object>> search(String kw) {
        String q = kw == null ? "" : kw.trim().toLowerCase(Locale.ROOT);
        List<Map<String, Object>> out = new ArrayList<Map<String, Object>>();
        if (q.isEmpty()) return out;
        for (Map<String, Object> t : tracks) {
            String hay = (Json.s(t, "title") + " " + Json.s(t, "artist") + " " + Json.s(t, "album"))
                    .toLowerCase(Locale.ROOT);
            if (hay.contains(q)) out.add(t);
        }
        return out;
    }

    /* ------------------------------------------------ 桌面 / 文件系统扫描器 */

    /** 基于文件系统的扫描器（桌面验证用；Android 上有真实路径时也可用） */
    public static final class FilesScanner implements Scanner {
        private final List<File> roots;
        private long deadline;

        public FilesScanner(List<File> roots) { this.roots = roots; }

        @Override public List<Map<String, Object>> scan() {
            List<Map<String, Object>> out = new ArrayList<Map<String, Object>>();
            deadline = System.currentTimeMillis() + MAX_SECONDS * 1000L;
            for (File root : roots) walk(root, root, out, 0);
            return out;
        }

        private void walk(File root, File dir, List<Map<String, Object>> out, int depth) {
            if (depth > MAX_DEPTH || out.size() >= MAX_FILES) return;
            if (System.currentTimeMillis() > deadline) return;
            File[] files = dir.listFiles();
            if (files == null) return;
            for (File f : files) {
                if (out.size() >= MAX_FILES) return;
                String name = f.getName();
                if (name.startsWith(".")) continue;
                try {
                    if (f.isDirectory()) {
                        if (name.equalsIgnoreCase("lost+found") || name.equalsIgnoreCase("Android")) continue;
                        walk(root, f, out, depth + 1);
                    } else if (f.isFile() && Util.isAudio(name)) {
                        out.add(makeTrack(root, f));
                    }
                } catch (Exception ignore) { }
            }
        }

        private Map<String, Object> makeTrack(File root, File f) {
            String rel = root.toURI().relativize(f.toURI()).getPath();
            String folder = "";
            int slash = rel.lastIndexOf('/');
            if (slash > 0) folder = Util.urlDecode(rel.substring(0, slash));
            Map<String, Object> m = Json.map();
            m.put("id", "f:" + f.getAbsolutePath());
            m.put("title", stripExt(f.getName()));
            m.put("artist", "");
            m.put("album", "");
            m.put("folder", folder);
            m.put("path", f.getAbsolutePath());
            m.put("size", f.length());
            m.put("duration_sec", 0);
            m.put("source", "local");
            return m;
        }

        private static String stripExt(String n) {
            int d = n.lastIndexOf('.');
            return d > 0 ? n.substring(0, d) : n;
        }
    }

    /** 文件系统读取器 */
    public static final class FilesOpener implements Opener {
        @Override public InputStream open(String id) throws Exception {
            String path = id.startsWith("f:") ? id.substring(2) : id;
            return new FileInputStream(path);
        }
        @Override public long size(String id) {
            String path = id.startsWith("f:") ? id.substring(2) : id;
            File f = new File(path);
            return f.isFile() ? f.length() : -1;
        }
    }
}
