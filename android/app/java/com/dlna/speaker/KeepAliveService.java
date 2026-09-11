package com.dlna.speaker;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;

/**
 * 前台服务：App 启动即拉起，常驻。
 *
 * 独立运行版里这一层比旧版更重要——本机的 DLNA 控制服务（8765）跑在这个进程里，
 * 音响是「反过来」来这个进程拉音频流的。进程一旦被系统回收，播放就会断，
 * 因此用前台服务把进程钉住，顺便保证手机本机播放退到后台/锁屏也能继续。
 */
public class KeepAliveService extends Service {

    private static final String CHANNEL = "playback";
    private static final int NOTI_ID = 1001;

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onCreate() {
        super.onCreate();
        goForeground();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        goForeground();
        return START_STICKY;
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
            PendingIntent pi = PendingIntent.getActivity(
                    this, 0, open, PendingIntent.FLAG_IMMUTABLE);

            Notification.Builder b;
            if (Build.VERSION.SDK_INT >= 26) {
                b = new Notification.Builder(this, CHANNEL);
            } else {
                b = new Notification.Builder(this);
            }
            b.setContentTitle("SyncDlnaPlay")
                    .setContentText("正在播放音乐")
                    .setSmallIcon(R.drawable.ic_stat)
                    .setContentIntent(pi)
                    .setOngoing(true);

            startForeground(NOTI_ID, b.build());
        } catch (Throwable ignored) {
        }
    }
}
