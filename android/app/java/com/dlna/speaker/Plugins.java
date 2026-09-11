package com.dlna.speaker;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 音源仓库（MusicFree 插件管理）
 * ==============================
 * 内置音源直接读 APK 的 assets/plugins/*.js，用户自己添加的存在应用私有目录：
 *
 *   <dataDir>/plugins/        启用中的自建音源
 *   <dataDir>/plugins-off/    被停用的自建音源
 *   <dataDir>/plugins/state.json  被停用的**内置**音源名单
 *
 * 「添加音源」要能吃下 MusicFree 生态里常见的几种分发形式，因为它们长得都不一样：
 *
 *   1. 单个 .js 插件源码                    → 直接存
 *   2. 订阅文件（JSON，可能是 base64 包裹）  → 拆出里面每个插件的 url 再逐个下载
 *   3. 分享码（base64(JSON)，srcUrl 里塞着整段源码）→ 解出源码直接存
 *   4. 一个 http(s) 网址                    → 下载下来按上面三种猜
 *
 * 识别顺序很关键：先看是不是源码 → 再看是不是 base64 → 最后当 JSON 拆。
 * 任何一步失败都只记一条可读的错误，绝不抛异常（这是 App 稳定性的底线）。
 */
public final class Plugins {

    private static final String BUILTIN_DIR = "plugins";
    private static final int MAX_SOURCE_BYTES = 4 * 1024 * 1024;
    private static final int MAX_PER_INSTALL = 8;

    /** 从插件源码里抠出 platform 字段，顺便当文件名 */
    private static final Pattern P_PLATFORM =
            Pattern.compile("platform\\s*[:=]\\s*[\"']([^\"']{1,50})[\"']");

    private final Api.AssetLoader assets;
    private final File dataDir;

    public Plugins(Api.AssetLoader assets, File dataDir) {
        this.assets = assets;
        this.dataDir = dataDir;
    }

    public String dirPath() {
        return dataDir == null ? "" : onDir().getAbsolutePath();
    }

    private File onDir() { return new File(dataDir, "plugins"); }
    private File offDir() { return new File(dataDir, "plugins-off"); }
    private File stateFile() { return new File(onDir(), "state.json"); }

    /* ------------------------------------------------------------ 查询 */

    /** 列出全部音源：内置的在前，自建的在后 */
    public List<Object> list() {
        List<Object> out = new ArrayList<Object>();
        Set<String> off = disabledBuiltin();
        for (String n : builtinNames()) {
            long size = 0;
            try {
                byte[] d = assets == null ? null : assets.load(BUILTIN_DIR + "/" + n);
                size = d == null ? 0 : d.length;
            } catch (Throwable ignore) { }
            out.add(Json.map("name", n, "builtin", true, "enabled", !off.contains(n),
                    "size", size, "platform", ""));
        }
        for (File f : listJs(onDir())) {
            out.add(Json.map("name", f.getName(), "builtin", false, "enabled", true,
                    "size", f.length(), "platform", ""));
        }
        for (File f : listJs(offDir())) {
            out.add(Json.map("name", f.getName(), "builtin", false, "enabled", false,
                    "size", f.length(), "platform", ""));
        }
        return out;
    }

    /** 取出所有启用中的音源源码，交给 WebView 里的插件运行时加载 */
    public List<Object> loadEnabled() {
        List<Object> out = new ArrayList<Object>();
        Set<String> off = disabledBuiltin();
        for (String n : builtinNames()) {
            if (off.contains(n)) continue;
            byte[] d = assets == null ? null : assets.load(BUILTIN_DIR + "/" + n);
            if (d == null) continue;
            out.add(Json.map("name", n, "code", utf8(d), "builtin", true));
        }
        for (File f : listJs(onDir())) {
            String code = readFile(f);
            if (code == null) continue;
            out.add(Json.map("name", f.getName(), "code", code, "builtin", false));
        }
        return out;
    }

    /* ------------------------------------------------------------ 安装 */

    /**
     * 安装音源。
     * @param url      插件网址 / 订阅网址（与 code 二选一）
     * @param code     直接粘贴的内容（插件源码、分享码、订阅 JSON 都行）
     * @param nameHint 文件名提示（可空，空则用源码里的 platform）
     */
    public Map<String, Object> install(String url, String code, String nameHint, int depth) {
        if (dataDir == null) return err("当前运行环境不支持安装音源");
        if (depth > 3) return err("订阅层级太深，已停止解析");
        List<Object> added = new ArrayList<Object>();
        List<String> errors = new ArrayList<String>();

        if (url != null && !url.trim().isEmpty()) {
            String u = url.trim();
            if (!u.startsWith("http://") && !u.startsWith("https://")) u = "https://" + u;
            Util.Resp r = Util.fetch(u, "GET", null, null, 20);
            if (r == null || r.status < 200 || r.status >= 300 || r.body == null) {
                return err("下载失败：" + (r == null ? "无响应"
                        : (r.statusText.isEmpty() ? ("HTTP " + r.status) : r.statusText)));
            }
            handle(r.body, nameHint, depth, added, errors);
        } else if (code != null && !code.trim().isEmpty()) {
            handle(code.getBytes(java.nio.charset.Charset.forName("UTF-8")), nameHint, depth, added, errors);
        } else {
            return err("请填写音源网址，或粘贴音源内容");
        }

        Map<String, Object> out = Json.map("ok", !added.isEmpty(), "added", added, "errors", errors,
                "msg", summary(added, errors));
        return out;
    }

    private void handle(byte[] data, String hint, int depth,
                        List<Object> added, List<String> errors) {
        if (data == null || data.length == 0) { errors.add("内容为空"); return; }
        if (data.length > MAX_SOURCE_BYTES) { errors.add("内容太大（超过 4MB）"); return; }
        String text = utf8(data);
        String t = text.trim();
        if (t.isEmpty()) { errors.add("内容为空"); return; }

        // 1) 看着就是插件源码
        if (looksLikeJs(t)) { save(t, hint, added, errors); return; }

        // 2) 可能是 base64（MusicFree 的分享码就是 base64 包了一层 JSON）
        String b64 = maybeBase64(t);
        if (b64 != null) {
            try {
                byte[] dec = Util.unbase64(b64);
                if (dec != null && dec.length > 0) {
                    String dt = utf8(dec).trim();
                    if (looksLikeJs(dt)) { save(dt, hint, added, errors); return; }
                    if (dt.startsWith("{") || dt.startsWith("[")) {
                        unpackJson(dt, hint, depth, added, errors);
                        return;
                    }
                }
            } catch (Throwable ignore) { }
        }

        // 3) JSON：订阅文件 / 分享对象
        if (t.startsWith("{") || t.startsWith("[")) {
            unpackJson(t, hint, depth, added, errors);
            return;
        }

        errors.add("没认出这个格式（既不是插件源码，也不是订阅或分享码）");
    }

    /** 从订阅 JSON / 分享对象里把插件挖出来 */
    private void unpackJson(String json, String hint, int depth,
                            List<Object> added, List<String> errors) {
        Object o;
        try { o = Json.parse(json); } catch (Throwable t) { o = null; }
        if (o == null) { errors.add("不是合法的 JSON"); return; }

        List<String> urls = new ArrayList<String>();
        List<String> inline = new ArrayList<String>();
        collect(o, urls, inline, "", 0);

        int n = 0;
        for (String src : inline) {
            if (n++ >= MAX_PER_INSTALL) break;
            save(src, hint, added, errors);
        }
        for (String u : urls) {
            if (n++ >= MAX_PER_INSTALL) break;
            Util.Resp r = Util.fetch(u, "GET", null, null, 20);
            if (r == null || r.status < 200 || r.status >= 300 || r.body == null) {
                errors.add("下载失败：" + u);
                continue;
            }
            handle(r.body, hint, depth + 1, added, errors);
        }
        if (urls.isEmpty() && inline.isEmpty()) errors.add("订阅里没找到可用的插件");
    }

    @SuppressWarnings("unchecked")
    private void collect(Object o, List<String> urls, List<String> inline, String key, int depth) {
        if (o == null || depth > 6) return;
        if (o instanceof Map) {
            for (Object e : ((Map<Object, Object>) o).entrySet()) {
                Map.Entry<Object, Object> en = (Map.Entry<Object, Object>) e;
                collect(en.getValue(), urls, inline, String.valueOf(en.getKey()), depth + 1);
            }
        } else if (o instanceof List) {
            for (Object x : (List<Object>) o) collect(x, urls, inline, key, depth + 1);
        } else if (o instanceof String) {
            String v = ((String) o).trim();
            if (v.isEmpty()) return;
            if (v.startsWith("http://") || v.startsWith("https://")) { urls.add(v); return; }
            if (v.length() > 200 && looksLikeJs(v)) { inline.add(v); return; }
            boolean keyish = key.equalsIgnoreCase("srcUrl") || key.equalsIgnoreCase("source")
                    || key.equalsIgnoreCase("url") || key.equalsIgnoreCase("script")
                    || key.equalsIgnoreCase("code");
            if (keyish && v.length() > 80) {
                String b = maybeBase64(v);
                if (b != null) {
                    try {
                        String d = utf8(Util.unbase64(b)).trim();
                        if (looksLikeJs(d)) inline.add(d);
                    } catch (Throwable ignore) { }
                }
            }
        }
    }

    /** 落盘 */
    private void save(String code, String hint, List<Object> added, List<String> errors) {
        try {
            String platform = extractPlatform(code);
            String base = hint == null ? "" : hint.trim();
            if (base.isEmpty()) base = platform;
            if (base == null || base.trim().isEmpty()) {
                base = "plugin-" + Long.toString(System.currentTimeMillis(), 36);
            }
            base = base.replaceAll("(?i)\\.js$", "");
            String file = Util.sanitizeName(base, "plugin") + ".js";
            File dir = onDir();
            if (!dir.exists() && !dir.mkdirs()) { errors.add("无法创建音源目录"); return; }
            File f = new File(dir, file);
            FileOutputStream os = new FileOutputStream(f);
            os.write(code.getBytes(java.nio.charset.Charset.forName("UTF-8")));
            os.close();
            // 同名的话从「停用」里捞回来，重新安装即视为启用
            File off = new File(offDir(), file);
            if (off.isFile()) off.delete();
            added.add(Json.map("name", file, "platform", platform, "size", f.length()));
        } catch (Throwable t) {
            errors.add("保存失败：" + t.getMessage());
        }
    }

    /* ------------------------------------------------------ 停用 / 删除 */

    public Map<String, Object> remove(String name) {
        if (name == null || name.trim().isEmpty()) return err("没指定要删的音源");
        String n = name.trim();
        if (!n.endsWith(".js")) n = n + ".js";
        if (isBuiltin(n)) {
            // 内置的删不掉（在 APK 里），改成停用
            return toggle(n, false);
        }
        boolean ok = false;
        File a = new File(onDir(), n);
        if (a.isFile()) ok = a.delete();
        File b = new File(offDir(), n);
        if (b.isFile()) ok = b.delete() || ok;
        return Json.map("ok", ok, "msg", ok ? "已删除" : "没找到这个音源");
    }

    public Map<String, Object> toggle(String name, boolean enabled) {
        if (name == null || name.trim().isEmpty()) return err("没指定音源");
        String n = name.trim();
        if (!n.endsWith(".js")) n = n + ".js";
        try {
            if (isBuiltin(n)) {
                Set<String> off = new LinkedHashSet<String>(disabledBuiltin());
                if (enabled) off.remove(n); else off.add(n);
                saveState(off);
                return Json.map("ok", true, "enabled", enabled, "msg", enabled ? "已启用" : "已停用");
            }
            File on = new File(onDir(), n), off = new File(offDir(), n);
            if (enabled) {
                if (!off.isFile()) return err("没找到这个音源");
                if (!onDir().exists() && !onDir().mkdirs()) return err("无法创建音源目录");
                if (!off.renameTo(on)) return err("启用失败");
            } else {
                if (!on.isFile()) return err("没找到这个音源");
                if (!offDir().exists() && !offDir().mkdirs()) return err("无法创建音源目录");
                if (!on.renameTo(off)) return err("停用失败");
            }
            return Json.map("ok", true, "enabled", enabled, "msg", enabled ? "已启用" : "已停用");
        } catch (Throwable t) {
            return err("操作失败：" + t.getMessage());
        }
    }

    /* ------------------------------------------------------------ 工具 */

    private String[] builtinNames() {
        String[] names;
        try {
            names = assets == null ? null : assets.list(BUILTIN_DIR);
        } catch (Throwable t) {
            names = null;
        }
        if (names == null) return new String[0];
        List<String> out = new ArrayList<String>();
        for (String n : names) if (n != null && n.endsWith(".js")) out.add(n);
        String[] arr = out.toArray(new String[out.size()]);
        Arrays.sort(arr);
        return arr;
    }

    private boolean isBuiltin(String name) {
        for (String n : builtinNames()) if (n.equals(name)) return true;
        return false;
    }

    private static List<File> listJs(File dir) {
        List<File> out = new ArrayList<File>();
        File[] fs = dir.listFiles();
        if (fs == null) return out;
        for (File f : fs) if (f.isFile() && f.getName().endsWith(".js")) out.add(f);
        java.util.Collections.sort(out, new java.util.Comparator<File>() {
            @Override public int compare(File a, File b) {
                return a.getName().compareToIgnoreCase(b.getName());
            }
        });
        return out;
    }

    private Set<String> disabledBuiltin() {
        Set<String> out = new LinkedHashSet<String>();
        try {
            File f = stateFile();
            if (!f.isFile()) return out;
            Map<String, Object> m = Json.parseObject(readFile(f));
            List<Object> l = Json.asList(m.get("disabled"));
            for (Object o : l) out.add(String.valueOf(o));
        } catch (Throwable ignore) { }
        return out;
    }

    private void saveState(Set<String> off) {
        try {
            if (dataDir == null) return;
            File dir = onDir();
            if (!dir.exists() && !dir.mkdirs()) return;
            List<Object> l = new ArrayList<Object>(off);
            FileOutputStream os = new FileOutputStream(stateFile());
            os.write(Json.write(Json.map("disabled", l))
                    .getBytes(java.nio.charset.Charset.forName("UTF-8")));
            os.close();
        } catch (Throwable ignore) { }
    }

    private static String summary(List<Object> added, List<String> errors) {
        StringBuilder sb = new StringBuilder();
        if (!added.isEmpty()) {
            sb.append("已添加 ").append(added.size()).append(" 个音源：");
            for (int i = 0; i < added.size(); i++) {
                if (i > 0) sb.append("、");
                sb.append(Json.s(Json.asMap(added.get(i)), "name"));
            }
        }
        if (!errors.isEmpty()) {
            if (sb.length() > 0) sb.append("；");
            sb.append("部分失败：").append(errors.get(0));
        }
        if (sb.length() == 0) sb.append("没有任何变化");
        return sb.toString();
    }

    private static Map<String, Object> err(String msg) {
        return Json.map("ok", false, "msg", msg, "added", new ArrayList<Object>(),
                "errors", new ArrayList<Object>());
    }

    /** 判断一段文本是不是插件源码 */
    private static boolean looksLikeJs(String t) {
        if (t == null || t.length() < 40) return false;
        String head = t.length() > 6000 ? t.substring(0, 6000) : t;
        if (head.contains("module.exports")) return true;
        if (head.contains("exports.platform") || head.contains("exports.default")) return true;
        if (P_PLATFORM.matcher(head).find()
                && (head.contains("function") || head.contains("=>"))) return true;
        return false;
    }

    /** base64 猜测：只由 base64 字符组成、长度够、且能解出东西 */
    private static String maybeBase64(String t) {
        String s = t.replaceAll("\\s+", "");
        if (s.length() < 80 || s.length() > 1024 * 1024) return null;
        if (!s.matches("[A-Za-z0-9+/=_-]+")) return null;
        s = s.replace('-', '+').replace('_', '/');
        int pad = 0;
        for (int i = 0; i < s.length(); i++) if (s.charAt(i) == '=') pad++;
        if (pad > 2) return null;
        while (s.length() % 4 != 0) s = s + "=";
        return s;
    }

    private static String extractPlatform(String code) {
        try {
            Matcher m = P_PLATFORM.matcher(code);
            while (m.find()) {
                String p = m.group(1);
                if (p != null && !p.isEmpty() && !p.startsWith("http")) return p;
            }
        } catch (Throwable ignore) { }
        return "";
    }

    private static String utf8(byte[] d) {
        return new String(d, java.nio.charset.Charset.forName("UTF-8"));
    }

    private static String readFile(File f) {
        InputStream in = null;
        try {
            in = new FileInputStream(f);
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            byte[] buf = new byte[16384];
            int n;
            while ((n = in.read(buf)) > 0) bos.write(buf, 0, n);
            return utf8(bos.toByteArray());
        } catch (Exception e) {
            return null;
        } finally {
            if (in != null) try { in.close(); } catch (Throwable ignore) { }
        }
    }
}
