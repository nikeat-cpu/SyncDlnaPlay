# -*- coding: utf-8 -*-
"""给 E2E 加四条真会失败的断言：
   1. SMB 面板出现「扫描 / 浏览」按钮，且不再有渲染成方块的 🖧
   2. /api/smb/browse 空主机要优雅报错（不崩、不超时）
   3. /api/smb/scan 真扫一遍局域网，必须限时返回
   4. 音源安装 → 出现在清单 + 插件运行时 + 在线音源下拉 → 删除后完全还原
"""
import io
import os

P = os.path.join("tools", "make_e2e_page.py")

NEW_TESTS = r"""
      /* ---------- v2.5：SMB 扫描 / 浏览 ---------- */

      /* SMB 面板：必须有「扫描局域网」「浏览共享」，且方块图标已换成矢量图标 */
      try {
        closeSheet();
        srcAdd('smb');
        var smbHtml = document.getElementById('sheetBody').innerHTML;
        var hasScan = smbHtml.indexOf('smbScan(') >= 0;
        var hasBrowse = smbHtml.indexOf('smbBrowse(') >= 0;
        var noBox = smbHtml.indexOf('\uD83D\uDDA7') < 0 && smbHtml.indexOf('\u26D3') < 0;
        var hasSvg = smbHtml.indexOf('<svg') >= 0;
        log('SMB 面板扫描/浏览', hasScan && hasBrowse && noBox && hasSvg,
          '扫描=' + hasScan + ' 浏览=' + hasBrowse + ' 无方块图标=' + noBox + ' 矢量图标=' + hasSvg);
        closeSheet();
      } catch (e) { log('SMB 面板扫描/浏览', false, e.message); }

      /* SMB 浏览接口：主机为空要给出可读提示，而不是抛异常 */
      try {
        var rb = await apiPost('/api/smb/browse', { host: '' }, 30000);
        log('SMB 浏览接口', rb.ok === false && typeof rb.error === 'string' && rb.error.length > 0,
          rb.error || '(没有错误信息)');
      } catch (e) { log('SMB 浏览接口', false, e.message); }

      /* SMB 局域网扫描：真跑一遍，必须限时返回且结构正确 */
      try {
        var t0 = Date.now();
        var rs = await apiPost('/api/smb/scan', { guest: true, user: '', password: '' }, 90000);
        var dt = Date.now() - t0;
        var okShape = rs && ((rs.ok === true && rs.hosts instanceof Array)
          || (rs.ok === false && typeof rs.error === 'string'));
        log('SMB 局域网扫描', okShape && dt < 45000,
          '耗时 ' + Math.round(dt / 1000) + 's · '
          + (rs.ok ? ('发现 ' + (rs.hosts || []).length + ' 台') : ('跳过：' + rs.error)));
      } catch (e) { log('SMB 局域网扫描', false, e.message); }

      /* ---------- v2.5：音源可自行添加 ---------- */

      /* 音源清单来自本机服务，不是前端写死的 */
      try {
        var rp = await api('/api/plugins');
        var lp = rp.list || [];
        var builtins = lp.filter(function (x) { return x.builtin; }).length;
        log('音源清单', lp.length >= 5 && builtins >= 5,
          '共 ' + lp.length + ' 个，内置 ' + builtins + ' 个');
      } catch (e) { log('音源清单', false, e.message); }

      /* 安装一个临时音源 —— 要真的进清单、进插件运行时、进在线音源下拉，删掉后完全还原 */
      try {
        var before = ((await api('/api/plugins')).list || []).length;
        var testCode = '"use strict";module.exports={platform:"E2E测试音源",version:"0.0.1",'
          + 'search:async function(q,p,t){return {isEnd:true,data:[]};},'
          + 'getMediaSource:async function(i){return {url:""};}};';
        var ri = await apiPost('/api/plugins/install',
          { code: testCode, name: 'e2e-test-src' }, 60000);
        var midList = (await api('/api/plugins')).list || [];
        var hasIt = midList.some(function (x) { return x.name === 'e2e-test-src.js'; });
        var codeList = (await api('/api/plugins/code')).list || [];
        var inRuntime = codeList.some(function (x) { return x.name === 'e2e-test-src.js'; });
        await loadProviders();
        var inDropdown = document.getElementById('onlineProvider').innerHTML.indexOf('E2E测试音源') >= 0;
        var rd = await apiPost('/api/plugins/remove', { name: 'e2e-test-src.js' }, 30000);
        var after = ((await api('/api/plugins')).list || []).length;
        await loadProviders();
        log('音源安装往返',
          ri.ok === true && hasIt && inRuntime && inDropdown && rd.ok === true && after === before,
          '前 ' + before + ' → 中 ' + midList.length + ' → 后 ' + after
          + ' 运行时=' + inRuntime + ' 下拉=' + inDropdown);
      } catch (e) { log('音源安装往返', false, e.message); }

      /* 音源管理面板能渲染出来 */
      try {
        await srcMgrSheet();
        var mgr = document.getElementById('sheetBody').innerHTML;
        var okAdd = mgr.indexOf('srcInstallSheet(') >= 0;
        var okLists = mgr.indexOf('已安装的音源') >= 0;
        log('音源管理面板', okAdd && okLists, '添加入口=' + okAdd + ' 列表=' + okLists);
        closeSheet();
      } catch (e) { log('音源管理面板', false, e.message); }

    } catch (e) {"""


def main():
    s = io.open(P, encoding="utf-8").read()
    anchor = "\n    } catch (e) {"
    n = s.count(anchor)
    assert n >= 1, "找不到测试驱动收尾锚点（命中 %d）" % n
    # 只替换最后一处（驱动里那个）
    idx = s.rindex(anchor)
    s = s[:idx] + NEW_TESTS + s[idx + len(anchor) - len("\n    } catch (e) {"):]
    io.open(P, "w", encoding="utf-8", newline="\n").write(s)
    print("[OK] 已插入 6 条 v2.5 断言")


if __name__ == "__main__":
    main()
