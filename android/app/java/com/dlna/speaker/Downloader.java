package com.dlna.speaker;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * 在线曲目下载器
 * ==============
 * 直链与请求头由前端（WebView 里的插件运行时）解析好后传进来，
 * 这里只负责按「歌手/歌手 - 歌名.ext」落盘，串行执行避免打爆音源。
 *
 * 落盘位置由 {@link Storage} 决定（默认公共音乐目录，用户可见）。
 * 下载过程先写本地缓存里的 .part，全部读完且大小校验通过后，才搬到最终位置 ——
 * 这样用户不会在文件管理器里看到半截文件。
 *
 * 与 Python 版 bridge.js 一致的过滤规则：
 *   - 时长已知且 < 60 秒的（试听/广告）预检跳过
 *   - 下载完成但小于 1MB 的视为试听片段，自动删除
 */
public final class Downloader {

    public static final long MIN_VALID_BYTES = 1024 * 1024L;

    private final Storage storage;
    private final List<Map<String, Object>> jobs = new ArrayList<Map<String, Object>>();
    private final Object lock = new Object();
    private volatile Map<String, Object> active = null;

    public Downloader(Storage storage) {
        this.storage = storage;
    }

    /** items: [{provider,id,title,artist,url,headers:{...},duration_sec}] */
    public Map<String, Object> add(List<Object> items, String subDir) {
        int queued = 0, skipped = 0;
        List<String> skipWhy = new ArrayList<String>();
        synchronized (lock) {
            for (Object o : items) {
                Map<String, Object> it = Json.asMap(o);
                String url = Json.s(it, "url");
                if (url.isEmpty()) { skipped++; skipWhy.add("没有直链"); continue; }
                int dur = Json.i(it, "duration_sec", Json.i(it, "duration", 0));
                if (dur > 0 && dur < 60) { skipped++; skipWhy.add("时长不足 60 秒（试听）"); continue; }
                String key = Json.s(it, "id", url);
                if (findJob(key) != null) { skipped++; continue; }

                Map<String, Object> job = Json.map();
                job.put("key", key);
                job.put("provider", Json.s(it, "provider"));
                job.put("id", Json.s(it, "id"));
                job.put("title", Json.s(it, "title", "未知"));
                job.put("artist", Json.s(it, "artist"));
                job.put("url", url);
                job.put("headers", it.get("headers"));
                job.put("sub_dir", subDir == null ? "" : subDir.trim());
                job.put("status", "pending");
                job.put("size", 0L);
                job.put("ts", System.currentTimeMillis());
                jobs.add(0, job);
                queued++;
            }
            while (jobs.size() > 200) jobs.remove(jobs.size() - 1);
        }
        if (queued > 0) runQueueAsync();
        Map<String, Object> out = Json.map("ok", true, "queued", queued, "exists", skipped);
        if (!skipWhy.isEmpty()) out.put("skip_reason", join(skipWhy));
        return out;
    }

    private static String join(List<String> xs) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < xs.size() && i < 3; i++) {
            if (i > 0) sb.append("；");
            sb.append(xs.get(i));
        }
        return sb.toString();
    }

    private Map<String, Object> findJob(String key) {
        for (Map<String, Object> j : jobs) {
            if (key.equals(Json.s(j, "key"))) {
                String st = Json.s(j, "status");
                if (!"error".equals(st)) return j;
            }
        }
        return null;
    }

    public Map<String, Object> status() {
        Map<String, Object> out = Json.map();
        List<Object> list = new ArrayList<Object>();
        synchronized (lock) {
            for (int i = 0; i < jobs.size() && i < 50; i++) list.add(new LinkedHashMap<String, Object>(jobs.get(i)));
        }
        Map<String, Object> a = active;
        out.put("ok", true);
        out.put("active", a == null ? null : Json.s(a, "title"));
        out.put("jobs", list);
        out.put("dir", storage.describe());
        return out;
    }

    public void clear() {
        synchronized (lock) {
            List<Map<String, Object>> keep = new ArrayList<Map<String, Object>>();
            for (Map<String, Object> j : jobs) {
                String st = Json.s(j, "status");
                if ("pending".equals(st) || "downloading".equals(st)) keep.add(j);
            }
            jobs.clear();
            jobs.addAll(keep);
        }
    }

    private void runQueueAsync() {
        Thread t = new Thread(new Runnable() {
            @Override public void run() {
                try {
                    runQueue();
                } catch (Throwable ignore) {
                    // 裸线程里的未捕获异常在 Android 上会杀掉整个进程，必须兜住
                }
            }
        }, "downloader");
        t.setDaemon(true);
        t.start();
    }

    private void runQueue() {
        if (active != null) return;
        while (true) {
            Map<String, Object> job = null;
            synchronized (lock) {
                for (Map<String, Object> j : jobs) {
                    if ("pending".equals(Json.s(j, "status"))) { job = j; break; }
                }
            }
            if (job == null) return;
            active = job;
            job.put("status", "downloading");
            try {
                downloadOne(job);
            } catch (Throwable e) {
                job.put("status", "error");
                job.put("error", e.getClass().getSimpleName() + ": "
                        + (e.getMessage() == null ? "" : e.getMessage()));
            } finally {
                active = null;
            }
        }
    }

    @SuppressWarnings("unchecked")
    private void downloadOne(Map<String, Object> job) throws Exception {
        String url = Json.s(job, "url");
        Map<String, String> headers = new LinkedHashMap<String, String>();
        Object h = job.get("headers");
        if (h instanceof Map) {
            for (Map.Entry<String, Object> e : ((Map<String, Object>) h).entrySet()) {
                if (e.getValue() != null) headers.put(e.getKey(), String.valueOf(e.getValue()));
            }
        }

        String artist = Util.sanitizeName(Json.s(job, "artist"), "未知歌手");
        String title = Util.sanitizeName(Json.s(job, "title"), "未知曲目");

        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        File tmp = null;
        try {
            c.setConnectTimeout(20000);
            c.setReadTimeout(60000);
            c.setInstanceFollowRedirects(true);
            for (Map.Entry<String, String> e : headers.entrySet()) {
                String k = e.getKey().toLowerCase(Locale.ROOT);
                if ("host".equals(k) || "content-length".equals(k) || "connection".equals(k)) continue;
                c.setRequestProperty(e.getKey(), e.getValue());
            }
            int code = c.getResponseCode();
            if (code >= 400) throw new Exception("音源返回 HTTP " + code + "（链接可能已失效）");
            String ct = c.getContentType();
            String ext = Util.pickExt(url, ct);
            String mime = mimeOf(ext, ct);
            String fileName = Util.sanitizeName(artist + " - " + title, "track") + "." + ext;

            // 目标位置已有同名且够大，直接跳过
            long have = storage.sink().existingSize(artist, fileName);
            if (have > 0) {
                job.put("status", "exists");
                job.put("size", have);
                job.put("file", artist + "/" + fileName);
                return;
            }

            // 先落到本地缓存
            tmp = new File(storage.tmpDir(), "dl-" + System.nanoTime() + "." + ext);
            InputStream in = c.getInputStream();
            OutputStream out = new FileOutputStream(tmp);
            long bytes = 0;
            try {
                byte[] buf = new byte[65536];
                int n;
                while ((n = in.read(buf)) > 0) {
                    out.write(buf, 0, n);
                    bytes += n;
                    job.put("size", bytes);
                }
                out.flush();
            } finally {
                try { out.close(); } catch (Throwable ignore) { }
                try { in.close(); } catch (Throwable ignore) { }
            }

            if (bytes < MIN_VALID_BYTES) {
                job.put("status", "error");
                job.put("size", bytes);
                job.put("error", "文件只有 " + (bytes / 1024) + " KB，判定为试听片段，未保存");
                return;
            }

            long size = storage.sink().put(artist, fileName, tmp, mime, title);
            job.put("status", "done");
            job.put("size", size);
            job.put("file", artist + "/" + fileName);
            job.put("saved_to", storage.describe());
        } catch (Exception e) {
            throw e;
        } finally {
            try { c.disconnect(); } catch (Throwable ignore) { }
            if (tmp != null) { try { tmp.delete(); } catch (Throwable ignore) { } }
        }
    }

    private static String mimeOf(String ext, String ct) {
        if (ct != null && ct.toLowerCase(Locale.ROOT).startsWith("audio/")) return ct.split(";")[0].trim();
        String e = ext.toLowerCase(Locale.ROOT);
        if ("flac".equals(e)) return "audio/flac";
        if ("wav".equals(e)) return "audio/x-wav";
        if ("m4a".equals(e)) return "audio/mp4";
        if ("aac".equals(e)) return "audio/aac";
        if ("ogg".equals(e)) return "audio/ogg";
        if ("wma".equals(e)) return "audio/x-ms-wma";
        return "audio/mpeg";
    }
}
