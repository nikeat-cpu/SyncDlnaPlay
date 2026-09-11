# -*- coding: utf-8 -*-
"""v2.4 收尾：两处小修。
  1) volAll 失败时若服务端文案已含「音量」，不再重复前缀（避免「音量设置失败：音量设置失败」）。
  2) 两个截图脚本在拍照前隐藏 #toast —— 那是 E2E 驱动跑出来的测试残留，不是产品状态。
"""
import io
import os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def sub(path, old, new, tag):
    p = os.path.join(ROOT, path)
    s = io.open(p, encoding="utf-8").read()
    n = s.count(old)
    if n == 0 and new in s:
        print("  [SKIP] %s（已应用过）" % tag)
        return
    assert n == 1, "[%s] 命中 %d 次（应为 1）" % (tag, n)
    io.open(p, "w", encoding="utf-8", newline="\n").write(s.replace(old, new, 1))
    print("  [OK] " + tag)


# 1) 失败文案不再重复
sub("app/assets/www/app.js",
    """    if (udns) { const d = devices()[S._volIdx]; if (d) d.volume = v; }
    await tick(true);
  } catch (e) { toast('\u97f3\u91cf\u8bbe\u7f6e\u5931\u8d25\uff1a' + e.message, 'err'); }
}""",
    """    if (udns) { const d = devices()[S._volIdx]; if (d) d.volume = v; }
    await tick(true);
  } catch (e) {
    const m = (e && e.message) || '\u672a\u77e5\u9519\u8bef';
    toast(m.indexOf('\u97f3\u91cf') >= 0 ? m : ('\u97f3\u91cf\u8bbe\u7f6e\u5931\u8d25\uff1a' + m), 'err');
  }
}""",
    "volAll 失败文案去重")

# 2) 截图前隐藏 toast
HIDE = """        pg.evaluate("() => { var e=document.getElementById('e2e-out'); if(e) e.style.display='none'; }")"""
sub("tools/shots_sheets.py", HIDE,
    HIDE + """
        pg.evaluate("() => { var t=document.getElementById('toast'); if(t) t.className='toast'; }")""",
    "shots_sheets 隐藏 toast")

HIDE2 = """        page.evaluate("() => { var e = document.getElementById('e2e-out'); if (e) e.style.display = 'none'; }")"""
sub("tools/e2e_shots.py", HIDE2,
    HIDE2 + """
        page.evaluate("() => { var t = document.getElementById('toast'); if (t) t.className = 'toast'; }")""",
    "e2e_shots 隐藏 toast")

print("\nv2.4 收尾补丁完成。")
