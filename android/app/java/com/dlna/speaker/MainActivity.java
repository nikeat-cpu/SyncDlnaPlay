package com.dlna.speaker;

import android.Manifest;
import android.app.Activity;
import android.app.UiModeManager;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.ActivityInfo;
import android.content.pm.PackageManager;
import android.content.res.Configuration;
import android.net.Uri;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.util.Base64;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.view.inputmethod.InputMethodManager;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.Toast;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.List;

/**
 * 音响管家 —— 独立运行版
 * ======================
 * 与旧版「手机客户端」最大的区别：整个后端（DLNA 控制 / 曲库 / 在线音乐代理 / 下载）
 * 都跑在手机本机，不再依赖 iStoreOS 上的服务，换任何网络都能独立使用。
 *
 * 进程内结构：
 *   HttpSrv(8765) + Api  <-- WebView 里的 SPA 与插件运行时都通过 http://127.0.0.1:8765 访问
 *   同时 8765 也对外监听，DLNA 音响才能来拉本地音乐 / 代理后的在线流。
 */
public class MainActivity extends Activity {

    public static final int PORT = 8765;
    private static final int REQ_FILE = 2001;
    private static final int REQ_PERM = 1001;
    private static final int REQ_TREE = 2002;

    private WebView web;
    private HttpSrv server;
    private Api api;
    private ValueCallback<Uri[]> fileCallback;
    private WifiManager.MulticastLock mcLock;
    private FrameLayout root;
    private Storage storage;
    private MusicDirs musicDirs;
    /** SAF 目录选择器的用途：music = 加进曲库，download = 设为下载目录 */
    private volatile String pendingTreeUse = "music";

    /* ------------------------------------------------------ 电视 / 遥控器 */
    /**
     * 前端（tv.js）是否接管按键：
     *   0 = 不接管，一切交回系统
     *   1 = 电视模式，方向键 / OK / 媒体键全部转发给前端焦点引擎
     *   2 = 正在输入文字，只有「返回」转发，其余留给系统输入法
     * 由前端通过 setKeySink() 上报，避免两边同时处理同一次按键。
     */
    private volatile int keySink = 0;
    /** 已被前端消费的按键，抬起事件也要一起吞掉，否则 WebView 会再触发一次 */
    private String heldTvKey = null;
    private Boolean tvDevice = null;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        // 越早安装越好：之后再有任何后台线程抛出异常，都不该让 App 整个闪退
        CrashGuard.install(this);

        acquireMulticastLock();
        startBackend();

        root = new FrameLayout(this);
        setContentView(root);
        buildWebView();

        requestPermissionsIfNeeded();
        startKeepAlive();
        // 媒体控制统一入口：锁屏/通知/耳机按键由 KeepAliveService 收下后转回这里，
        // 直接驱动前端 ctl()；Activity 已销毁时由服务回退到本机 HTTP 控制。
        KeepAliveService.setControlHandler(new KeepAliveService.ControlHandler() {
            @Override public void control(String a) {
                if (web != null) runJs("ctl('" + a + "')");
                else KeepAliveService.httpControl(a);
            }
        });
    }

    /** 建 WebView 并挂进 root。渲染进程崩溃后也走这里重建，所以单独抽出来。 */
    private void buildWebView() {
        web = new WebView(this);
        root.addView(web, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        WebSettings ws = web.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setAllowFileAccess(true);
        ws.setAllowContentAccess(true);
        ws.setAllowFileAccessFromFileURLs(true);
        ws.setAllowUniversalAccessFromFileURLs(true);
        ws.setMediaPlaybackRequiresUserGesture(false);
        ws.setLoadWithOverviewMode(true);
        ws.setUseWideViewPort(true);
        ws.setCacheMode(WebSettings.LOAD_NO_CACHE);
        if (Build.VERSION.SDK_INT >= 21) {
            ws.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        }

        // 去掉「网页感」：不要长按选中/放大镜、不要滚动条、不要边缘回弹光效，
        // 字体也不随系统字号缩放（否则 5 档字体会把布局顶坏）。
        web.setLongClickable(false);
        web.setHapticFeedbackEnabled(false);
        web.setVerticalScrollBarEnabled(false);
        web.setHorizontalScrollBarEnabled(false);
        web.setOverScrollMode(View.OVER_SCROLL_NEVER);
        ws.setTextZoom(100);
        ws.setSupportZoom(false);
        ws.setBuiltInZoomControls(false);

        // API 26 起渲染进程独立，崩溃时要自己接管，否则系统会连 App 一起杀掉
        if (Build.VERSION.SDK_INT >= 26) {
            web.setWebViewClient(new SafeWebViewClient(new SafeWebViewClient.Listener() {
                @Override public void onRendererGone(String reason) { handleRendererGone(reason); }
            }));
        } else {
            web.setWebViewClient(new WebViewClient());
        }

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView v, ValueCallback<Uri[]> cb,
                                             FileChooserParams params) {
                fileCallback = cb;
                try {
                    Intent it = new Intent(Intent.ACTION_GET_CONTENT);
                    it.addCategory(Intent.CATEGORY_OPENABLE);
                    it.setType("*/*");
                    startActivityForResult(Intent.createChooser(it, "选择插件文件"), REQ_FILE);
                    return true;
                } catch (Exception e) {
                    fileCallback = null;
                    return false;
                }
            }
        });
        web.addJavascriptInterface(new Bridge(), "Android");
        web.setBackgroundColor(0xFF0E0E12);
        web.loadUrl("file:///android_asset/www/index.html");
    }

    /**
     * WebView 渲染进程崩溃/被回收。
     * 进程已经保住了（SafeWebViewClient 返回 true），这里负责把界面重新建起来。
     */
    private void handleRendererGone(String reason) {
        CrashGuard.note("WebView", reason);
        final WebView dead = web;
        web = null;
        if (dead != null) {
            try {
                ViewGroup parent = (ViewGroup) dead.getParent();
                if (parent != null) parent.removeView(dead);
            } catch (Throwable ignore) { }
            try { dead.destroy(); } catch (Throwable ignore) { }
        }
        try { root.removeAllViews(); } catch (Throwable ignore) { }
        try {
            buildWebView();
            Toast.makeText(this, "页面已自动恢复（" + reason + "）", Toast.LENGTH_LONG).show();
        } catch (Throwable t) {
            CrashGuard.note("WebView", "重建失败: " + t);
        }
    }

    /**
     * SSDP 靠组播收发 M-SEARCH。Android 的 WiFi 省电策略默认会过滤组播包，
     * 不持有 MulticastLock 时经常「扫不到任何音响」，因此开机即持有。
     */
    private void acquireMulticastLock() {
        try {
            WifiManager wm = (WifiManager) getApplicationContext()
                    .getSystemService(android.content.Context.WIFI_SERVICE);
            if (wm == null) return;
            mcLock = wm.createMulticastLock("dlna-ssdp");
            mcLock.setReferenceCounted(true);
            mcLock.acquire();
        } catch (Exception ignore) { /* 无 WiFi 时忽略 */ }
    }

    /** 启动进程内的 HTTP 服务 + 曲库扫描 */
    private void startBackend() {
        storage = new AndroidStorage(this);
        musicDirs = new MusicDirs(this);
        api = new Api(PORT, new AssetLoader(), storage, musicDirs);
        // 用户自建音源（MusicFree 插件）存放位置
        try { api.setDataDir(getFilesDir()); } catch (Throwable ignore) { }
        api.library().setScanner(new MediaScanner(this, musicDirs), new MediaScanner.Opener(this, musicDirs));
        api.library().scanAsync();
        api.startScheduler();
        server = new HttpSrv(PORT, api);
        try {
            server.start();
        } catch (Exception e) {
            Toast.makeText(this, "本地服务启动失败: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    /* ------------------------------------------------------------ 权限 */

    private static final String PERM_NOTIF = "android.permission.POST_NOTIFICATIONS";

    private void requestPermissionsIfNeeded() {
        List<String> need = new ArrayList<String>();
        if (Build.VERSION.SDK_INT >= 33) {
            if (checkSelfPermission(Manifest.permission.READ_MEDIA_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                need.add(Manifest.permission.READ_MEDIA_AUDIO);
            }
            if (checkSelfPermission(PERM_NOTIF) != PackageManager.PERMISSION_GRANTED) {
                need.add(PERM_NOTIF);
            }
        } else if (Build.VERSION.SDK_INT >= 23) {
            if (checkSelfPermission(Manifest.permission.READ_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
                need.add(Manifest.permission.READ_EXTERNAL_STORAGE);
            }
        }
        if (!need.isEmpty()) {
            requestPermissions(need.toArray(new String[0]), REQ_PERM);
        }
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] results) {
        super.onRequestPermissionsResult(code, perms, results);
        if (code != REQ_PERM) return;
        boolean mediaGranted = false;
        boolean notifGranted = false;
        for (int i = 0; i < perms.length; i++) {
            if (perms[i] != null && perms[i].contains("NOTIFICATION")) {
                notifGranted = results[i] == PackageManager.PERMISSION_GRANTED;
            } else if (results[i] == PackageManager.PERMISSION_GRANTED) {
                mediaGranted = true;
            }
        }
        if (mediaGranted) {
            api.library().clear();
            api.library().scanAsync();
        }
        if (notifGranted) startKeepAlive();
        runJs("window.__onPermissionChanged && window.__onPermissionChanged()");
    }

    private void startKeepAlive() {
        try {
            if (Build.VERSION.SDK_INT >= 33
                    && checkSelfPermission(PERM_NOTIF) != PackageManager.PERMISSION_GRANTED) {
                return;             // Android 13+ 没通知权限就不上前台服务，避免异常
            }
            Intent it = new Intent(this, KeepAliveService.class);
            if (Build.VERSION.SDK_INT >= 26) startForegroundService(it);
            else startService(it);
        } catch (Exception ignore) { }
    }

    /* ------------------------------------------------------- 文件选择回调 */

    /**
     * 打开系统目录选择器（SAF）。
     * 这是 Android 上唯一零依赖、能跨 ROM 拿到「任意目录」的官方通道 ——
     * 本地文件夹、SD 卡、U 盘，以及系统「文件」App 里挂载好的网络位置都能选。
     */
    private void openTreePicker() {
        runOnUiThread(new Runnable() {
            @Override public void run() {
                try {
                    Intent it = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
                    it.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                            | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                            | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
                            | Intent.FLAG_GRANT_PREFIX_URI_PERMISSION);
                    startActivityForResult(it, REQ_TREE);
                } catch (Throwable e) {
                    Toast.makeText(MainActivity.this,
                            "无法打开目录选择器：" + e.getMessage(), Toast.LENGTH_LONG).show();
                }
            }
        });
    }

    protected void onActivityResult(int req, int res, Intent data) {
        if (req == REQ_FILE) {
            if (fileCallback != null) {
                Uri[] uris = null;
                if (res == RESULT_OK && data != null && data.getData() != null) {
                    uris = new Uri[]{data.getData()};
                }
                fileCallback.onReceiveValue(uris);
                fileCallback = null;
            }
            return;
        }
        if (req == REQ_TREE) {
            if (res == RESULT_OK && data != null && data.getData() != null) {
                Uri tree = data.getData();
                String use = pendingTreeUse;
                // 授权必须持久化，否则重启后目录就失效了
                try {
                    getContentResolver().takePersistableUriPermission(tree,
                            Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
                } catch (Throwable ignore) { }
                String name = MusicDirs.guessSafName(tree);
                if ("download".equals(use)) {
                    if (storage != null) storage.setCustom(tree.toString(), name);
                    runJs("window.__onStorageChanged && window.__onStorageChanged()");
                    Toast.makeText(this, "下载目录已设为：" + name, Toast.LENGTH_SHORT).show();
                } else {
                    if (musicDirs != null) musicDirs.addSaf(tree, name);
                    if (api != null) api.library().scanAsync();
                    runJs("window.__onMusicDirsChanged && window.__onMusicDirsChanged()");
                    Toast.makeText(this, "已添加音乐目录：" + name, Toast.LENGTH_SHORT).show();
                }
            }
            return;
        }
        super.onActivityResult(req, res, data);
    }

    /* ------------------------------------------------- 电视 / 遥控器按键 */

    /** 是否运行在电视 / 机顶盒上（Android TV，或系统 UI 模式为电视） */
    boolean isTvDevice() {
        if (tvDevice != null) return tvDevice;
        boolean tv = false;
        try {
            PackageManager pm = getPackageManager();
            tv = pm.hasSystemFeature("android.software.leanback")
                    || pm.hasSystemFeature("android.hardware.type.television");
        } catch (Throwable ignore) { }
        if (!tv) {
            try {
                UiModeManager um = (UiModeManager) getSystemService(Context.UI_MODE_SERVICE);
                if (um != null && um.getCurrentModeType() == Configuration.UI_MODE_TYPE_TELEVISION) {
                    tv = true;
                }
            } catch (Throwable ignore) { }
        }
        tvDevice = tv;
        return tv;
    }

    /** 遥控器按键 → 前端约定的动作名；不是遥控键则返回 null */
    private static String tvKeyOf(int code) {
        switch (code) {
            case KeyEvent.KEYCODE_DPAD_UP:        return "up";
            case KeyEvent.KEYCODE_DPAD_DOWN:      return "down";
            case KeyEvent.KEYCODE_DPAD_LEFT:      return "left";
            case KeyEvent.KEYCODE_DPAD_RIGHT:     return "right";
            case KeyEvent.KEYCODE_DPAD_CENTER:
            case KeyEvent.KEYCODE_ENTER:
            case KeyEvent.KEYCODE_NUMPAD_ENTER:
            case KeyEvent.KEYCODE_BUTTON_A:       return "ok";
            case KeyEvent.KEYCODE_BACK:           return "back";
            case KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE:
            case KeyEvent.KEYCODE_HEADSETHOOK:
            case KeyEvent.KEYCODE_MEDIA_PLAY:
            case KeyEvent.KEYCODE_MEDIA_PAUSE:    return "togglePlay";
            case KeyEvent.KEYCODE_MEDIA_NEXT:     return "next";
            case KeyEvent.KEYCODE_MEDIA_PREVIOUS: return "prev";
            case KeyEvent.KEYCODE_MEDIA_STOP:     return "stop";
            case KeyEvent.KEYCODE_CHANNEL_UP:     return "volUp";
            case KeyEvent.KEYCODE_CHANNEL_DOWN:   return "volDown";
            default: return null;
        }
    }

    /**
     * 遥控器按键总入口：Java 只做「翻译 + 转发」，具体怎么移动由前端焦点引擎决定。
     * keySink=0（未启用电视模式）时这里完全不介入，所以手机/桌面行为一字不变。
     */
    @Override
    public boolean dispatchKeyEvent(KeyEvent event) {
        String k = tvKeyOf(event.getKeyCode());
        if (k == null || keySink == 0) return super.dispatchKeyEvent(event);

        // 返回键沿用原有链路（onKeyDown / onBackPressed → window.__onBack）
        if ("back".equals(k)) return super.dispatchKeyEvent(event);

        // 正在输入文字：方向键与 OK 必须交回系统输入法，否则打不了字
        if (keySink == 2) return super.dispatchKeyEvent(event);

        int act = event.getAction();
        if (act == KeyEvent.ACTION_DOWN || act == KeyEvent.ACTION_MULTIPLE) {
            runJs("window.__tvKey && window.__tvKey('" + k + "')");
            heldTvKey = k;      // 长按的重复事件同样是 ACTION_DOWN，可连续移动 / 连续调值
            return true;
        }
        if (act == KeyEvent.ACTION_UP) {
            if (k.equals(heldTvKey)) { heldTvKey = null; return true; }
        }
        return super.dispatchKeyEvent(event);
    }

    /* ------------------------------------------------------------ 返回键 */

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK) {
            handleBack();
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    /** Android 13+ 手势返回不再触发 onKeyDown，这里兜住传统返回键 */
    @Override
    public void onBackPressed() {
        handleBack();
    }

    private void handleBack() {
        // 电视模式下正在打字：先收键盘，不要一按返回就退出 App
        if (keySink == 2) {
            runJs("window.__tvKey && window.__tvKey('back')");
            return;
        }
        runJs("window.__onBack ? window.__onBack() : 'exit'", true);
    }

    private void runJs(String js) { runJs(js, false); }

    private void runJs(final String js, final boolean checkBack) {
        if (web == null) return;
        web.post(new Runnable() {
            @Override public void run() {
                if (checkBack) {
                    web.evaluateJavascript(
                            "(function(){ try { return window.__onBack ? window.__onBack() : 'exit'; } "
                                    + "catch(e){ return 'exit'; } })()",
                            new ValueCallback<String>() {
                                @Override public void onReceiveValue(String value) {
                                    if (value == null || value.contains("exit")) finish();
                                }
                            });
                } else {
                    web.evaluateJavascript(js, null);
                }
            }
        });
    }

    @Override
    protected void onDestroy() {
        KeepAliveService.setControlHandler(null);
        if (server != null) server.stop();
        if (mcLock != null) {
            try { if (mcLock.isHeld()) mcLock.release(); } catch (Exception ignore) { }
            mcLock = null;
        }
        super.onDestroy();
    }

    /* ------------------------------------------------------- 静态资源读取 */

    class AssetLoader implements Api.AssetLoader {
        @Override public byte[] load(String path) {
            try {
                InputStream in = getAssets().open(path);
                ByteArrayOutputStream bos = new ByteArrayOutputStream();
                byte[] buf = new byte[16384];
                int n;
                while ((n = in.read(buf)) > 0) bos.write(buf, 0, n);
                in.close();
                return bos.toByteArray();
            } catch (Exception e) {
                return null;
            }
        }

        @Override public String mimeType(String path) {
            return Util.mimeOf(path);
        }

        @Override public String[] list(String dir) {
            try { return getAssets().list(dir); } catch (Throwable t) { return new String[0]; }
        }
    }

    private static String readFile(File f) {
        try {
            InputStream in = new java.io.FileInputStream(f);
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            byte[] buf = new byte[16384];
            int n;
            while ((n = in.read(buf)) > 0) bos.write(buf, 0, n);
            in.close();
            return new String(bos.toByteArray(), "UTF-8");
        } catch (Exception e) {
            return null;
        }
    }

    /* ----------------------------------------------------------- JS 桥 */

    class Bridge {

        /** 内置服务地址：前端与插件运行时都靠它 */
        @JavascriptInterface
        public String getBaseUrl() {
            return "http://127.0.0.1:" + PORT;
        }

        @JavascriptInterface
        public String getVersion() {
            try {
                return getPackageManager().getPackageInfo(getPackageName(), 0).versionName + "-standalone";
            } catch (Throwable t) {
                return "2.22-standalone";
            }
        }

        /* ------------------------------------------------ 电视 / 遥控器桥 */

        /** 电视环境判定：前端据此自动开启电视模式 */
        @JavascriptInterface
        public String isTv() {
            return isTvDevice() ? "1" : "0";
        }

        /**
         * 上报按键接管级别：0=不接管 1=电视模式全接管 2=正在输入（只接管返回）。
         * 与前端 tv.js 一一对应，保证同一次按键只被一边处理。
         */
        @JavascriptInterface
        public void setKeySink(int mode) {
            keySink = (mode < 0 || mode > 2) ? 0 : mode;
            heldTvKey = null;
        }

        /** 唤起系统输入法（电视上输入框聚焦不会自动弹键盘） */
        @JavascriptInterface
        public void showKeyboard() {
            runOnUiThread(new Runnable() {
                @Override public void run() {
                    try {
                        if (web == null) return;
                        web.requestFocus();
                        InputMethodManager imm = (InputMethodManager)
                                getSystemService(Context.INPUT_METHOD_SERVICE);
                        if (imm != null) imm.showSoftInput(web, InputMethodManager.SHOW_IMPLICIT);
                    } catch (Throwable ignore) { }
                }
            });
        }

        /** 收起输入法 */
        @JavascriptInterface
        public void hideKeyboard() {
            runOnUiThread(new Runnable() {
                @Override public void run() {
                    try {
                        if (web == null) return;
                        InputMethodManager imm = (InputMethodManager)
                                getSystemService(Context.INPUT_METHOD_SERVICE);
                        if (imm != null) imm.hideSoftInputFromWindow(web.getWindowToken(), 0);
                    } catch (Throwable ignore) { }
                }
            });
        }

        /** 最近的崩溃记录（新的在前），供界面「运行日志」展示 */
        @JavascriptInterface
        public String getCrashLogs() {
            try { return CrashGuard.readAll(); } catch (Throwable ignore) { return ""; }
        }

        @JavascriptInterface
        public int getCrashCount() {
            try { return CrashGuard.count(); } catch (Throwable ignore) { return 0; }
        }

        @JavascriptInterface
        public String getCrashLogDir() {
            try { return CrashGuard.dirPath(); } catch (Throwable ignore) { return ""; }
        }

        @JavascriptInterface
        public void clearCrashLogs() {
            try { CrashGuard.clear(); } catch (Throwable ignore) { }
        }

        /** 下发随 App 打包的 MusicFree 插件源码 */
        @JavascriptInterface
        public String getPlugins() {
            List<Object> out = new ArrayList<Object>();
            try {
                String[] names = getAssets().list("plugins");
                if (names != null) {
                    for (String n : names) {
                        if (!n.endsWith(".js")) continue;
                        byte[] data = new AssetLoader().load("plugins/" + n);
                        if (data == null) continue;
                        out.add(Json.map("name", n, "code", new String(data, "UTF-8")));
                    }
                }
            } catch (Exception ignore) { }
            return Json.write(out);
        }

        /** 用户自己导入的插件（存在应用私有目录，优先于内置插件同名项） */
        @JavascriptInterface
        public String getUserPlugins() {
            List<Object> out = new ArrayList<Object>();
            File dir = new File(getFilesDir(), "plugins");
            File[] files = dir.listFiles();
            if (files != null) {
                for (File f : files) {
                    if (!f.getName().endsWith(".js")) continue;
                    String code = readFile(f);
                    if (code == null) continue;
                    out.add(Json.map("name", f.getName(), "code", code));
                }
            }
            return Json.write(out);
        }

        /** 保存用户选择的插件文件（前端把文件读成 base64 传进来） */
        @JavascriptInterface
        public String saveUserPlugin(String name, String base64) {
            try {
                File dir = new File(getFilesDir(), "plugins");
                if (!dir.exists() && !dir.mkdirs()) return Json.write(Json.map("ok", false, "msg", "无法创建目录"));
                byte[] data = Base64.decode(base64, Base64.DEFAULT);
                File f = new File(dir, Util.sanitizeName(name, "plugin.js"));
                java.io.FileOutputStream os = new java.io.FileOutputStream(f);
                os.write(data);
                os.close();
                return Json.write(Json.map("ok", true, "path", f.getAbsolutePath(), "size", data.length));
            } catch (Exception e) {
                return Json.write(Json.map("ok", false, "msg", String.valueOf(e)));
            }
        }

        @JavascriptInterface
        public String getDownloadsDir() {
            return storage == null ? "" : storage.describe();
        }

        @JavascriptInterface
        public String getLibraryInfo() {
            return Json.write(Json.map(
                    "count", api.library().count(),
                    "scanning", api.library().isScanning(),
                    "truncated", api.library().isTruncated(),
                    "error", api.library().getLastError(),
                    "last_scan", api.library().getLastScan()
            ));
        }

        @JavascriptInterface
        public void rescanLibrary() {
            api.library().clear();
            api.library().scanAsync();
        }

        @JavascriptInterface
        public void requestAudioPermission() {
            runOnUiThread(new Runnable() {
                @Override public void run() { requestPermissionsIfNeeded(); }
            });
        }

        @JavascriptInterface
        public String getPermissionState() {
            String perm = Build.VERSION.SDK_INT >= 33
                    ? Manifest.permission.READ_MEDIA_AUDIO
                    : Manifest.permission.READ_EXTERNAL_STORAGE;
            if (Build.VERSION.SDK_INT < 23) return "granted";
            return checkSelfPermission(perm) == PackageManager.PERMISSION_GRANTED ? "granted" : "denied";
        }

        @JavascriptInterface
        public void startKeepAlive() {
            runOnUiThread(new Runnable() {
                @Override public void run() { MainActivity.this.startKeepAlive(); }
            });
        }

        /** 前端把当前曲目与播放状态推过来，刷新锁屏/通知栏媒体控制 */
        @JavascriptInterface
        public void updateMedia(String title, String artist, boolean playing) {
            try {
                KeepAliveService.updateMedia(title, artist, playing);
            } catch (Throwable ignore) { }
        }

        /** 控制屏幕方向：'land'=锁定横屏，'port'=锁定竖屏，'unlock'=跟随传感器 */
        @JavascriptInterface
        public void setOrientation(String mode) {
            final int ori;
            if ("land".equals(mode)) ori = ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE;
            else if ("port".equals(mode)) ori = ActivityInfo.SCREEN_ORIENTATION_PORTRAIT;
            else ori = ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED;
            runOnUiThread(new Runnable() {
                @Override public void run() {
                    try { MainActivity.this.setRequestedOrientation(ori); } catch (Throwable ignore) { }
                }
            });
        }

        @JavascriptInterface
        public void exitApp() {
            runOnUiThread(new Runnable() {
                @Override public void run() { finish(); }
            });
        }

        /** 打开下载目录（优先定位到系统「文件」里的音频根，失败退回文件夹 Intent） */
        @JavascriptInterface
        public void openDownloads() {
            final String desc = storage == null ? "下载目录" : storage.describe();
            runOnUiThread(new Runnable() {
                @Override public void run() {
                    try {
                        Intent it = new Intent(Intent.ACTION_VIEW);
                        it.setDataAndType(
                                Uri.parse("content://com.android.externalstorage.documents/root/primary"),
                                "vnd.android.document/root");
                        it.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
                        startActivity(it);
                    } catch (Throwable e) {
                        try {
                            Intent it2 = new Intent(Intent.ACTION_VIEW);
                            it2.setDataAndType(Uri.fromFile(storage.defaultDir()), "resource/folder");
                            it2.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                            startActivity(it2);
                        } catch (Throwable e2) {
                            Toast.makeText(MainActivity.this, "下载目录：" + desc, Toast.LENGTH_LONG).show();
                        }
                    }
                }
            });
        }

        /* ------------------------------------------------ 下载目录 / 曲库目录 */

        /** 下载目录现状 */
        @JavascriptInterface
        public String getStorageInfo() {
            if (storage == null) return "{}";
            return Json.write(Json.map(
                    "dir", storage.describe(),
                    "custom", storage.isCustom(),
                    "name", storage.customName(),
                    "subdir", storage.subDir(),
                    "path", storage.defaultDir().getAbsolutePath()
            ));
        }

        /** 用系统目录选择器指定下载目录 */
        @JavascriptInterface
        public void pickDownloadFolder() {
            pendingTreeUse = "download";
            openTreePicker();
        }

        /** 用系统目录选择器把某个目录加进曲库（本地 / SD 卡 / 系统已挂载的网络位置） */
        @JavascriptInterface
        public void pickMusicFolder() {
            pendingTreeUse = "music";
            openTreePicker();
        }

        /** 恢复默认的公共音乐目录 */
        @JavascriptInterface
        public void resetDownloadFolder() {
            if (storage != null) storage.clearCustom();
            runJs("window.__onStorageChanged && window.__onStorageChanged()");
        }

        /** 已添加的音乐目录清单 */
        @JavascriptInterface
        public String getMusicDirs() {
            List<Object> out = new ArrayList<Object>();
            if (musicDirs != null) {
                for (MusicDirs.Entry e : musicDirs.list()) {
                    out.add(Json.map(
                            "id", e.id,
                            "name", e.displayName(),
                            "type", e.type,
                            "addr", e.addr(),
                            "count", api.library().countBySrc(e.id)
                    ));
                }
            }
            return Json.write(out);
        }

        @JavascriptInterface
        public void removeMusicDir(String id) {
            if (musicDirs != null) musicDirs.remove(id);
            api.library().scanAsync();
        }

        @JavascriptInterface
        public void toast(String msg) {
            final String m = msg;
            runOnUiThread(new Runnable() {
                @Override public void run() {
                    Toast.makeText(MainActivity.this, m, Toast.LENGTH_SHORT).show();
                }
            });
        }
    }
}
