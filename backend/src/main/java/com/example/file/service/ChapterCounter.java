package com.example.file.service;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 数小说章节数：逐行识别章节标题再计数（不看最后一章写的是第几章）。
 * 规则与 python-service/app/text_loader.py 的 detect_heading / find_headings / split_book 一致（两边一起改），
 * 说明见 docs/素材提取改造方案.md 第二节：
 * <ul>
 *   <li>章级标题「第X章 / 回 / 节 / 话」「Chapter N」；卷级「第X卷 / 集 / 部 / 篇」「卷X」「上部　面壁者」；特殊标题 序章 / 楔子 / 尾声 / 番外 …；</li>
 *   <li>可带「正文 / 正文卷 / VIP章节」前缀；编号后没有分隔就接正文的不算（章级：带「。」或以英文句点结尾；卷级 / 特殊：带任何标点）；</li>
 *   <li>卷名后面带着章号（「第二十七卷红色星期五第十六章…」）算章；</li>
 *   <li>书里有章级标题时卷标题只断开：卷下正文 ≥ 200 字才算一个单元；没有章级时卷标题当章；都没有时「1.标题 / 一、标题」兜底且至少 3 处；</li>
 *   <li>标题下没有正文的不算，首个标题前的文字（开篇 / 书头）不算；没有章节结构返回 0（Python 那边会按字数分段，不算章）。</li>
 * </ul>
 */
public final class ChapterCounter {

    private ChapterCounter() {
    }

    private static final int FLAGS = Pattern.CASE_INSENSITIVE | Pattern.UNICODE_CASE | Pattern.UNICODE_CHARACTER_CLASS
            | Pattern.DOTALL;
    private static final String EN_NUM = "(?:\\d+|[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"
            + "|[a-z]+teen|(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[- ][a-z]+)?)";
    private static final String NUM = "[零〇一二三四五六七八九十百千万两\\d０-９]+";
    private static final String SPECIAL_CORE = "(?:序[ \\t　]*章|序言|序|前言|楔子|引子|尾[ \\t　]*声|后[ \\t　]*记|番外|prologue|epilogue)";
    private static final String SEPARATORS = " \t　:：、.．-—·（(【[《";

    private static final Pattern PREFIX = Pattern.compile("^(?:正文卷|正文|VIP[ \\t　]*章节)[ \\t　]*", FLAGS);
    private static final Pattern CHAPTER_HEAD = Pattern.compile("^(第[ \\t　]*" + NUM + "[ \\t　]*[章回节话])(.{0,30})$", FLAGS);
    private static final Pattern VOLUME_HEAD = Pattern.compile("^(第[ \\t　]*" + NUM + "[ \\t　]*[卷集部篇]|卷[ \\t　]*" + NUM + ")(.{0,30})$", FLAGS);
    private static final Pattern EMBEDDED_CHAPTER = Pattern.compile("第[ \\t　]*" + NUM + "[ \\t　]*[章回节话]", FLAGS);
    private static final Pattern PART_HEAD = Pattern.compile("^[上中下]部[ \\t　]+[^\\s，。！？“”：；…][^，。！？“”：；…]{0,15}$", FLAGS);
    private static final Pattern EN_HEAD = Pattern.compile("^(chapter[ \\t]+" + EN_NUM + ")\\b(.{0,60})$", FLAGS);
    private static final Pattern SPECIAL_HEAD = Pattern.compile("^(" + SPECIAL_CORE + ")(.{0,20})$", FLAGS);
    private static final Pattern SPECIAL_ONLY = Pattern.compile(SPECIAL_CORE, FLAGS);
    private static final Pattern STRICT_PUNCT = Pattern.compile("[。！？!?…，,；;]");
    private static final Pattern NUMBERED_RE = Pattern.compile(
            "^((?:\\d{1,4}|[一二三四五六七八九十百]{1,4})[.、．][ \\t]*[^\\s\\d][^\\n]{0,24}?|" + SPECIAL_CORE + ")[ \\t]*$"
                    + "(?<![。！？!?”…：:，,；;])",
            Pattern.CASE_INSENSITIVE | Pattern.UNICODE_CASE | Pattern.MULTILINE | Pattern.UNICODE_CHARACTER_CLASS);

    static final int VOLUME_INTRO_MIN_CHARS = 200;

    private static final String CHAPTER = "chapter";
    private static final String VOLUME = "volume";
    private static final String SPECIAL = "special";

    /** 一个标题行：在全文中的 [start, end)、类别、标题 */
    record Head(int start, int end, String kind, String title) {
    }

    /** 章节数；识别不到章节结构返回 0 */
    public static int count(String text) {
        if (text == null || text.isEmpty()) {
            return 0;
        }
        text = text.replace("\r\n", "\n").replace('\r', '\n');
        List<Head> heads = findHeadings(text);
        int n = 0;
        for (int i = 0; i < heads.size(); i++) {
            Head h = heads.get(i);
            int end = i + 1 < heads.size() ? heads.get(i + 1).start() : text.length();
            String content = strip(text.substring(h.end(), end));
            if (VOLUME.equals(h.kind())) {
                if (content.codePointCount(0, content.length()) >= VOLUME_INTRO_MIN_CHARS) {
                    n++;
                }
            } else if (!content.isEmpty()) {
                n++;
            }
        }
        return n;
    }

    /** 一行是不是章节标题 → {kind, 标题}，不是返回 null（与 Python detect_heading 一致） */
    static String[] detectHeading(String line) {
        String s = strip(line);
        if (s.isEmpty() || s.codePointCount(0, s.length()) > 50) {
            return null;
        }
        s = PREFIX.matcher(s).replaceFirst("");
        Matcher m = CHAPTER_HEAD.matcher(s);
        if (m.matches() && !restIsProse(m.group(2), false, "")) {
            return new String[]{CHAPTER, s};
        }
        m = EN_HEAD.matcher(s);
        if (m.matches() && !restIsProse(m.group(2), false, ",")) {
            return new String[]{CHAPTER, s};
        }
        m = VOLUME_HEAD.matcher(s);
        if (m.matches()) {
            if (EMBEDDED_CHAPTER.matcher(m.group(2)).find()) {
                return new String[]{CHAPTER, s};
            }
            if (!restIsProse(m.group(2), true, "")) {
                return new String[]{VOLUME, s};
            }
        }
        if (PART_HEAD.matcher(s).matches()) {
            return new String[]{VOLUME, s};
        }
        m = SPECIAL_HEAD.matcher(s);
        if (m.matches()) {
            String rest = m.group(2);
            boolean separated = rest.isEmpty() || SEPARATORS.indexOf(rest.charAt(0)) >= 0 || "番外".equals(m.group(1));
            if (separated && !restIsProse(rest, true, "")) {
                return new String[]{SPECIAL, s};
            }
        }
        return null;
    }

    /** 标题编号后面的部分像正文（与 Python _rest_is_prose 一致） */
    private static boolean restIsProse(String rest, boolean strict, String extraSep) {
        if (rest.isEmpty() || (SEPARATORS + extraSep).indexOf(rest.charAt(0)) >= 0) {
            return false;
        }
        if (strict) {
            return STRICT_PUNCT.matcher(rest).find();
        }
        return rest.contains("。") || rest.endsWith(".");
    }

    /** 决定用哪一套标题（与 Python find_headings 一致） */
    static List<Head> findHeadings(String text) {
        List<Head> heads = new ArrayList<>();
        int pos = 0;
        while (pos <= text.length()) {
            int nl = text.indexOf('\n', pos);
            int lineEnd = nl < 0 ? text.length() : nl;
            String[] h = detectHeading(text.substring(pos, lineEnd));
            if (h != null) {
                heads.add(new Head(pos, lineEnd, h[0], h[1]));
            }
            if (nl < 0) {
                break;
            }
            pos = nl + 1;
        }
        if (heads.stream().anyMatch(h -> CHAPTER.equals(h.kind()))) {
            return heads;
        }
        if (heads.stream().anyMatch(h -> VOLUME.equals(h.kind()))) {
            return heads.stream()
                    .map(h -> VOLUME.equals(h.kind()) ? new Head(h.start(), h.end(), CHAPTER, h.title()) : h)
                    .toList();
        }
        List<Head> numbered = new ArrayList<>();
        int real = 0;
        Matcher m = NUMBERED_RE.matcher(text);
        while (m.find()) {
            String title = m.group(1).strip();
            boolean special = SPECIAL_ONLY.matcher(title).matches();
            numbered.add(new Head(m.start(), m.end(), special ? SPECIAL : CHAPTER, title));
            if (!special) {
                real++;
            }
        }
        return real >= 3 ? numbered : List.of();
    }

    /** 去掉首尾空白，口径同 Python str.strip()（含全角空格、不换行空格） */
    private static String strip(String s) {
        int a = 0;
        int b = s.length();
        while (a < b && isSpace(s.charAt(a))) {
            a++;
        }
        while (b > a && isSpace(s.charAt(b - 1))) {
            b--;
        }
        return s.substring(a, b);
    }

    private static boolean isSpace(char c) {
        return Character.isWhitespace(c) || Character.isSpaceChar(c);
    }
}
