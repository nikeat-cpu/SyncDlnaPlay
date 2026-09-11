package com.dlna.speaker;

import android.webkit.RenderProcessGoneDetail;
import android.webkit.WebView;
import android.webkit.WebViewClient;

/**
 * WebView 渲染进程崩溃兜底
 * ========================
 * Android 8（API 26）起 WebView 的渲染器跑在独立进程里。当它因为内存不足
 * 或被系统回收而挂掉时，会回调到宿主 App 的 onRenderProcessGone()：
 *
 *   - 返回 false（默认）：**系统直接把整个 App 杀掉** —— 用户看到的就是「闪退」。
 *   - 返回 true          ：由我们自己处理，App 继续存活，可以重建 WebView 恢复界面。
 *
 * 在线音乐这条链路里，插件解析音源时会把整个网页/接口响应经 /__proxy 走 base64
 * 送回 WebView，响应偏大时渲染进程的内存压力会明显上升，是最容易触发这一幕的地方。
 *
 * 注意：本类引用了 API 26 才有的 RenderProcessGoneDetail，因此只能在 API 26+
 * 上实例化（MainActivity 里有版本判断），低版本设备不会加载到它。
 */
public class SafeWebViewClient extends WebViewClient {

    public interface Listener {
        /** 渲染进程没了。reason 是给用户看的一句人话。 */
        void onRendererGone(String reason);
    }

    private final Listener listener;

    public SafeWebViewClient(Listener listener) {
        this.listener = listener;
    }

    @Override
    public boolean onRenderProcessGone(WebView view, RenderProcessGoneDetail detail) {
        String reason = "页面进程崩溃";
        try {
            if (detail != null && !detail.didCrash()) {
                reason = "页面进程被系统回收（内存不足）";
            }
        } catch (Throwable ignore) { }
        try {
            if (listener != null) listener.onRendererGone(reason);
        } catch (Throwable ignore) { }
        // 必须返回 true：告诉系统「我自己搞定了」，否则 App 会被一起杀掉
        return true;
    }
}
