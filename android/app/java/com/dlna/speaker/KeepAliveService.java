package com.dlna.speaker;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.media.MediaMetadata;
import android.media.session.MediaSession;
import android.media.session.PlaybackState;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.util.Log;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * 前台服务：App 启动即拉起，常驻。
 *
 * 独立运行版里这一层比旧版更重要——本机的 DLNA 控制服务（8765）跑在这个进程里，
 * 音响是「反过来」来这个进程拉音频流的。进程一旦被系统回收，播放就会断，
 * 因此用前台服务把进程钉住，顺便保证手机本机播放退到后台/锁屏也能继续。
 *
 * 同时挂一个 MediaSession：让通知栏和锁屏都有「上一首 / 播放暂停 / 下一首」控制按钮，
 * 按钮统一通过广播转给前端 JS 的 ctl() 执行，保持单一控制入口。
 */
public class KeepAliveService extends Service {

    private static final String CHANNEL = "playback";
    private static final int NOTI_ID = 1001;
    private static final String TAG = "KeepAlive";

    public static final String ACTION_PLAY = "com.dlna.speaker.action.PLAY";
    public static final String ACTION_PAUSE = "com.dlna.speaker.action.PAUSE";
    public static final String ACTION_NEXT = "com.dlna.speaker.action.NEXT";
    public static final String ACTION_PREV = "com.dlna.speaker.action.PREV";

    private static KeepAliveService sInstance;

    /** 媒体控制转发目标：由 MainActivity 注册。Activity 活着时走 JS ctl()（界面即时响应），
     *  若 Activity 已销毁则回退到进程内 HTTP 控制后端，保证锁屏/通知/耳机控制始终可用。 */
    public static final int CTRL_PORT = 8765;
    public interface ControlHandler { void control(String action); }
    private static volatile ControlHandler sControl;
    public static void setControlHandler(ControlHandler h) { sControl = h; }

    private MediaSession mediaSession;
    private BroadcastReceiver ctlReceiver;
    private Handler mainHandler;
    private String curTitle = "SyncDlnaPlay";
    private String curArtist = "正在播放音乐";
    private boolean playing = false;

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onCreate() {
        super.onCreate();
        sInstance = this;
        mainHandler = new Handler(Looper.getMainLooper());
        setupMediaSession();
        registerCtlReceiver();
        goForeground();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        goForeground();
        return START_STICKY;
    }

    private void setupMediaSession() {
        try {
            mediaSession = new MediaSession(this, "SyncDlnaPlay");
            mediaSession.setFlags(MediaSession.FLAG_HANDLES_MEDIA_BUTTONS
                    | MediaSession.FLAG_HANDLES_TRANSPORT_CONTROLS);
            mediaSession.setCallback(new MediaSession.Callback() {
                @Override public void onPlay() { sendCtl(ACTION_PLAY); }
                @Override public void onPause() { sendCtl(ACTION_PAUSE); }
                @Override public void onSkipToNext() { sendCtl(ACTION_NEXT); }
                @Override public void onSkipToPrevious() { sendCtl(ACTION_PREV); }
            });
            mediaSession.setActive(true);
        } catch (Throwable t) {
            Log.e(TAG, "media session setup", t);
        }
    }

    private void registerCtlReceiver() {
        ctlReceiver = new BroadcastReceiver() {
            @Override public void onReceive(Context c, Intent i) {
                String a = i.getAction();
                if (a == null) return;
                if (ACTION_PLAY.equals(a)) sendCtl(ACTION_PLAY);
                else if (ACTION_PAUSE.equals(a)) sendCtl(ACTION_PAUSE);
                else if (ACTION_NEXT.equals(a)) sendCtl(ACTION_NEXT);
                else if (ACTION_PREV.equals(a)) sendCtl(ACTION_PREV);
            }
        };
        IntentFilter f = new IntentFilter();
        f.addAction(ACTION_PLAY); f.addAction(ACTION_PAUSE);
        f.addAction(ACTION_NEXT); f.addAction(ACTION_PREV);
        if (Build.VERSION.SDK_INT >= 33) registerReceiver(ctlReceiver, f, Context.RECEIVER_NOT_EXPORTED);
        else registerReceiver(ctlReceiver, f);
    }

    /** 媒体控制：优先转给 Activity（JS ctl()，界面即时响应），否则回退本机 HTTP 控制 */
    private void ctrl(String action) {
        if (sControl != null) { sControl.control(action); return; }
        httpControl(action);
    }

    /** 兼容旧调用点（MediaSession 回调 / 广播接收器）：
     *  把完整 Intent action 常量翻译成 ctl() / player.control 认的短命令，
     *  否则前端只认 play/pause/next/prev，锁屏按钮全部静默无反应。 */
    private void sendCtl(String action) { ctrl(shortAction(action)); }

    /** Intent action 常量 -> 统一短命令（play/pause/next/prev） */
    private static String shortAction(String action) {
        if (ACTION_PLAY.equals(action)) return "play";
        if (ACTION_PAUSE.equals(action)) return "pause";
        if (ACTION_NEXT.equals(action)) return "next";
        if (ACTION_PREV.equals(action)) return "prev";
        return action;
    }

    /** 经由进程内 HTTP 后端直接下发控制（Activity 不在时也能用：锁屏/通知/耳机） */
    public static void httpControl(String action) {
        try {
            final String body = "{\"action\":\"" + action + "\"}";
            final byte[] data = body.getBytes("UTF-8");
            new Thread(new Runnable() {
                @Override public void run() {
                    HttpURLConnection c = null;
                    try {
                        URL u = new URL("http://127.0.0.1:" + CTRL_PORT + "/api/control");
                        c = (HttpURLConnection) u.openConnection();
                        c.setRequestMethod("POST");
                        c.setConnectTimeout(3000);
                        c.setReadTimeout(5000);
                        c.setDoOutput(true);
                        c.setRequestProperty("Content-Type", "application/json");
                        c.setFixedLengthStreamingMode(data.length);
                        OutputStream os = c.getOutputStream();
                        os.write(data);
                        os.flush();
                        os.close();
                        c.getResponseCode();
                    } catch (Throwable ignore) {
                    } finally {
                        if (c != null) try { c.disconnect(); } catch (Throwable ignore) { }
                    }
                }
            }).start();
        } catch (Throwable ignore) { }
    }

    private void goForeground() {
        try {
            NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            if (Build.VERSION.SDK_INT >= 26 && nm != null) {
                NotificationChannel ch = new NotificationChannel(
                        CHANNEL, "播放后台服务", NotificationManager.IMPORTANCE_LOW);
                ch.setShowBadge(false);
                ch.setSound(null, null);
                nm.createNotificationChannel(ch);
            }

            Intent open = new Intent(this, MainActivity.class);
            open.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
            PendingIntent pi = PendingIntent.getActivity(this, 0, open, PendingIntent.FLAG_IMMUTABLE);

            // 媒体控制按钮：通知栏点按 / 锁屏 / 蓝牙耳机都在这里触发
            PendingIntent prevPi = PendingIntent.getBroadcast(this, 1,
                    new Intent(ACTION_PREV).setPackage(getPackageName()), PendingIntent.FLAG_IMMUTABLE);
            PendingIntent playPi = PendingIntent.getBroadcast(this, 2,
                    new Intent(playing ? ACTION_PAUSE : ACTION_PLAY).setPackage(getPackageName()), PendingIntent.FLAG_IMMUTABLE);
            PendingIntent nextPi = PendingIntent.getBroadcast(this, 3,
                    new Intent(ACTION_NEXT).setPackage(getPackageName()), PendingIntent.FLAG_IMMUTABLE);

            Notification.Builder b;
            if (Build.VERSION.SDK_INT >= 26) b = new Notification.Builder(this, CHANNEL);
            else b = new Notification.Builder(this);
            b.setContentTitle(curTitle)
             .setContentText(curArtist)
             .setSmallIcon(R.drawable.ic_stat)
             .setContentIntent(pi)
             .setOngoing(true)
             .addAction(android.R.drawable.ic_media_previous, "上一首", prevPi)
             .addAction(playing ? android.R.drawable.ic_media_pause : android.R.drawable.ic_media_play,
                        playing ? "暂停" : "播放", playPi)
             .addAction(android.R.drawable.ic_media_next, "下一首", nextPi);
            if (mediaSession != null && Build.VERSION.SDK_INT >= 21) {
                b.setStyle(new Notification.MediaStyle()
                        .setMediaSession(mediaSession.getSessionToken()));
            }
            startForeground(NOTI_ID, b.build());
        } catch (Throwable ignored) {
        }
    }

    /** 由 JS 桥调用：刷新锁屏 / 通知上的歌名与播放状态（在主线程重建通知） */
    public static void updateMedia(String title, String artist, boolean isPlaying) {
        if (sInstance == null) return;
        try {
            sInstance.curTitle = (title != null && !title.isEmpty()) ? title : "SyncDlnaPlay";
            sInstance.curArtist = (artist != null && !artist.isEmpty()) ? artist : "正在播放音乐";
            sInstance.playing = isPlaying;
            sInstance.pushPlaybackState();
            // 通知栏文字/按钮会随播放状态变化，必须回到主线程重建
            sInstance.mainHandler.post(new Runnable() {
                @Override public void run() { sInstance.goForeground(); }
            });
        } catch (Throwable ignore) { }
    }

    /** 把播放状态与元数据同步给 MediaSession（锁屏控制依赖它） */
    private void pushPlaybackState() {
        if (mediaSession == null) return;
        try {
            long actions = PlaybackState.ACTION_PLAY_PAUSE
                    | PlaybackState.ACTION_SKIP_TO_NEXT
                    | PlaybackState.ACTION_SKIP_TO_PREVIOUS;
            if (!playing) actions |= PlaybackState.ACTION_PLAY;
            PlaybackState st = new PlaybackState.Builder()
                    .setActions(actions)
                    .setState(playing ? PlaybackState.STATE_PLAYING : PlaybackState.STATE_PAUSED, 0, 1f)
                    .build();
            mediaSession.setPlaybackState(st);
            MediaMetadata md = new MediaMetadata.Builder()
                    .putString(MediaMetadata.METADATA_KEY_TITLE, curTitle)
                    .putString(MediaMetadata.METADATA_KEY_ARTIST, curArtist)
                    .build();
            mediaSession.setMetadata(md);
        } catch (Throwable ignore) { }
    }

    @Override
    public void onDestroy() {
        try { if (ctlReceiver != null) unregisterReceiver(ctlReceiver); } catch (Throwable ignore) { }
        try {
            if (mediaSession != null) { mediaSession.setActive(false); mediaSession.release(); }
        } catch (Throwable ignore) { }
        mediaSession = null;
        sInstance = null;
        super.onDestroy();
    }
}
