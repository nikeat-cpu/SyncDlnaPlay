package com.dlna.speaker;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.HttpURLConnection;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.NetworkInterface;
import java.net.URL;
import java.nio.charset.Charset;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Enumeration;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import javax.xml.parsers.DocumentBuilder;
import javax.xml.parsers.DocumentBuilderFactory;

import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.Node;
import org.w3c.dom.NodeList;

/**
 * UPnP / DLNA 控制点核心库（Java 版）
 * ====================================
 * 由项目里的 app/upnp.py 忠实移植，行为保持一致。
 * <p>
 * 【重要】本文件刻意不引用任何 android.* API，只依赖 Java 标准库，
 * 因此可以直接在桌面 JVM 上编译运行，对着真实音响做发现/播放验证。
 * <p>
 * 职责：
 * 1. SSDP 设备发现（多网卡并发，避开回环 / 169.254 / Tailscale CGNAT 段）
 * 2. UPnP SOAP 调用封装
 * 3. MediaRenderer 控制（播放/暂停/停止/音量/进度查询）
 * 4. MediaServer 内容浏览（MiniDLNA ContentDirectory）
 * 5. DIDL-Lite 元数据生成（推送 URI 时渲染器需要它才能正确识别音频）
 */
public final class Dlna {

    private Dlna() {}

    /* ------------------------------------------------------------ 常量 */

    public static final String SSDP_ADDR = "239.255.255.250";
    public static final int SSDP_PORT = 1900;

    public static final String AVT = "urn:schemas-upnp-org:service:AVTransport:1";
    public static final String RC  = "urn:schemas-upnp-org:service:RenderingControl:1";
    public static final String CM  = "urn:schemas-upnp-org:service:ConnectionManager:1";
    public static final String CD  = "urn:schemas-upnp-org:service:ContentDirectory:1";

    public static final String DEV_NS = "urn:schemas-upnp-org:device-1-0";
    public static final String SVC_NS = "urn:schemas-upnp-org:service-1-0";

    public static final String DIDL_NS = "urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/";
    public static final String DC_NS   = "http://purl.org/dc/elements/1.1/";
    public static final String UPNP_NS = "urn:schemas-upnp-org:metadata-1-0/upnp/";

    public static final int DEFAULT_TIMEOUT = 6;
    public static final String UA = "DLNA-Controller/1.0";

    /** 音频扩展名 -> {mime, DLNA.ORG_PN}；pn 为 null 表示不写 PN */
    private static final Map<String, String[]> MIME_MAP = new LinkedHashMap<String, String[]>();
    static {
        MIME_MAP.put("mp3",  new String[]{"audio/mpeg", "MP3"});
        MIME_MAP.put("flac", new String[]{"audio/flac", "FLAC"});
        MIME_MAP.put("wav",  new String[]{"audio/wav", "WAV"});
        MIME_MAP.put("m4a",  new String[]{"audio/mp4", "AAC_ISO_320"});
        MIME_MAP.put("aac",  new String[]{"audio/aac", "AAC_ISO"});
        MIME_MAP.put("ogg",  new String[]{"audio/ogg", "OGG"});
        MIME_MAP.put("oga",  new String[]{"audio/ogg", "OGG"});
        MIME_MAP.put("opus", new String[]{"audio/ogg", "OPUS"});
        MIME_MAP.put("wma",  new String[]{"audio/x-ms-wma", "WMAFULL"});
        MIME_MAP.put("ape",  new String[]{"audio/x-ape", null});
        MIME_MAP.put("aiff", new String[]{"audio/aiff", "AIFF"});
        MIME_MAP.put("aif",  new String[]{"audio/aiff", "AIFF"});
        MIME_MAP.put("mp4",  new String[]{"audio/mp4", "AAC_ISO_320"});
        MIME_MAP.put("m3u8", new String[]{"application/x-mpegURL", null});
    }

    /** 根据 URL 扩展名推断 {mime, pn} */
    public static String[] guessMime(String url) {
        String u = url == null ? "" : url;
        int q = u.indexOf('?');
        if (q >= 0) u = u.substring(0, q);
        while (u.endsWith("/")) u = u.substring(0, u.length() - 1);
        int dot = u.lastIndexOf('.');
        String ext = dot >= 0 ? u.substring(dot + 1).toLowerCase(Locale.ROOT) : "";
        String[] hit = MIME_MAP.get(ext);
        return hit != null ? new String[]{hit[0], hit[1]} : new String[]{"audio/mpeg", "MP3"};
    }

    /* ------------------------------------------------------- 网卡 / IP */

    /** 是否可以用于局域网组播：排除回环、链路本地、Tailscale CGNAT(100.64/10) */
    private static boolean usableIp(String ip) {
        if (ip == null || ip.isEmpty()) return false;
        if (ip.startsWith("127.") || ip.startsWith("169.254.")) return false;
        String[] p = ip.split("\\.");
        if (p.length == 4) {
            try {
                int a = Integer.parseInt(p[0]);
                int b = Integer.parseInt(p[1]);
                if (a == 100 && b >= 64 && b <= 127) return false;   // CGNAT
            } catch (NumberFormatException ignore) { }
        }
        return true;
    }

    /** 枚举所有可用于局域网组播的本机 IPv4 */
    public static List<String> localIps() {
        List<String> out = new ArrayList<String>();
        Set<String> seen = new LinkedHashSet<String>();
        try {
            Enumeration<NetworkInterface> nis = NetworkInterface.getNetworkInterfaces();
            if (nis == null) return out;
            while (nis.hasMoreElements()) {
                NetworkInterface ni = nis.nextElement();
                try {
                    if (!ni.isUp() || ni.isLoopback()) continue;
                } catch (Exception ignore) { }
                Enumeration<InetAddress> addrs = ni.getInetAddresses();
                while (addrs.hasMoreElements()) {
                    InetAddress a = addrs.nextElement();
                    if (!(a instanceof Inet4Address)) continue;
                    String ip = a.getHostAddress();
                    if (!usableIp(ip)) continue;
                    if (seen.add(ip)) out.add(ip);
                }
            }
        } catch (Exception ignore) { }
        return out;
    }

    /**
     * 选择用于发 SSDP 的网卡 IP 列表。
     * @param prefer 形如 "192.168.1." 的网段前缀；命中则只用它，否则返回全部候选
     */
    public static List<String> pickIps(String prefer) {
        List<String> ips = localIps();
        if (prefer != null && !prefer.isEmpty()) {
            List<String> hit = new ArrayList<String>();
            for (String ip : ips) if (ip.startsWith(prefer)) hit.add(ip);
            if (!hit.isEmpty()) return hit;
        }
        if (ips.isEmpty()) ips.add("0.0.0.0");
        return ips;
    }

    /* ------------------------------------------------------ HTTP / XML */

    public static String httpGet(String url, int timeoutSec) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        try {
            c.setRequestMethod("GET");
            c.setConnectTimeout(timeoutSec * 1000);
            c.setReadTimeout(timeoutSec * 1000);
            c.setRequestProperty("User-Agent", UA);
            c.setRequestProperty("Connection", "close");
            int code = c.getResponseCode();
            InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
            String body = readAll(in);
            if (code >= 400) throw new Exception("HTTP " + code + ": " + trim(body, 200));
            return body;
        } finally {
            try { c.disconnect(); } catch (Exception ignore) { }
        }
    }

    private static String readAll(InputStream in) throws Exception {
        if (in == null) return "";
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) > 0) bos.write(buf, 0, n);
        in.close();
        return new String(bos.toByteArray(), Charset.forName("UTF-8"));
    }

    private static String trim(String s, int n) {
        if (s == null) return "";
        return s.length() <= n ? s : s.substring(0, n);
    }

    /** 去掉命名空间前缀（同时兼容 "dc:title" 与 "{ns}title" 两种写法） */
    public static String stripNs(String tag) {
        if (tag == null) return "";
        int b = tag.lastIndexOf('}');
        if (b >= 0) return tag.substring(b + 1);
        int c = tag.lastIndexOf(':');
        if (c >= 0) return tag.substring(c + 1);
        return tag;
    }

    private static String ln(Node n) {
        if (n == null) return "";
        String local = n.getLocalName();
        if (local != null && !local.isEmpty()) return local;
        return stripNs(n.getNodeName());
    }

    public static Element findChild(Node parent, String name) {
        if (parent == null) return null;
        NodeList kids = parent.getChildNodes();
        for (int i = 0; i < kids.getLength(); i++) {
            Node c = kids.item(i);
            if (c.getNodeType() == Node.ELEMENT_NODE && name.equals(ln(c))) return (Element) c;
        }
        return null;
    }

    public static List<Element> findallChild(Node parent, String name) {
        List<Element> out = new ArrayList<Element>();
        if (parent == null) return out;
        NodeList kids = parent.getChildNodes();
        for (int i = 0; i < kids.getLength(); i++) {
            Node c = kids.item(i);
            if (c.getNodeType() == Node.ELEMENT_NODE && name.equals(ln(c))) out.add((Element) c);
        }
        return out;
    }

    public static String textOf(Node parent, String name, String def) {
        Element n = findChild(parent, name);
        if (n == null) return def;
        String t = n.getTextContent();
        return t == null ? def : t.trim();
    }

    public static String textOf(Node parent, String name) { return textOf(parent, name, ""); }

    public static Document parseXml(String xml) throws Exception {
        DocumentBuilderFactory f = DocumentBuilderFactory.newInstance();
        f.setNamespaceAware(true);
        // 关闭外部实体，避免 XXE（部分实现不支持这些特性，忽略异常即可）
        try { f.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true); } catch (Exception ignore) { }
        try { f.setFeature("http://xml.org/sax/features/external-general-entities", false); } catch (Exception ignore) { }
        try { f.setFeature("http://xml.org/sax/features/external-parameter-entities", false); } catch (Exception ignore) { }
        f.setExpandEntityReferences(false);
        DocumentBuilder b = f.newDocumentBuilder();
        // 设备返回的内容不一定是 XML（超时/空响应/HTML 错误页都会走到这里）。
        // 默认 ErrorHandler 会往 stderr 打 "[Fatal Error] 前言中不允许有内容"，
        // 轮询状态下会把日志刷爆，所以静默掉，由调用方按返回值判断成败。
        b.setErrorHandler(new org.xml.sax.ErrorHandler() {
            @Override public void warning(org.xml.sax.SAXParseException e) { }
            @Override public void error(org.xml.sax.SAXParseException e) { }
            @Override public void fatalError(org.xml.sax.SAXParseException e) throws org.xml.sax.SAXException {
                throw e;
            }
        });
        b.setEntityResolver(new org.xml.sax.EntityResolver() {
            @Override public org.xml.sax.InputSource resolveEntity(String pub, String sys) {
                return new org.xml.sax.InputSource(new java.io.StringReader(""));
            }
        });
        return b.parse(new org.xml.sax.InputSource(new java.io.StringReader(xml)));
    }

    public static String escapeXml(String s) {
        if (s == null) return "";
        StringBuilder sb = new StringBuilder(s.length() + 16);
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '&':  sb.append("&amp;"); break;
                case '<':  sb.append("&lt;"); break;
                case '>':  sb.append("&gt;"); break;
                case '"':  sb.append("&quot;"); break;
                case '\'': sb.append("&apos;"); break;
                default:   sb.append(c);
            }
        }
        return sb.toString();
    }

    /* --------------------------------------------------------- SOAP */

    /** SOAP 调用结果 */
    public static final class SoapResult {
        public final boolean ok;
        public final String error;
        public final Map<String, String> values;
        SoapResult(boolean ok, String error, Map<String, String> values) {
            this.ok = ok; this.error = error; this.values = values;
        }
        public String get(String k) { return values == null ? null : values.get(k); }
        public String get(String k, String def) {
            String v = get(k);
            return v == null ? def : v;
        }
        @Override public String toString() {
            return ok ? ("OK " + values) : ("ERR " + error);
        }
    }

    /**
     * 通用 UPnP SOAP 调用。
     * 约定：参数值以 '&lt;' 开头时按原始 XML 插入（用于 CurrentURIMetaData）。
     */
    public static SoapResult soapCall(String controlUrl, String serviceType, String action,
                                      Map<String, Object> args, int timeoutSec) {
        StringBuilder body = new StringBuilder();
        if (args != null) {
            for (Map.Entry<String, Object> e : args.entrySet()) {
                String v = e.getValue() == null ? "" : String.valueOf(e.getValue());
                String raw = v.startsWith("<") ? v : escapeXml(v);
                body.append('<').append(e.getKey()).append('>')
                    .append(raw)
                    .append("</").append(e.getKey()).append('>');
            }
        }
        String envelope = "<?xml version=\"1.0\" encoding=\"utf-8\"?>"
                + "<s:Envelope xmlns:s=\"http://schemas.xmlsoap.org/soap/envelope/\" "
                + "s:encodingStyle=\"http://schemas.xmlsoap.org/soap/encoding/\">"
                + "<s:Body><u:" + action + " xmlns:u=\"" + serviceType + "\">"
                + body
                + "</u:" + action + "></s:Body></s:Envelope>";

        HttpURLConnection c = null;
        try {
            byte[] payload = envelope.getBytes(Charset.forName("UTF-8"));
            c = (HttpURLConnection) new URL(controlUrl).openConnection();
            c.setRequestMethod("POST");
            c.setConnectTimeout(timeoutSec * 1000);
            c.setReadTimeout(timeoutSec * 1000);
            c.setDoOutput(true);
            c.setRequestProperty("Content-Type", "text/xml; charset=\"utf-8\"");
            c.setRequestProperty("SOAPAction", "\"" + serviceType + "#" + action + "\"");
            c.setRequestProperty("User-Agent", UA);
            c.setRequestProperty("Connection", "close");
            c.setFixedLengthStreamingMode(payload.length);
            OutputStream os = c.getOutputStream();
            os.write(payload);
            os.flush();
            os.close();

            int code = c.getResponseCode();
            InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
            String raw = readAll(in);
            if (code >= 400) {
                return new SoapResult(false, "HTTP " + code + ": " + trim(raw, 300), null);
            }
            return parseSoapResponse(raw, action);
        } catch (Exception e) {
            return new SoapResult(false, String.valueOf(e), null);
        } finally {
            if (c != null) try { c.disconnect(); } catch (Exception ignore) { }
        }
    }

    public static SoapResult soapCall(String controlUrl, String serviceType, String action,
                                      Map<String, Object> args) {
        return soapCall(controlUrl, serviceType, action, args, DEFAULT_TIMEOUT);
    }

    /** 解析 SOAP 响应体（含 UPnP 错误码解析） */
    public static SoapResult parseSoapResponse(String raw, String action) {
        // 有的设备会返回 200 + 空 body（或 HTML 错误页），直接丢给 XML 解析器会抛
        // 一堆 "前言中不允许有内容"。这里先挡掉，给出可读的失败原因。
        if (raw == null || raw.trim().isEmpty()) {
            return new SoapResult(false, "设备返回空响应", null);
        }
        if (raw.indexOf('<') < 0) {
            return new SoapResult(false, "设备返回的不是 XML: " + trim(raw, 120), null);
        }
        Document doc;
        try {
            doc = parseXml(raw);
        } catch (Exception e) {
            return new SoapResult(false, "XML 解析失败: " + e, null);
        }
        Element root = doc.getDocumentElement();
        Element bodyEl = findChild(root, "Body");
        Element fault = bodyEl != null ? findChild(bodyEl, "Fault") : null;
        if (fault == null) fault = findChild(root, "Fault");
        if (fault != null) {
            Element detail = findChild(fault, "detail");
            if (detail == null) detail = fault;
            Element err = findChild(detail, "UPnPError");
            String code = textOf(err, "errorCode", "?");
            String desc = textOf(err, "errorDescription", "");
            return new SoapResult(false, "UPnP 错误 " + code + ": " + desc, null);
        }

        Element resp = bodyEl != null ? findChild(bodyEl, action + "Response") : null;
        if (resp == null) resp = bodyEl != null ? bodyEl : root;

        Map<String, String> out = new LinkedHashMap<String, String>();
        if (resp != null) {
            NodeList kids = resp.getChildNodes();
            for (int i = 0; i < kids.getLength(); i++) {
                Node ch = kids.item(i);
                if (ch.getNodeType() != Node.ELEMENT_NODE) continue;
                String t = ch.getTextContent();
                out.put(ln(ch), t == null ? "" : t);
            }
        }
        return new SoapResult(true, null, out);
    }

    /* ------------------------------------------------------ DIDL-Lite */

    /** 构造 SetAVTransportURI 需要的 DIDL-Lite 元数据 */
    public static String buildDidl(String title, String url, String duration,
                                   String artist, String album,
                                   String mime, String pn, boolean rich) {
        if (mime == null) {
            String[] g = guessMime(url);
            mime = g[0];
            pn = g[1];
        }
        String protocol;
        if (rich && pn != null) {
            protocol = "http-get:*:" + mime + ":"
                    + "DLNA.ORG_PN=" + pn + ";DLNA.ORG_OP=01;DLNA.ORG_CI=0;"
                    + "DLNA.ORG_FLAGS=01700000000000000000000000000000";
        } else {
            protocol = "http-get:*:" + mime + ":*";
        }
        StringBuilder sb = new StringBuilder(512);
        sb.append("<DIDL-Lite xmlns=\"").append(DIDL_NS).append("\" xmlns:dc=\"").append(DC_NS)
          .append("\" xmlns:upnp=\"").append(UPNP_NS).append("\">")
          .append("<item id=\"0\" parentID=\"-1\" restricted=\"1\">")
          .append("<dc:title>").append(escapeXml(title)).append("</dc:title>")
          .append("<upnp:class>object.item.audioItem.musicTrack</upnp:class>");
        if (artist != null && !artist.isEmpty()) {
            sb.append("<upnp:artist role=\"Performer\">").append(escapeXml(artist)).append("</upnp:artist>")
              .append("<dc:creator>").append(escapeXml(artist)).append("</dc:creator>");
        }
        if (album != null && !album.isEmpty()) {
            sb.append("<upnp:album>").append(escapeXml(album)).append("</upnp:album>");
        }
        sb.append("<res protocolInfo=\"").append(protocol).append("\"");
        if (duration != null && !duration.isEmpty()) {
            sb.append(" duration=\"").append(duration).append("\"");
        }
        sb.append(">").append(escapeXml(url)).append("</res>")
          .append("</item></DIDL-Lite>");
        return sb.toString();
    }

    /** 解析 DIDL-Lite，返回条目列表 */
    public static List<Map<String, Object>> parseDidl(String didlText) {
        List<Map<String, Object>> items = new ArrayList<Map<String, Object>>();
        if (didlText == null || didlText.isEmpty()) return items;

        Document doc = null;
        try {
            doc = parseXml(didlText);
        } catch (Exception first) {
            // 有些服务端会二次转义，再试一次手工反转义
            String text = didlText.replace("&lt;", "<").replace("&gt;", ">")
                    .replace("&quot;", "\"").replace("&apos;", "'").replace("&amp;", "&");
            try { doc = parseXml(text); } catch (Exception ignore) { return items; }
        }
        Element root = doc.getDocumentElement();
        if (root == null) return items;

        NodeList kids = root.getChildNodes();
        for (int i = 0; i < kids.getLength(); i++) {
            Node node = kids.item(i);
            if (node.getNodeType() != Node.ELEMENT_NODE) continue;
            String tag = ln(node);
            if (!"item".equals(tag) && !"container".equals(tag)) continue;

            Element res = findChild(node, "res");
            String url = res != null && res.getTextContent() != null ? res.getTextContent().trim() : "";
            String dur = res != null ? res.getAttribute("duration") : "";
            Integer size = null;
            if (res != null && res.getAttribute("size") != null && !res.getAttribute("size").isEmpty()) {
                try { size = Integer.valueOf(res.getAttribute("size")); } catch (NumberFormatException ignore) { }
            }
            Map<String, Object> m = new LinkedHashMap<String, Object>();
            m.put("id", node instanceof Element ? ((Element) node).getAttribute("id") : "");
            m.put("parent_id", node instanceof Element ? ((Element) node).getAttribute("parentID") : "");
            m.put("type", tag);
            m.put("title", textOf(node, "title"));
            String artist = textOf(node, "artist");
            if (artist.isEmpty()) artist = textOf(node, "creator");
            m.put("artist", artist);
            m.put("album", textOf(node, "album"));
            m.put("class", textOf(node, "class"));
            m.put("url", url);
            m.put("duration", dur == null ? "" : dur);
            m.put("size", size);
            m.put("protocol", res != null ? res.getAttribute("protocolInfo") : "");
            items.add(m);
        }
        return items;
    }

    /* --------------------------------------------------- 设备描述解析 */

    /** 一个 UPnP 设备 */
    public static final class DeviceInfo {
        public String ip = "";
        public String location = "";
        public String deviceType = "";
        public String friendlyName = "";
        public String manufacturer = "";
        public String modelName = "";
        public String modelDescription = "";
        public String udn = "";
        public String baseUrl = "";
        public final Map<String, Service> services = new LinkedHashMap<String, Service>();

        public static final class Service {
            public String control = "";
            public String event = "";
        }

        public boolean isRenderer() {
            return deviceType.contains("MediaRenderer") && services.containsKey(AVT);
        }
        public boolean isServer() {
            return deviceType.contains("MediaServer") && services.containsKey(CD);
        }
        public String name() { return friendlyName == null || friendlyName.isEmpty() ? ip : friendlyName; }

        public Map<String, Object> toMap() {
            Map<String, Object> m = new LinkedHashMap<String, Object>();
            m.put("ip", ip);
            m.put("name", name());
            m.put("udn", udn);
            m.put("model", modelName);
            m.put("manufacturer", manufacturer);
            m.put("location", location);
            m.put("device_type", deviceType);
            m.put("has_volume", services.containsKey(RC));
            return m;
        }
    }

    private static final Pattern ORIGIN = Pattern.compile("(https?://[^/]+)");

    /** 抓取并解析设备描述 XML；失败返回 null */
    public static DeviceInfo fetchDescription(String location, int timeoutSec) {
        String xmlText;
        try {
            xmlText = httpGet(location, timeoutSec);
        } catch (Exception e) {
            return null;
        }
        Document doc;
        try {
            doc = parseXml(xmlText);
        } catch (Exception e) {
            return null;
        }
        Element root = doc.getDocumentElement();
        String base = location;
        Element ub = findChild(root, "URLBase");
        if (ub != null && ub.getTextContent() != null && !ub.getTextContent().trim().isEmpty()) {
            base = ub.getTextContent().trim();
        }
        Element dev = findChild(root, "device");
        if (dev == null) return null;

        DeviceInfo info = new DeviceInfo();
        info.location = location;
        info.baseUrl = base;
        info.deviceType = textOf(dev, "deviceType");
        info.friendlyName = textOf(dev, "friendlyName");
        info.manufacturer = textOf(dev, "manufacturer");
        info.modelName = textOf(dev, "modelName");
        info.modelDescription = textOf(dev, "modelDescription");
        info.udn = textOf(dev, "UDN");

        Element sl = findChild(dev, "serviceList");
        for (Element svc : findallChild(sl, "service")) {
            String st = textOf(svc, "serviceType");
            String ct = textOf(svc, "controlURL");
            String et = textOf(svc, "eventSubURL");
            if (st.isEmpty()) continue;
            if (!ct.isEmpty() && !ct.startsWith("http")) {
                Matcher m = ORIGIN.matcher(base);
                String origin = m.find() ? m.group(1) : base;
                ct = origin + (ct.startsWith("/") ? "" : "/") + ct;
            }
            DeviceInfo.Service s = new DeviceInfo.Service();
            s.control = ct;
            s.event = et;
            info.services.put(st, s);
        }
        return info;
    }

    /* ------------------------------------------------------ SSDP 发现 */

    /** 从指定网卡 IP 发送一次 M-SEARCH，返回 {ip: location} */
    public static Map<String, String> ssdpSearch(String localIp, String st, int timeoutSec, int mx) {
        Map<String, String> found = new LinkedHashMap<String, String>();
        String msg = "M-SEARCH * HTTP/1.1\r\n"
                + "HOST: " + SSDP_ADDR + ":" + SSDP_PORT + "\r\n"
                + "MAN: \"ssdp:discover\"\r\n"
                + "MX: " + mx + "\r\n"
                + "ST: " + st + "\r\n"
                + "\r\n";
        DatagramSocket sock = null;
        try {
            byte[] data = msg.getBytes(Charset.forName("UTF-8"));
            sock = new DatagramSocket(null);
            sock.setReuseAddress(true);
            sock.setBroadcast(true);
            InetAddress bind = "0.0.0.0".equals(localIp)
                    ? null : InetAddress.getByName(localIp);
            sock.bind(bind == null ? new InetSocketAddress(0) : new InetSocketAddress(bind, 0));
            sock.setSoTimeout(timeoutSec * 1000);
            // 说明：不设置 IP_MULTICAST_TTL —— DatagramSocket.setOption 需要 Java 9 /
            // Android API 33，而 SSDP 只在同一广播域内有效，TTL 用默认值 1 即可。
            sock.send(new DatagramPacket(data, data.length,
                    InetAddress.getByName(SSDP_ADDR), SSDP_PORT));

            byte[] buf = new byte[65535];
            long deadline = System.currentTimeMillis() + timeoutSec * 1000L;
            while (System.currentTimeMillis() < deadline) {
                DatagramPacket pkt = new DatagramPacket(buf, buf.length);
                try {
                    sock.receive(pkt);
                } catch (java.net.SocketTimeoutException te) {
                    break;
                } catch (Exception e) {
                    break;
                }
                String text = new String(pkt.getData(), 0, pkt.getLength(), Charset.forName("UTF-8"));
                Matcher m = Pattern.compile("^LOCATION:\\s*(\\S+)", Pattern.MULTILINE | Pattern.CASE_INSENSITIVE)
                        .matcher(text);
                if (m.find()) {
                    String ip = pkt.getAddress().getHostAddress();
                    if (!found.containsKey(ip)) found.put(ip, m.group(1).trim());
                }
            }
        } catch (Exception ignore) {
            // 与 Python 版一致：静默失败，交由上层用其它网卡重试
        } finally {
            if (sock != null) try { sock.close(); } catch (Exception ignore) { }
        }
        return found;
    }

    /** 多网卡并发 SSDP 发现，返回去重后的设备列表（已抓取描述） */
    public static List<DeviceInfo> discover(List<String> searchTargets, String preferNet,
                                            int timeoutSec, int workers) {
        if (searchTargets == null || searchTargets.isEmpty()) {
            searchTargets = new ArrayList<String>();
            searchTargets.add("upnp:rootdevice");
            searchTargets.add("urn:schemas-upnp-org:device:MediaRenderer:1");
        }
        List<String> ips = pickIps(preferNet);
        final Map<String, String> locations = Collections.synchronizedMap(new LinkedHashMap<String, String>());

        List<Callable<Void>> tasks = new ArrayList<Callable<Void>>();
        for (final String ip : ips) {
            for (final String st : searchTargets) {
                tasks.add(new Callable<Void>() {
                    @Override public Void call() {
                        Map<String, String> r = ssdpSearch(ip, st, timeoutSec, Math.max(1, Math.min(3, timeoutSec)));
                        synchronized (locations) {
                            for (Map.Entry<String, String> e : r.entrySet()) {
                                if (!locations.containsKey(e.getKey())) locations.put(e.getKey(), e.getValue());
                            }
                        }
                        return null;
                    }
                });
            }
        }
        runAll(tasks, Math.max(1, Math.min(workers, tasks.size())));

        List<DeviceInfo> devices = new ArrayList<DeviceInfo>();
        Set<String> seenUdn = new LinkedHashSet<String>();
        List<Callable<DeviceInfo>> fetches = new ArrayList<Callable<DeviceInfo>>();
        for (final Map.Entry<String, String> e : locations.entrySet()) {
            fetches.add(new Callable<DeviceInfo>() {
                @Override public DeviceInfo call() {
                    DeviceInfo d = fetchDescription(e.getValue(), DEFAULT_TIMEOUT);
                    if (d != null) d.ip = e.getKey();
                    return d;
                }
            });
        }
        for (DeviceInfo d : runAll(fetches, Math.max(1, Math.min(16, fetches.size())))) {
            if (d == null) continue;
            if (!seenUdn.add(d.udn)) continue;
            devices.add(d);
        }
        Collections.sort(devices, new java.util.Comparator<DeviceInfo>() {
            @Override public int compare(DeviceInfo a, DeviceInfo b) {
                return a.ip.compareTo(b.ip);
            }
        });
        return devices;
    }

    public static List<DeviceInfo> discover(String preferNet, int timeoutSec) {
        return discover(null, preferNet, timeoutSec, 8);
    }

    /** 全默认搜索目标（rootdevice + MediaRenderer），指定超时与并发 */
    public static List<DeviceInfo> discover(int timeoutSec, int workers) {
        return discover(null, null, timeoutSec, workers);
    }

    private static <T> List<T> runAll(List<Callable<T>> tasks, int workers) {
        List<T> out = new ArrayList<T>();
        if (tasks.isEmpty()) return out;
        ExecutorService ex = Executors.newFixedThreadPool(workers);
        try {
            List<Future<T>> futs = new ArrayList<Future<T>>();
            for (Callable<T> t : tasks) futs.add(ex.submit(t));
            for (Future<T> f : futs) {
                try { out.add(f.get(30, TimeUnit.SECONDS)); } catch (Exception ignore) { }
            }
        } finally {
            ex.shutdownNow();
        }
        return out;
    }

    /* --------------------------------------------------- Renderer 封装 */

    /** 一个 DLNA 渲染器（音响）的控制封装 */
    public static final class Renderer {
        public final DeviceInfo info;
        public final String ip, name, udn, location, manufacturer, model;
        private final Map<String, DeviceInfo.Service> services;
        /** Amlogic 类渲染器对精简 metadata 兼容性更好 */
        public final boolean richMetadata;

        public Renderer(DeviceInfo info) {
            this.info = info;
            this.ip = info.ip;
            this.name = info.name();
            this.udn = info.udn;
            this.location = info.location;
            this.manufacturer = info.manufacturer == null ? "" : info.manufacturer;
            this.model = info.modelName == null ? "" : info.modelName;
            this.services = info.services;
            String m = (this.manufacturer + " " + this.model).toLowerCase(Locale.ROOT);
            this.richMetadata = !m.contains("amlogic");
        }

        private String ctrl(String svc) {
            DeviceInfo.Service s = services.get(svc);
            return s == null ? null : s.control;
        }

        private SoapResult action(String svc, String act, Map<String, Object> args, int timeoutSec) {
            String url = ctrl(svc);
            if (url == null || url.isEmpty()) {
                return new SoapResult(false, "设备不支持服务 " + svc, null);
            }
            return soapCall(url, svc, act, args, timeoutSec);
        }

        private static Map<String, Object> args(Object... kv) {
            Map<String, Object> m = new LinkedHashMap<String, Object>();
            for (int i = 0; i + 1 < kv.length; i += 2) m.put(String.valueOf(kv[i]), kv[i + 1]);
            return m;
        }

        /** 设置播放地址（不自动播放） */
        public SoapResult setUri(String url, String title, String duration, String artist,
                                 String album, String mime, String pn, int timeoutSec) {
            if (title == null || title.isEmpty()) {
                int s = url.lastIndexOf('/');
                title = s >= 0 ? url.substring(s + 1) : url;
            }
            String meta = buildDidl(title, url, duration == null ? "" : duration,
                    artist, album, mime, pn, richMetadata);
            return action(AVT, "SetAVTransportURI",
                    args("InstanceID", 0, "CurrentURI", url, "CurrentURIMetaData", meta), timeoutSec);
        }

        public SoapResult setUri(String url, String title) {
            return setUri(url, title, "", "", "", null, null, 8);
        }

        /** 预置下一曲（部分设备支持，用于无缝续播） */
        public SoapResult setNextUri(String url, String title, String duration, String artist,
                                     String mime, String pn) {
            if (title == null || title.isEmpty()) {
                int s = url.lastIndexOf('/');
                title = s >= 0 ? url.substring(s + 1) : url;
            }
            String meta = buildDidl(title, url, duration == null ? "" : duration,
                    artist, "", mime, pn, richMetadata);
            return action(AVT, "SetNextAVTransportURI",
                    args("InstanceID", 0, "NextURI", url, "NextURIMetaData", meta), DEFAULT_TIMEOUT);
        }

        public SoapResult play() {
            return action(AVT, "Play", args("InstanceID", 0, "Speed", "1"), DEFAULT_TIMEOUT);
        }
        public SoapResult play(String speed) {
            return action(AVT, "Play", args("InstanceID", 0, "Speed", speed), DEFAULT_TIMEOUT);
        }
        public SoapResult pause() { return action(AVT, "Pause", args("InstanceID", 0), DEFAULT_TIMEOUT); }
        public SoapResult stop()  { return action(AVT, "Stop",  args("InstanceID", 0), DEFAULT_TIMEOUT); }
        public SoapResult nextTrack() { return action(AVT, "Next", args("InstanceID", 0), DEFAULT_TIMEOUT); }
        public SoapResult prevTrack() { return action(AVT, "Previous", args("InstanceID", 0), DEFAULT_TIMEOUT); }

        public SoapResult seek(String target) {
            return action(AVT, "Seek", args("InstanceID", 0, "Unit", "REL_TIME", "Target", target), DEFAULT_TIMEOUT);
        }

        /** 一步到位：设置 URI 并播放 */
        public SoapResult playUri(String url, String title) {
            SoapResult r = setUri(url, title);
            if (!r.ok) return r;
            try { Thread.sleep(120); } catch (InterruptedException ignore) { }
            return play();
        }

        public SoapResult setVolume(int volume) {
            int v = Math.max(0, Math.min(100, volume));
            return action(RC, "SetVolume",
                    args("InstanceID", 0, "Channel", "Master", "DesiredVolume", v), DEFAULT_TIMEOUT);
        }

        /** 返回 {ok, volume} —— 成功时 values 里带 CurrentVolume */
        public SoapResult getVolume() {
            return action(RC, "GetVolume", args("InstanceID", 0, "Channel", "Master"), DEFAULT_TIMEOUT);
        }

        public SoapResult setMute(boolean mute) {
            return action(RC, "SetMute",
                    args("InstanceID", 0, "Channel", "Master", "DesiredMute", mute ? 1 : 0), DEFAULT_TIMEOUT);
        }

        public SoapResult getMute() {
            return action(RC, "GetMute", args("InstanceID", 0, "Channel", "Master"), DEFAULT_TIMEOUT);
        }

        /** PLAYING / PAUSED_PLAYBACK / STOPPED / TRANSITIONING */
        public SoapResult getTransportInfo() {
            return action(AVT, "GetTransportInfo", args("InstanceID", 0), 4);
        }

        /** {track,duration,position,abs_time,uri,title,artist} */
        public SoapResult getPositionInfo() {
            SoapResult r = action(AVT, "GetPositionInfo", args("InstanceID", 0), 4);
            if (!r.ok) return r;
            String trackMeta = r.get("TrackMetaData", "");
            String title = "", artist = "";
            if (trackMeta != null && !trackMeta.isEmpty()) {
                List<Map<String, Object>> items = parseDidl(trackMeta);
                if (!items.isEmpty()) {
                    title = str(items.get(0).get("title"));
                    artist = str(items.get(0).get("artist"));
                }
            }
            Map<String, String> out = new LinkedHashMap<String, String>();
            out.put("track", r.get("Track", "0"));
            out.put("duration", r.get("TrackDuration", "00:00:00"));
            out.put("position", r.get("RelTime", "00:00:00"));
            out.put("abs_time", r.get("AbsTime", "00:00:00"));
            out.put("uri", r.get("TrackURI", ""));
            out.put("title", title);
            out.put("artist", artist);
            return new SoapResult(true, null, out);
        }

        public SoapResult getMediaInfo() {
            return action(AVT, "GetMediaInfo", args("InstanceID", 0), 4);
        }

        /** 综合状态快照 */
        public Map<String, Object> status() {
            Map<String, Object> out = new LinkedHashMap<String, Object>();
            out.put("ip", ip);
            out.put("name", name);
            out.put("udn", udn);
            out.put("model", model);
            out.put("manufacturer", manufacturer);
            out.put("online", false);
            out.put("state", "UNKNOWN");
            out.put("volume", null);
            out.put("mute", null);
            out.put("position", null);
            out.put("duration", null);
            out.put("position_sec", 0);
            out.put("duration_sec", 0);
            out.put("title", null);
            out.put("artist", null);
            out.put("uri", null);

            SoapResult st = getTransportInfo();
            if (!st.ok) return out;
            out.put("online", true);
            out.put("state", st.get("CurrentTransportState", "UNKNOWN"));

            SoapResult v = getVolume();
            if (v.ok && v.get("CurrentVolume") != null) {
                try { out.put("volume", Integer.valueOf(v.get("CurrentVolume").trim())); } catch (Exception ignore) { }
            }
            SoapResult p = getPositionInfo();
            if (p.ok) {
                out.put("position", p.get("position"));
                out.put("duration", p.get("duration"));
                out.put("title", p.get("title"));
                out.put("artist", p.get("artist"));
                out.put("uri", p.get("uri"));
                out.put("position_sec", tsecToSec(p.get("position", "")));
                out.put("duration_sec", tsecToSec(p.get("duration", "")));
            }
            return out;
        }

        /** 轻量状态快照（调度器高频调用用） */
        public Map<String, Object> quickStatus() {
            Map<String, Object> out = new LinkedHashMap<String, Object>();
            out.put("ip", ip);
            out.put("udn", udn);
            out.put("online", false);
            out.put("state", "UNKNOWN");
            out.put("position_sec", 0);
            out.put("duration_sec", 0);
            out.put("uri", null);
            out.put("title", null);

            SoapResult st = getTransportInfo();
            if (!st.ok) return out;
            out.put("online", true);
            out.put("state", st.get("CurrentTransportState", "UNKNOWN"));
            SoapResult p = getPositionInfo();
            if (p.ok) {
                out.put("position_sec", tsecToSec(p.get("position", "")));
                out.put("duration_sec", tsecToSec(p.get("duration", "")));
                out.put("uri", p.get("uri"));
                out.put("title", p.get("title"));
            }
            return out;
        }
    }

    /* -------------------------------------------------- MediaServer */

    /** DLNA 媒体服务器（如 MiniDLNA）内容浏览封装 */
    public static final class MediaServer {
        public final DeviceInfo info;
        public final String ip, name, udn;
        private final String control;

        public MediaServer(DeviceInfo info) {
            this.info = info;
            this.ip = info.ip;
            this.name = info.name();
            this.udn = info.udn;
            DeviceInfo.Service s = info.services.get(CD);
            this.control = s == null ? null : s.control;
        }

        /** 返回 {ok, items, total}；失败时 items 为错误字符串 */
        public BrowseResult browse(String objectId, int start, int count, String sort) {
            if (control == null || control.isEmpty()) {
                return BrowseResult.fail("该设备没有 ContentDirectory 服务");
            }
            Map<String, Object> a = new LinkedHashMap<String, Object>();
            a.put("ObjectID", objectId);
            a.put("BrowseFlag", "BrowseDirectChildren");
            a.put("Filter", "*");
            a.put("StartingIndex", start);
            a.put("RequestedCount", count);
            a.put("SortCriteria", sort == null ? "" : sort);
            SoapResult r = soapCall(control, CD, "Browse", a, 10);
            if (!r.ok) return BrowseResult.fail(r.error);
            List<Map<String, Object>> items = parseDidl(r.get("Result", ""));
            int total = items.size();
            try { total = Integer.parseInt(r.get("TotalMatches", String.valueOf(items.size()))); } catch (Exception ignore) { }
            return new BrowseResult(true, items, total, null);
        }

        /** 关键字搜索（MiniDLNA 支持 Search） */
        public BrowseResult search(String keyword, String container, int count) {
            if (control == null || control.isEmpty()) return BrowseResult.fail("无 ContentDirectory 服务");
            Map<String, Object> a = new LinkedHashMap<String, Object>();
            a.put("ContainerID", container);
            a.put("SearchCriteria", "(dc:title contains \"" + keyword + "\")");
            a.put("Filter", "*");
            a.put("StartingIndex", 0);
            a.put("RequestedCount", count);
            a.put("SortCriteria", "");
            SoapResult r = soapCall(control, CD, "Search", a, 10);
            if (!r.ok) return BrowseResult.fail(r.error);
            List<Map<String, Object>> items = parseDidl(r.get("Result", ""));
            int total = items.size();
            try { total = Integer.parseInt(r.get("TotalMatches", String.valueOf(items.size()))); } catch (Exception ignore) { }
            return new BrowseResult(true, items, total, null);
        }

        public Map<String, Object> toMap() {
            Map<String, Object> m = new LinkedHashMap<String, Object>();
            m.put("ip", ip);
            m.put("name", name);
            m.put("udn", udn);
            m.put("control", control);
            return m;
        }
    }

    /** MediaServer 浏览结果 */
    public static final class BrowseResult {
        public final boolean ok;
        public final List<Map<String, Object>> items;
        public final int total;
        public final String error;
        BrowseResult(boolean ok, List<Map<String, Object>> items, int total, String error) {
            this.ok = ok; this.items = items; this.total = total; this.error = error;
        }
        static BrowseResult fail(String err) { return new BrowseResult(false, null, 0, err); }
    }

    /* ------------------------------------------------------- 工具 */

    private static String str(Object o) { return o == null ? "" : String.valueOf(o); }

    /** '01:02:03' -> 3723 */
    public static int tsecToSec(String t) {
        if (t == null || t.isEmpty() || "NOT_IMPLEMENTED".equals(t) || "0".equals(t)) return 0;
        try {
            String[] parts = t.split(":");
            if (parts.length == 3) {
                return Integer.parseInt(parts[0]) * 3600
                        + Integer.parseInt(parts[1]) * 60 + Integer.parseInt(parts[2]);
            }
            if (parts.length == 2) {
                return Integer.parseInt(parts[0]) * 60 + Integer.parseInt(parts[1]);
            }
            if (parts.length == 1) return Integer.parseInt(parts[0]);
        } catch (Exception ignore) { }
        return 0;
    }

    /** 3723 -> '01:02:03' */
    public static String secToTsec(int s) {
        if (s < 0) s = 0;
        int h = s / 3600, rem = s % 3600, m = rem / 60, sec = rem % 60;
        return String.format(Locale.ROOT, "%02d:%02d:%02d", h, m, sec);
    }

    /** 把各种时长写法规范化成 DLNA 要求的 H:MM:SS（如 '0:03:24.097' -> '0:03:24'） */
    public static String normDuration(String d) {
        if (d == null || d.isEmpty()) return "";
        String s = d.trim();
        if ("NOT_IMPLEMENTED".equals(s) || "0".equals(s) || "00:00:00".equals(s) || "-1".equals(s)) return "";
        int dot = s.indexOf('.');
        if (dot > 0) s = s.substring(0, dot);
        int comma = s.indexOf(',');
        if (comma > 0) s = s.substring(0, comma);
        String[] parts = s.split(":");
        try {
            if (parts.length == 3) {
                int h = Integer.parseInt(parts[0]), m = Integer.parseInt(parts[1]), sec = Integer.parseInt(parts[2]);
                return h + ":" + String.format(Locale.ROOT, "%02d:%02d", m, sec);
            }
            if (parts.length == 2) {
                int m = Integer.parseInt(parts[0]), sec = Integer.parseInt(parts[1]);
                return "0:" + String.format(Locale.ROOT, "%02d:%02d", m, sec);
            }
            if (parts.length == 1) {
                int total = Integer.parseInt(parts[0]);
                return "0:" + String.format(Locale.ROOT, "%02d:%02d", total / 60, total % 60);
            }
        } catch (Exception ignore) { }
        return s;
    }
}
