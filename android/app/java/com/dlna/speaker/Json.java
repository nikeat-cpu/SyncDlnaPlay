package com.dlna.speaker;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 极简 JSON 解析 / 序列化（不依赖 org.json）
 * ==========================================
 * 刻意不用 Android 的 org.json：自己实现可以让整个服务端在桌面 JVM 上编译运行，
 * 从而能在 PC 上把全部 API 端到端跑一遍再装到手机上。
 */
public final class Json {

    private Json() {}

    /* --------------------------------------------------------- 构造助手 */

    public static Map<String, Object> map() { return new LinkedHashMap<String, Object>(); }

    public static Map<String, Object> map(Object... kv) {
        Map<String, Object> m = new LinkedHashMap<String, Object>();
        for (int i = 0; i + 1 < kv.length; i += 2) m.put(String.valueOf(kv[i]), kv[i + 1]);
        return m;
    }

    public static List<Object> list() { return new ArrayList<Object>(); }

    public static List<Object> list(Object... items) {
        List<Object> l = new ArrayList<Object>();
        for (Object o : items) l.add(o);
        return l;
    }

    /* --------------------------------------------------------- 取值助手 */

    @SuppressWarnings("unchecked")
    public static Map<String, Object> asMap(Object o) {
        return o instanceof Map ? (Map<String, Object>) o : new LinkedHashMap<String, Object>();
    }

    @SuppressWarnings("unchecked")
    public static List<Object> asList(Object o) {
        return o instanceof List ? (List<Object>) o : new ArrayList<Object>();
    }

    public static String s(Map<String, Object> m, String k, String def) {
        if (m == null) return def;
        Object v = m.get(k);
        return v == null ? def : String.valueOf(v);
    }

    public static String s(Map<String, Object> m, String k) { return s(m, k, ""); }

    public static int i(Map<String, Object> m, String k, int def) {
        if (m == null) return def;
        Object v = m.get(k);
        if (v instanceof Number) return ((Number) v).intValue();
        if (v instanceof String) {
            try { return (int) Double.parseDouble(((String) v).trim()); } catch (Exception ignore) { }
        }
        return def;
    }

    public static long l(Map<String, Object> m, String k, long def) {
        if (m == null) return def;
        Object v = m.get(k);
        if (v instanceof Number) return ((Number) v).longValue();
        if (v instanceof String) {
            try { return (long) Double.parseDouble(((String) v).trim()); } catch (Exception ignore) { }
        }
        return def;
    }

    public static boolean b(Map<String, Object> m, String k, boolean def) {
        if (m == null) return def;
        Object v = m.get(k);
        if (v instanceof Boolean) return (Boolean) v;
        if (v instanceof String) return "true".equalsIgnoreCase((String) v) || "1".equals(v);
        if (v instanceof Number) return ((Number) v).intValue() != 0;
        return def;
    }

    /* --------------------------------------------------------- 解析 */

    public static Object parse(String text) {
        if (text == null) return null;
        P p = new P(text);
        p.ws();
        if (p.end()) return null;
        Object v = p.value();
        return v;
    }

    /** 解析失败时返回空 Map，避免调用方到处判空 */
    public static Map<String, Object> parseObject(String text) {
        Object o = parse(text);
        return asMap(o);
    }

    private static final class P {
        private final String s;
        private int i;

        P(String s) { this.s = s; this.i = 0; }

        boolean end() { return i >= s.length(); }

        void ws() {
            while (i < s.length()) {
                char c = s.charAt(i);
                if (c == ' ' || c == '\t' || c == '\n' || c == '\r') i++;
                else break;
            }
        }

        Object value() {
            ws();
            if (end()) return null;
            char c = s.charAt(i);
            switch (c) {
                case '{': return object();
                case '[': return array();
                case '"': return string();
                case 't': expect("true"); return Boolean.TRUE;
                case 'f': expect("false"); return Boolean.FALSE;
                case 'n': expect("null"); return null;
                default: return number();
            }
        }

        void expect(String word) {
            if (s.startsWith(word, i)) i += word.length();
            else throw new IllegalArgumentException("JSON 解析错误，位置 " + i);
        }

        Map<String, Object> object() {
            Map<String, Object> m = new LinkedHashMap<String, Object>();
            i++;                        // {
            ws();
            if (!end() && s.charAt(i) == '}') { i++; return m; }
            while (!end()) {
                ws();
                if (end() || s.charAt(i) != '"') break;
                String k = string();
                ws();
                if (end() || s.charAt(i) != ':') break;
                i++;
                m.put(k, value());
                ws();
                if (!end() && s.charAt(i) == ',') { i++; continue; }
                if (!end() && s.charAt(i) == '}') { i++; break; }
                break;
            }
            return m;
        }

        List<Object> array() {
            List<Object> l = new ArrayList<Object>();
            i++;                        // [
            ws();
            if (!end() && s.charAt(i) == ']') { i++; return l; }
            while (!end()) {
                l.add(value());
                ws();
                if (!end() && s.charAt(i) == ',') { i++; continue; }
                if (!end() && s.charAt(i) == ']') { i++; break; }
                break;
            }
            return l;
        }

        String string() {
            StringBuilder sb = new StringBuilder();
            i++;                        // 开引号
            while (!end()) {
                char c = s.charAt(i++);
                if (c == '"') break;
                if (c != '\\') { sb.append(c); continue; }
                if (end()) break;
                char e = s.charAt(i++);
                switch (e) {
                    case 'n': sb.append('\n'); break;
                    case 't': sb.append('\t'); break;
                    case 'r': sb.append('\r'); break;
                    case 'b': sb.append('\b'); break;
                    case 'f': sb.append('\f'); break;
                    case '/': sb.append('/'); break;
                    case '\\': sb.append('\\'); break;
                    case '"': sb.append('"'); break;
                    case 'u':
                        if (i + 4 <= s.length()) {
                            try {
                                sb.append((char) Integer.parseInt(s.substring(i, i + 4), 16));
                                i += 4;
                            } catch (NumberFormatException ignore) { }
                        }
                        break;
                    default: sb.append(e);
                }
            }
            return sb.toString();
        }

        Object number() {
            int start = i;
            while (i < s.length()) {
                char c = s.charAt(i);
                if (c == '-' || c == '+' || c == '.' || c == 'e' || c == 'E' || (c >= '0' && c <= '9')) i++;
                else break;
            }
            String num = s.substring(start, i);
            try {
                if (num.indexOf('.') < 0 && num.indexOf('e') < 0 && num.indexOf('E') < 0) {
                    return Long.valueOf(Long.parseLong(num));
                }
                return Double.valueOf(Double.parseDouble(num));
            } catch (NumberFormatException e) {
                return null;
            }
        }
    }

    /* --------------------------------------------------------- 序列化 */

    public static String write(Object o) {
        StringBuilder sb = new StringBuilder(256);
        writeTo(sb, o);
        return sb.toString();
    }

    @SuppressWarnings("unchecked")
    private static void writeTo(StringBuilder sb, Object o) {
        if (o == null) { sb.append("null"); return; }
        if (o instanceof String) { writeString(sb, (String) o); return; }
        if (o instanceof Boolean) { sb.append(((Boolean) o) ? "true" : "false"); return; }
        if (o instanceof Double || o instanceof Float) {
            double d = ((Number) o).doubleValue();
            if (Double.isNaN(d) || Double.isInfinite(d)) sb.append("null");
            else sb.append(trimDouble(d));
            return;
        }
        if (o instanceof Number) { sb.append(o.toString()); return; }
        if (o instanceof Map) {
            sb.append('{');
            boolean first = true;
            for (Map.Entry<String, Object> e : ((Map<String, Object>) o).entrySet()) {
                if (!first) sb.append(',');
                first = false;
                writeString(sb, e.getKey());
                sb.append(':');
                writeTo(sb, e.getValue());
            }
            sb.append('}');
            return;
        }
        if (o instanceof Iterable) {
            sb.append('[');
            boolean first = true;
            for (Object one : (Iterable<Object>) o) {
                if (!first) sb.append(',');
                first = false;
                writeTo(sb, one);
            }
            sb.append(']');
            return;
        }
        if (o instanceof Object[]) {
            sb.append('[');
            Object[] arr = (Object[]) o;
            for (int k = 0; k < arr.length; k++) {
                if (k > 0) sb.append(',');
                writeTo(sb, arr[k]);
            }
            sb.append(']');
            return;
        }
        writeString(sb, String.valueOf(o));
    }

    private static String trimDouble(double d) {
        if (d == Math.rint(d) && Math.abs(d) < 1e15) {
            return String.valueOf((long) d);
        }
        return String.valueOf(d);
    }

    private static void writeString(StringBuilder sb, String v) {
        sb.append('"');
        for (int i = 0; i < v.length(); i++) {
            char c = v.charAt(i);
            switch (c) {
                case '"': sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                case '\b': sb.append("\\b"); break;
                case '\f': sb.append("\\f"); break;
                default:
                    if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
                    else sb.append(c);
            }
        }
        sb.append('"');
    }
}
