# -*- coding: utf-8 -*-
"""E2E 适配 i18n：测试页强制中文（断言依赖中文文案），并新增英文词典断言。"""
import io, os

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, "make_e2e_page.py")

with io.open(P, encoding="utf-8") as f:
    s = f.read()

# 1) 生成测试页时，强制中文（无头浏览器默认 en-US，会让 i18n 切到英文）
old = '''    # 在 plugins-runtime.js 之前插入桥替身
    marker = '<script src="plugins-runtime.js"></script>'
    if marker not in src:
        raise SystemExit("index.html 里没有找到 plugins-runtime.js 引用")
    src = src.replace(marker, SHIM + marker, 1)'''
new = '''    # 测试页强制中文：断言全部基于中文文案，且无头浏览器默认 en-US
    src = src.replace('<link rel="stylesheet" href="app.css">',
                      '<script>try{localStorage.setItem("dlna_lang","zh")}catch(e){}</script>\\n'
                      '<link rel="stylesheet" href="app.css">', 1)

    # 在 plugins-runtime.js 之前插入桥替身
    marker = '<script src="plugins-runtime.js"></script>'
    if marker not in src:
        raise SystemExit("index.html 里没有找到 plugins-runtime.js 引用")
    src = src.replace(marker, SHIM + marker, 1)'''
if "强制中文" not in s:
    assert old in s, "锚点：生成器主函数"
    s = s.replace(old, new, 1)
    print("ok: 测试页强制中文")
else:
    print("skip: 测试页强制中文（已应用）")

# 2) 驱动里追加英文词典断言
anchor = "      } catch (e) { log('v2.11 沉浸模式', false, e.message); }\n"
block = anchor + '''
      /* v2.12：i18n —— 词典覆盖率 + 设置页语言切换入口 */
      try {
        var hasI18N = !!window.I18N;
        var pairs = [
          ['正在播放', 'Now Playing'], ['我的设备', 'My Devices'], ['本地曲库', 'Local Library'],
          ['在线搜索', 'Online Search'], ['播放列表', 'Queue'], ['设置', 'Settings'],
          ['扫描局域网', 'Scan LAN'], ['边听边下载', 'Download while playing']
        ];
        var hit = 0, miss = [];
        pairs.forEach(function (p) {
          if (I18N.t(p[0]) === p[1]) hit++; else miss.push(p[0]);
        });
        var dyn = I18N.t('3 台设备') === '3 devices' && I18N.t('第 2 页 · 1 首') === 'Page 2 · 1 tracks';
        settingsSheet();
        var sheetTxt = document.getElementById('sheetBody').innerHTML;
        var langUi = sheetTxt.indexOf("I18N.set('en')") >= 0 && sheetTxt.indexOf("I18N.set('zh')") >= 0;
        closeSheet();
        log('v2.12 中英双语', hasI18N && hit === pairs.length && dyn && langUi,
          '引擎=' + hasI18N + ' 词典=' + hit + '/' + pairs.length + ' 动态=' + dyn + ' 切换入口=' + langUi
          + (miss.length ? ' 缺失:' + miss.join(',') : ''));
      } catch (e) { log('v2.12 中英双语', false, e.message); }
'''
if "v2.12 中英双语" not in s:
    assert s.count(anchor) == 1, "锚点：沉浸模式断言"
    s = s.replace(anchor, block, 1)
    print("ok: 新增英文词典断言")
else:
    print("skip: 英文词典断言（已应用）")

with io.open(P, "w", encoding="utf-8", newline="") as f:
    f.write(s)
print("done")
