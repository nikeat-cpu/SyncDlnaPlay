# -*- coding: utf-8 -*-
"""v2.10：修复「正在播放」进度条乱跳。
根因：
  1) 音响进度快照有粒度/延迟，每次轮询直接重置滑条 → 来回跳；
  2) seek 后音响要 1~3s 才生效，期间旧快照把滑条弹回去再猛跳；
  3) 拖动守卫用 activeElement 在触屏上不可靠。
修复：
  - smoothAccept()：外推 + 小偏差(<2.5s)忽略噪声 + 大偏差才采纳跳变；
  - seekTo/seekToTime 设置 5s 宽限期，期间以 seek 目标外推，不理会旧快照；
  - seekLive 拖动时刷新 S._seekDragUntil 时间窗，refreshNow 窗口内不写滑条。
"""
import io

P = "app/assets/www/app.js"
with io.open(P, encoding="utf-8") as f:
    s = f.read()

# 1) nowPlaying()：换成平滑器
old = """  if (!dur && t && t.duration_sec) dur = t.duration_sec;
  // 歌词/进度平滑：服务端进度是轮询快照，两次轮询之间按本机时钟外推
  if (pl.playing && S.posRef && S.posRef.playing) {
    const el = Math.min(30, Math.max(0, performance.now() - S.posRef.at) / 1000);
    pos = Math.max(pos, S.posRef.pos + el);
  }
  return { t: t, pos: pos, dur: dur, playing: !!pl.playing };
}"""
new = """  if (!dur && t && t.duration_sec) dur = t.duration_sec;
  pos = smoothAccept(pos, pl.playing);   // 进度平滑：滤掉快照噪声，只认真跳变
  return { t: t, pos: pos, dur: dur, playing: !!pl.playing };
}

/* 进度平滑器：音响的进度上报有粒度和延迟（有的设备几秒才刷一次，
   多台取 max 还会来回切源），直接画会乱跳。
   规则：
   - 本地按时钟外推（每 300ms 高亮定时器与 1.6s 轮询都会调到）；
   - 新快照与当前外推差 < 2.5s → 当作上报噪声，忽略，继续外推；
   - 差 >= 2.5s → 视为真实 seek/换曲/暂停恢复，跳变采纳；
   - 手动 seek 后 5s 宽限期内完全以 seek 目标外推（音响生效有延迟）。 */
function smoothAccept(rawPos, playing) {
  const now = performance.now();
  playing = !!playing;
  if (!S._sm || !playing) {
    S._sm = { pos: rawPos, at: now, playing: playing };
    return rawPos;
  }
  const el = Math.min(30, Math.max(0, now - S._sm.at) / 1000);
  let cur = S._sm.playing ? S._sm.pos + el : S._sm.pos;
  if (S._seekAt && now - S._seekAt < 5000) {
    cur = S._seekPos + (S._sm.playing ? el : 0);
  } else if (Math.abs(rawPos - cur) > 2.5) {
    cur = rawPos;
  }
  S._sm = { pos: cur, at: now, playing: playing };
  return cur;
}"""
assert s.count(old) == 1, "nowPlaying anchor"
s = s.replace(old, new)

# 2) seekTo：设置宽限期（手机模式同样记录，切回 dlna 时也成立）
old = """async function seekTo(v) {
  v = parseInt(v, 10) || 0;
  if (S.out === 'phone') { try { audio.currentTime = v; } catch (e) { } return; }
  try { await apiPost('/api/seek', { position: v }); } catch (e) { toast('跳转失败：' + e.message, 'err'); }
}"""
new = """async function seekTo(v) {
  v = parseInt(v, 10) || 0;
  S._seekPos = v;
  S._seekAt = performance.now();   // 5s 宽限期：期间进度条以目标位置外推
  if (S.out === 'phone') { try { audio.currentTime = v; } catch (e) { } return; }
  try { await apiPost('/api/seek', { position: v }); } catch (e) { toast('跳转失败：' + e.message, 'err'); }
}"""
assert s.count(old) == 1, "seekTo anchor"
s = s.replace(old, new)

# 3) seekToTime（点歌词跳转）：同样进宽限期
old = """function seekToTime(sec) {
  if (S.out === 'phone') { try { audio.currentTime = sec; } catch (e) { } return; }
  apiPost('/api/seek', { position: Math.floor(sec) }).catch(function () { });
}"""
new = """function seekToTime(sec) {
  S._seekPos = Math.floor(sec);
  S._seekAt = performance.now();
  if (S.out === 'phone') { try { audio.currentTime = sec; } catch (e) { } return; }
  apiPost('/api/seek', { position: Math.floor(sec) }).catch(function () { });
}"""
assert s.count(old) == 1, "seekToTime anchor"
s = s.replace(old, new)

# 4) 拖动时间窗守卫：seekLive 记录最后拖动时刻
old = """function seekLive(v) { const el = $('npPos'); if (el) el.textContent = fmt(v); }"""
new = """function seekLive(v) {
  S._seekDragUntil = performance.now() + 1500;   // 拖动中：1.5s 内轮询不得改写滑条
  const el = $('npPos'); if (el) el.textContent = fmt(v);
}"""
assert s.count(old) == 1, "seekLive anchor"
s = s.replace(old, new)

# 5) refreshNow：用时间窗替代 activeElement 守卫
old = """  const seek = $('npSeek');
  if (seek && document.activeElement !== seek && n.dur) seek.value = Math.floor(n.pos);"""
new = """  const seek = $('npSeek');
  if (seek && n.dur && performance.now() >= (S._seekDragUntil || 0)) seek.value = Math.floor(n.pos);"""
assert s.count(old) == 1, "refreshNow anchor"
s = s.replace(old, new)

with io.open(P, "w", encoding="utf-8", newline="") as f:
    f.write(s)
print("patch ok")
