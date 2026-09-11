package com.dlna.speaker;

import android.content.Context;
import android.os.Build;
import android.os.Looper;
import android.util.Log;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.OutputStreamWriter;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.Date;
import java.util.List;
import java.util.Locale;

/**
 * 全局崩溃兜底 + 崩溃日志
 * ========================
 * Android 与桌面 JVM 的一个关键差异，是「闪退」的常见来源：
 *
 *   - 桌面 JVM：任意线程抛出未捕获的 Throwable，只打印堆栈，进程继续跑。
 *   - Android ：任意线程抛出未捕获的 Throwable，系统会直接杀掉整个进程。
 *
 * 于是同一个漏网的 NoClassDefFoundError / OutOfMemoryError / StackOverflowError，
 * 在桌面上表现为「日志里一行红字」，在手机上就是「App 突然退到桌面」。
 *
 * 这里的策略：
 *   1. 非主线程 → 记录日志后「吞掉」，线程结束但进程存活。该功能报错，App 不闪退。
 *   2. 主线程   → 记录日志后交回系统（主线程崩溃时界面状态已不可信，强留反而更糟）。
 *
 * 日志落在 App 专属外部目录 logs/ 下，可通过界面「运行日志」查看或直接分享出来。
 */
public final class CrashGuard {

    private static final String TAG = "CrashGuard";
    private static final String VERSION = "2.0-standalone";
    private static final int MAX_LOGS = 20;

    private static volatile Context appCtx;
    private static volatile boolean installed = false;

    private CrashGuard() { }

    public static void install(Context ctx) {
        if (installed) return;
        installed = true;
        appCtx = ctx.getApplicationContext();

        final Thread.UncaughtExceptionHandler prev = Thread.getDefaultUncaughtExceptionHandler();
        Thread.setDefaultUncaughtExceptionHandler(new Thread.UncaughtExceptionHandler() {
            @Override public void uncaughtException(Thread t, Throwable e) {
                boolean main = isMainThread(t);
                save(t, e, main);
                if (main) {
                    // 主线程已崩，界面状态不可知：交回系统，避免卡在半死状态
                    if (prev != null) prev.uncaughtException(t, e);
                } else {
                    // 后台线程：吞掉异常，保住进程。下一次请求会重新起线程继续干活。
                    Log.e(TAG, "已拦截后台线程异常 [" + t.getName() + "]: " + e);
                }
            }
        });
    }

    private static boolean isMainThread(Thread t) {
        try {
            Looper main = Looper.getMainLooper();
            return main != null && main.getThread() == t;
        } catch (Throwable ignore) {
            return false;
        }
    }

    /* ------------------------------------------------------------ 落盘 */

    private static File logsDir() {
        Context c = appCtx;
        if (c == null) return null;
        File base = null;
        try { base = c.getExternalFilesDir(null); } catch (Throwable ignore) { }
        if (base == null) base = c.getFilesDir();
        if (base == null) return null;
        File d = new File(base, "logs");
        if (!d.exists() && !d.mkdirs() && !d.isDirectory()) return null;
        return d;
    }

    private static void save(Thread t, Throwable e, boolean main) {
        try {
            File d = logsDir();
            if (d == null) return;
            String stamp = new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(new Date());
            File f = new File(d, "crash-" + stamp + (main ? "-main" : "-bg") + ".txt");

            StringWriter sw = new StringWriter();
            PrintWriter pw = new PrintWriter(sw);
            pw.println("时间   : " + new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(new Date()));
            pw.println("线程   : " + t.getName() + (main ? "  [主线程]" : "  [后台线程]"));
            pw.println("类型   : " + e.getClass().getName());
            pw.println("设备   : " + Build.MANUFACTURER + " " + Build.MODEL
                    + "  Android " + Build.VERSION.RELEASE + "  (API " + Build.VERSION.SDK_INT + ")");
            pw.println("版本   : " + VERSION);
            pw.println();
            e.printStackTrace(pw);
            pw.flush();

            writeFile(f, sw.toString());
            trim(d);
        } catch (Throwable ignore) {
            // 记录崩溃的过程本身绝不能再抛
        }
    }

    /** 记录一条非异常事件（例如渲染进程被回收），便于事后排查 */
    public static void note(String tag, String msg) {
        try {
            File d = logsDir();
            if (d == null) return;
            String stamp = new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(new Date());
            File f = new File(d, "note-" + stamp + ".txt");
            StringBuilder sb = new StringBuilder();
            sb.append("时间   : ")
              .append(new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(new Date())).append("\n");
            sb.append("事件   : ").append(tag).append("\n");
            sb.append("说明   : ").append(msg).append("\n");
            sb.append("设备   : ").append(Build.MANUFACTURER).append(" ").append(Build.MODEL)
              .append("  Android ").append(Build.VERSION.RELEASE)
              .append("  (API ").append(Build.VERSION.SDK_INT).append(")\n");
            sb.append("版本   : ").append(VERSION).append("\n");
            writeFile(f, sb.toString());
            trim(d);
        } catch (Throwable ignore) { }
    }

    private static void writeFile(File f, String text) {
        FileOutputStream fo = null;
        OutputStreamWriter w = null;
        try {
            fo = new FileOutputStream(f);
            w = new OutputStreamWriter(fo, "UTF-8");
            w.write(text);
            w.flush();
        } catch (Throwable ignore) {
        } finally {
            try { if (w != null) w.close(); } catch (Throwable ignore) { }
            try { if (fo != null) fo.close(); } catch (Throwable ignore) { }
        }
    }

    /** 只保留最近 MAX_LOGS 条 */
    private static void trim(File dir) {
        try {
            File[] fs = dir.listFiles();
            if (fs == null || fs.length <= MAX_LOGS) return;
            List<File> list = new ArrayList<File>(Arrays.asList(fs));
            java.util.Collections.sort(list, new Comparator<File>() {
                @Override public int compare(File a, File b) {
                    return a.getName().compareTo(b.getName());
                }
            });
            int remove = list.size() - MAX_LOGS;
            for (int i = 0; i < remove; i++) list.get(i).delete();
        } catch (Throwable ignore) { }
    }

    /* ------------------------------------------------------------ 读取 */

    /** 最近的崩溃记录（新的在前），没有则返回空串 */
    public static String readAll() {
        try {
            File d = logsDir();
            if (d == null) return "";
            File[] fs = d.listFiles();
            if (fs == null || fs.length == 0) return "";
            List<File> list = new ArrayList<File>(Arrays.asList(fs));
            java.util.Collections.sort(list, new Comparator<File>() {
                @Override public int compare(File a, File b) {
                    return b.getName().compareTo(a.getName());
                }
            });
            StringBuilder sb = new StringBuilder();
            int n = 0;
            for (File f : list) {
                if (!f.getName().endsWith(".txt")) continue;
                if (n++ >= 5) break;
                sb.append("──────── ").append(f.getName()).append(" ────────\n");
                sb.append(readFile(f)).append("\n\n");
            }
            return sb.toString();
        } catch (Throwable ignore) {
            return "";
        }
    }

    public static int count() {
        try {
            File d = logsDir();
            if (d == null) return 0;
            File[] fs = d.listFiles();
            if (fs == null) return 0;
            int n = 0;
            for (File f : fs) if (f.getName().endsWith(".txt")) n++;
            return n;
        } catch (Throwable ignore) {
            return 0;
        }
    }

    public static void clear() {
        try {
            File d = logsDir();
            if (d == null) return;
            File[] fs = d.listFiles();
            if (fs != null) for (File f : fs) f.delete();
        } catch (Throwable ignore) { }
    }

    /** 日志目录，方便用户直接去文件管理器里取 */
    public static String dirPath() {
        File d = logsDir();
        return d == null ? "" : d.getAbsolutePath();
    }

    private static String readFile(File f) {
        FileInputStream in = null;
        try {
            in = new FileInputStream(f);
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) bos.write(buf, 0, n);
            return new String(bos.toByteArray(), "UTF-8");
        } catch (Throwable ignore) {
            return "(读取失败)";
        } finally {
            try { if (in != null) in.close(); } catch (Throwable ignore) { }
        }
    }
}
