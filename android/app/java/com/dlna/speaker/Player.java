package com.dlna.speaker;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 播放器：队列 + 播放目标 + 传输控制 + 自动续播调度器
 * ==================================================
 * 对应 Python 版 server.py 里的 Player / scheduler_loop。
 *
 * 输出方式由 targets 决定：
 *   - targets 为空  -> 「本机播放」，由前端 <audio> 播放，前端在 ended 时调 next
 *   - targets 非空  -> 「投放音响」，本类负责把 URL 推给 DLNA 渲染器并轮询续播
 *
 * 自动续播的判定规则（照搬线上验证过的经验，别改回简化版）：
 *   在线曲目 duration 常为 0，不能凭 STOPPED 就判定播完；
 *   必须先见过 PLAYING（sawPlaying）才允许判定结束；
 *   若推送后一直没开播，超过 120 秒才兜底跳下一曲。
 */
public final class Player {

    /** 把队列里的曲目转成渲染器可拉取的绝对 URL */
    public interface UrlBuilder { String build(Map<String, Object> track); }

    public static final int NO_PLAY_FALLBACK_SEC = 120;

    private final DeviceManager dm;
    private UrlBuilder urlBuilder;

    private final Object lock = new Object();
    private final List<Map<String, Object>> queue = new ArrayList<Map<String, Object>>();
    private int index = -1;
    private List<Integer> order = new ArrayList<Integer>();
    private int playpos = 0;
    private final List<String> targets = new ArrayList<String>();
    private final Map<String, Integer> delays = new LinkedHashMap<String, Integer>();
    private volatile boolean playing = false;
    private volatile boolean autoAdvance = true;
    private volatile String repeat = "off";        // off | all | one
    private volatile boolean shuffle = false;

    private volatile String lastUri = "";
    private volatile boolean sawPlaying = false;
    private volatile long playStartedAt = 0;
    private volatile int lastPosSec = -1;
    private volatile String lastError = "";
    private volatile long lastAdvanceAt = 0;

    public Player(DeviceManager dm) {
        this.dm = dm;
    }

    public void setUrlBuilder(UrlBuilder b) { this.urlBuilder = b; }

    public DeviceManager devices() { return dm; }

    /* ------------------------------------------------------------ 状态 */

    public boolean isPlaying() { return playing; }
    public String getRepeat() { return repeat; }
    public boolean isShuffle() { return shuffle; }
    public String getLastError() { return lastError; }

    public List<String> getTargets() {
        synchronized (lock) { return new ArrayList<String>(targets); }
    }

    public List<Map<String, Object>> getQueue() {
        synchronized (lock) { return new ArrayList<Map<String, Object>>(queue); }
    }

    public int getIndex() { return index; }

    public Map<String, Object> getCurrent() {
        synchronized (lock) {
            if (index < 0 || index >= queue.size()) return null;
            return queue.get(index);
        }
    }

    /** 对外快照（供 /api/state 使用） */
    public Map<String, Object> snapshot() {
        Map<String, Object> m = Json.map();
        synchronized (lock) {
            List<Object> q = new ArrayList<Object>();
            for (Map<String, Object> t : queue) q.add(publicTrack(t));
            m.put("queue", q);
            m.put("index", index);
            m.put("order", new ArrayList<Object>(order));
            m.put("playpos", playpos);
            m.put("targets", new ArrayList<Object>(targets));
            m.put("playing", playing);
            m.put("auto_advance", autoAdvance);
            m.put("repeat", repeat);
            m.put("shuffle", shuffle);
            Map<String, Object> cur = (index >= 0 && index < queue.size()) ? queue.get(index) : null;
            m.put("current", cur == null ? null : publicTrack(cur));
            m.put("output", targets.isEmpty() ? "phone" : "dlna");
        }
        return m;
    }

    /** 给前端的曲目视图（附上可直接播放的 url） */
    public Map<String, Object> publicTrack(Map<String, Object> t) {
        Map<String, Object> m = new LinkedHashMap<String, Object>(t);
        String url = urlFor(t);
        m.put("url", url == null ? "" : url);
        if (!m.containsKey("duration")) m.put("duration", Dlna.secToTsec(Json.i(t, "duration_sec", 0)));
        if (!m.containsKey("duration_sec")) m.put("duration_sec", 0);
        return m;
    }

    private String urlFor(Map<String, Object> t) {
        if (t == null) return "";
        if (urlBuilder != null) {
            String u = urlBuilder.build(t);
            if (u != null && !u.isEmpty()) return u;
        }
        return Json.s(t, "url");
    }

    /* ------------------------------------------------------------ 目标 */

    public List<String> setTargets(List<String> udns) {
        synchronized (lock) {
            targets.clear();
            if (udns != null) {
                for (String u : udns) if (u != null && !u.isEmpty() && !targets.contains(u)) targets.add(u);
            }
            return new ArrayList<String>(targets);
        }
    }

    public int setDelay(String udn, int delayMs) {
        int v = Math.max(0, Math.min(5000, delayMs));
        synchronized (lock) { delays.put(udn, v); }
        return v;
    }

    public Map<String, Integer> getDelays() {
        synchronized (lock) { return new LinkedHashMap<String, Integer>(delays); }
    }

    /* ------------------------------------------------------------ 模式 */

    public String setMode(String rep, Boolean shf) {
        if (rep != null && !rep.isEmpty()) repeat = rep;
        if (shf != null) {
            shuffle = shf.booleanValue();
            rebuildOrder();
        }
        return repeat;
    }

    private void rebuildOrder() {
        synchronized (lock) {
            order = new ArrayList<Integer>();
            for (int i = 0; i < queue.size(); i++) order.add(i);
            if (shuffle) {
                // 保持当前曲目在最前，其余打乱
                List<Integer> rest = new ArrayList<Integer>(order);
                rest.remove(Integer.valueOf(index));
                Collections.shuffle(rest);
                order = new ArrayList<Integer>();
                if (index >= 0 && index < queue.size()) order.add(index);
                order.addAll(rest);
                playpos = 0;
            } else {
                playpos = Math.max(0, index);
            }
        }
    }

    /* ------------------------------------------------------------ 队列 */

    public int queueAdd(List<Map<String, Object>> tracks) {
        if (tracks == null || tracks.isEmpty()) return queueSize();
        synchronized (lock) {
            queue.addAll(tracks);
            rebuildOrder();
            return queue.size();
        }
    }

    public boolean queueRemove(int idx) {
        synchronized (lock) {
            if (idx < 0 || idx >= queue.size()) return false;
            queue.remove(idx);
            if (index >= idx) index = Math.max(-1, index - 1);
            rebuildOrder();
            return true;
        }
    }

    public void queueClear() {
        synchronized (lock) {
            queue.clear();
            order.clear();
            index = -1;
            playpos = 0;
            playing = false;
        }
    }

    public int queueSize() {
        synchronized (lock) { return queue.size(); }
    }

    /* ------------------------------------------------------------ 播放 */

    /** 播放一组曲目（替换队列） */
    public boolean playTracks(List<Map<String, Object>> tracks, int startIndex) {
        if (tracks == null || tracks.isEmpty()) {
            lastError = "没有曲目";
            return false;
        }
        synchronized (lock) {
            queue.clear();
            queue.addAll(tracks);
            index = Math.max(0, Math.min(startIndex, queue.size() - 1));
            rebuildOrder();
        }
        return playIndex(index);
    }

    /** 跳到队列中的某一曲 */
    public boolean jump(int i) {
        synchronized (lock) {
            if (i < 0 || i >= queue.size()) return false;
            index = i;
            if (shuffle) {
                int p = order.indexOf(Integer.valueOf(i));
                if (p >= 0) playpos = p;
            } else {
                playpos = i;
            }
        }
        return playIndex(i);
    }

    /** 播放当前 index 指向的曲目 */
    public boolean playIndex(int i) {
        Map<String, Object> track;
        synchronized (lock) {
            if (i < 0 || i >= queue.size()) return false;
            index = i;
            track = queue.get(i);
        }
        String url = urlFor(track);
        if (url == null || url.isEmpty()) {
            lastError = "曲目没有可播放地址";
            return false;
        }
        lastUri = url;
        sawPlaying = false;
        lastPosSec = -1;
        playStartedAt = System.currentTimeMillis();
        playing = true;

        List<String> tgs = getTargets();
        if (tgs.isEmpty()) {
            return true;        // 本机播放：前端负责
        }
        boolean anyOk = false;
        String err = "";
        for (String udn : tgs) {
            Dlna.Renderer r = dm.renderer(udn);
            if (r == null) { err = "设备不在线: " + udn; continue; }
            Integer d = delays.get(udn);
            if (d != null && d > 0) {
                try { Thread.sleep(d); } catch (InterruptedException ignore) { }
            }
            Dlna.SoapResult sr = r.setUri(url, Json.s(track, "title"),
                    Dlna.secToTsec(Json.i(track, "duration_sec", 0)),
                    Json.s(track, "artist"), Json.s(track, "album"), null, null, 8);
            if (!sr.ok) { err = sr.error; continue; }
            try { Thread.sleep(120); } catch (InterruptedException ignore) { }
            Dlna.SoapResult pr = r.play();
            if (!pr.ok) { err = pr.error; continue; }
            anyOk = true;
        }
        if (!anyOk) {
            lastError = err.isEmpty() ? "推送到音响失败" : err;
            playing = false;
        }
        return anyOk;
    }

    /** 传输控制: play / pause / stop / next / prev */
    public boolean control(String action, List<String> udns) {
        if (action == null) return false;
        if (udns != null && !udns.isEmpty()) setTargets(udns);
        action = action.toLowerCase();

        if ("next".equals(action)) return next();
        if ("prev".equals(action)) return prev();

        List<String> tgs = getTargets();
        if ("play".equals(action)) {
            if (tgs.isEmpty()) { playing = true; return true; }
            boolean ok = false;
            for (String udn : tgs) {
                Dlna.Renderer r = dm.renderer(udn);
                if (r != null && r.play().ok) ok = true;
            }
            playing = ok;
            return ok;
        }
        if ("pause".equals(action)) {
            if (tgs.isEmpty()) { playing = false; return true; }
            boolean ok = false;
            for (String udn : tgs) {
                Dlna.Renderer r = dm.renderer(udn);
                if (r != null && r.pause().ok) ok = true;
            }
            playing = false;
            return ok;
        }
        if ("stop".equals(action)) {
            if (tgs.isEmpty()) { playing = false; return true; }
            boolean ok = false;
            for (String udn : tgs) {
                Dlna.Renderer r = dm.renderer(udn);
                if (r != null && r.stop().ok) ok = true;
            }
            playing = false;
            return ok;
        }
        return false;
    }

    /** 下一曲（尊重 repeat / shuffle） */
    public boolean next() {
        synchronized (lock) {
            if (queue.isEmpty()) return false;
            if (shuffle && !order.isEmpty()) {
                if (playpos + 1 < order.size()) {
                    playpos++;
                } else if ("all".equals(repeat)) {
                    Collections.shuffle(order);
                    playpos = 0;
                } else {
                    playing = false;
                    return false;
                }
                index = order.get(playpos);
            } else {
                if (index + 1 < queue.size()) {
                    index++;
                } else if ("all".equals(repeat)) {
                    index = 0;
                } else {
                    playing = false;
                    return false;
                }
            }
        }
        return playIndex(index);
    }

    public boolean prev() {
        synchronized (lock) {
            if (queue.isEmpty()) return false;
            if (shuffle && !order.isEmpty()) {
                if (playpos > 0) playpos--;
                else playpos = order.size() - 1;
                index = order.get(playpos);
            } else {
                if (index > 0) index--;
                else index = queue.size() - 1;
            }
        }
        return playIndex(index);
    }

    /** 单曲循环时重播当前曲 */
    private boolean replayCurrent() {
        synchronized (lock) {
            if (index < 0 || index >= queue.size()) return false;
        }
        return playIndex(index);
    }

    public boolean setVolume(int volume, List<String> udns) {
        List<String> tgs = (udns != null && !udns.isEmpty()) ? udns : getTargets();
        if (tgs.isEmpty()) return false;
        boolean ok = false;
        for (String udn : tgs) {
            Dlna.Renderer r = dm.renderer(udn);
            if (r != null && r.setVolume(volume).ok) ok = true;
        }
        return ok;
    }

    public boolean seek(int positionSec, List<String> udns) {
        List<String> tgs = (udns != null && !udns.isEmpty()) ? udns : getTargets();
        if (tgs.isEmpty()) return false;
        boolean ok = false;
        for (String udn : tgs) {
            Dlna.Renderer r = dm.renderer(udn);
            if (r != null && r.seek(Dlna.secToTsec(Math.max(0, positionSec))).ok) ok = true;
        }
        return ok;
    }

    /** 向渲染器重新推送当前曲目（校准音画/恢复状态） */
    public boolean resync() {
        Map<String, Object> cur = getCurrent();
        if (cur == null) return false;
        return playIndex(index);
    }

    /* ------------------------------------------------------- 自动续播 */

    /**
     * 调度器单次 tick。由后台线程周期调用。
     * 只处理「投放音响」模式：本机播放由前端 <audio> 的 ended 事件驱动。
     */
    public void tick() {
        if (!playing || !autoAdvance) return;
        List<String> tgs = getTargets();
        if (tgs.isEmpty()) return;

        Dlna.Renderer probe = dm.renderer(tgs.get(0));
        if (probe == null) return;
        Map<String, Object> st = probe.quickStatus();
        if (st == null) return;
        dm.putStatus(tgs.get(0), st);

        boolean online = Boolean.TRUE.equals(st.get("online"));
        if (!online) return;
        String state = String.valueOf(st.get("state"));
        int pos = Json.i(st, "position_sec", 0);
        int dur = Json.i(st, "duration_sec", 0);

        if ("PLAYING".equals(state)) {
            sawPlaying = true;
            lastPosSec = pos;
        }

        // 判定一：进度已到达曲长（最可靠，但仅当曲长已知）
        boolean endedByPos = dur > 0 && pos > 0 && pos >= dur - 1;
        // 判定二：播放过之后变为停止
        boolean endedByState = sawPlaying && "STOPPED".equals(state)
                && (dur <= 0 || pos >= dur - 2);
        // 判定三：一直没能开播（音源不可达等），兜底跳过
        boolean neverStarted = !sawPlaying
                && (System.currentTimeMillis() - playStartedAt) > NO_PLAY_FALLBACK_SEC * 1000L;

        if (endedByPos || endedByState || neverStarted) {
            long now = System.currentTimeMillis();
            if (now - lastAdvanceAt < 1500) return;      // 防止重复触发
            lastAdvanceAt = now;
            if ("one".equals(repeat)) {
                replayCurrent();
            } else {
                next();
            }
        }
    }

    /** 供后台线程调用的循环入口 */
    public void schedulerLoop(long intervalMs) {
        while (!Thread.currentThread().isInterrupted()) {
            try {
                tick();
            } catch (Throwable ignore) {
                // 调度器绝不能因为单次异常退出
            }
            try {
                Thread.sleep(intervalMs);
            } catch (InterruptedException e) {
                return;
            }
        }
    }
}
