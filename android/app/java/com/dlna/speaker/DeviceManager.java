package com.dlna.speaker;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * DLNA 设备管理：后台扫描 + 状态缓存
 * ===================================
 * 对应 Python 版 server.py 里的 DeviceManager。纯标准库，可在桌面运行。
 */
public final class DeviceManager {

    private final Map<String, Dlna.DeviceInfo> renderers = new ConcurrentHashMap<String, Dlna.DeviceInfo>();
    private final Map<String, Map<String, Object>> status = new ConcurrentHashMap<String, Map<String, Object>>();
    private final List<Dlna.DeviceInfo> servers = new ArrayList<Dlna.DeviceInfo>();

    private volatile boolean scanning = false;
    private volatile long lastScan = 0;
    private String preferNet = "";

    public void setPreferNet(String net) { this.preferNet = net == null ? "" : net; }
    public String getPreferNet() { return preferNet; }

    public boolean isScanning() { return scanning; }
    public long getLastScan() { return lastScan; }

    public List<Dlna.DeviceInfo> allRenderers() {
        List<Dlna.DeviceInfo> out = new ArrayList<Dlna.DeviceInfo>(renderers.values());
        Collections.sort(out, new java.util.Comparator<Dlna.DeviceInfo>() {
            @Override public int compare(Dlna.DeviceInfo a, Dlna.DeviceInfo b) { return a.ip.compareTo(b.ip); }
        });
        return out;
    }

    public List<Dlna.DeviceInfo> allServers() {
        synchronized (servers) { return new ArrayList<Dlna.DeviceInfo>(servers); }
    }

    public Dlna.DeviceInfo rendererInfo(String udn) { return renderers.get(udn); }

    public Dlna.Renderer renderer(String udn) {
        Dlna.DeviceInfo info = renderers.get(udn);
        return info == null ? null : new Dlna.Renderer(info);
    }

    public Map<String, Map<String, Object>> statusMap() { return status; }

    /** 同步扫描（约 3~6 秒） */
    public synchronized void refresh() {
        if (scanning) return;
        scanning = true;
        try {
            List<Dlna.DeviceInfo> found = Dlna.discover(null, preferNet.isEmpty() ? null : preferNet, 3, 8);
            Map<String, Dlna.DeviceInfo> nextRenderers = new LinkedHashMap<String, Dlna.DeviceInfo>();
            List<Dlna.DeviceInfo> nextServers = new ArrayList<Dlna.DeviceInfo>();
            for (Dlna.DeviceInfo d : found) {
                if (d.isRenderer()) nextRenderers.put(d.udn, d);
                else if (d.isServer()) nextServers.add(d);
            }
            renderers.keySet().retainAll(nextRenderers.keySet());
            renderers.putAll(nextRenderers);
            synchronized (servers) {
                servers.clear();
                servers.addAll(nextServers);
            }
            lastScan = System.currentTimeMillis() / 1000L;
        } finally {
            scanning = false;
        }
    }

    /** 后台扫描，不阻塞请求 */
    public void refreshAsync() {
        if (scanning) return;
        Thread t = new Thread(new Runnable() {
            @Override public void run() {
                try {
                    refresh();
                } catch (Throwable ignore) {
                    // 发现失败不该终止进程（Android 上裸线程异常会直接闪退）
                }
            }
        }, "dlna-scan");
        t.setDaemon(true);
        t.start();
    }

    /** 刷新所有已选渲染器的状态（供调度器/状态接口使用） */
    public void pollStatus(List<String> udns) {
        for (final String udn : udns) {
            final Dlna.Renderer r = renderer(udn);
            if (r == null) continue;
            Map<String, Object> st = r.status();
            status.put(udn, st);
        }
    }

    /** 只刷新传输状态与进度（高频调用，开销更小） */
    public Map<String, Object> pollQuick(String udn) {
        Dlna.Renderer r = renderer(udn);
        if (r == null) return null;
        Map<String, Object> st = r.quickStatus();
        Map<String, Object> prev = status.get(udn);
        if (prev != null) {
            st.put("volume", prev.get("volume"));
            st.put("mute", prev.get("mute"));
        }
        status.put(udn, st);
        return st;
    }

    public void putStatus(String udn, Map<String, Object> st) { status.put(udn, st); }
}
