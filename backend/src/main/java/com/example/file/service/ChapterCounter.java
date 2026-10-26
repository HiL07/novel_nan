package com.example.file.service;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 数小说章节数：逐个识别章节标题行再计数（不看最后一章写的是第几章）。
 * 规则与 python-service/app/text_loader.py 的 split_chapters 一致，保证与小说提取切出的章节对得上：
 * 优先「第X章/回/节/卷 / Chapter N」，一个都没有时才用「1.标题 / 一、标题」兜底且至少 3 处；
 * 标题下没有正文的不算（如紧跟第一章的「第一卷」），开头的序/前言不算。
 */
public final class ChapterCounter {

    private ChapterCounter() {
    }

    private static final String EN_NUM = "(?:\\d+|[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"
            + "|[a-z]+teen|(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[- ][a-z]+)?)";
    private static final String SPECIAL = "(?:序[ \\t　]*章|序言|序|前言|楔子|引子|尾[ \\t　]*声|后[ \\t　]*记|番外[^\\n]{0,20}|prologue|epilogue)";
    private static final int FLAGS = Pattern.CASE_INSENSITIVE | Pattern.UNICODE_CASE | Pattern.MULTILINE
            | Pattern.UNICODE_CHARACTER_CLASS;

    private static final Pattern CHAPTER_RE = Pattern.compile(
            "^[ \\t　]*("
                    + "第[零〇一二三四五六七八九十百千万两\\d]+[章回节卷集部篇][^\\n]{0,30}"
                    + "|[上中下]部[ \\t　]+[^\\s，。！？“”：；…][^\\n，。！？“”：；…]{0,15}"
                    + "|chapter[ \\t]+" + EN_NUM + "\\b[^\\n]{0,60}"
                    + "|" + SPECIAL
                    + ")[ \\t　]*$", FLAGS);
    private static final Pattern NUMBERED_RE = Pattern.compile(
            "^((?:\\d{1,4}|[一二三四五六七八九十百]{1,4})[.、．][ \\t]*[^\\s\\d][^\\n]{0,24}?|" + SPECIAL + ")[ \\t]*$"
                    + "(?<![。！？!?”…：:，,；;])", FLAGS);
    private static final Pattern SPECIAL_ONLY = Pattern.compile(SPECIAL, FLAGS);

    /** 章节数；识别不到章节结构返回 0 */
    public static int count(String text) {
        if (text == null || text.isEmpty()) {
            return 0;
        }
        text = text.replace("\r\n", "\n").replace('\r', '\n');
        List<int[]> heads = find(CHAPTER_RE, text, 1);
        if (heads.isEmpty()) {
            heads = find(NUMBERED_RE, text, 3);
        }
        int n = 0;
        for (int i = 0; i < heads.size(); i++) {
            int end = i + 1 < heads.size() ? heads.get(i + 1)[0] : text.length();
            if (!text.substring(heads.get(i)[1], end).isBlank()) {
                n++;
            }
        }
        return n;
    }

    /** 全部标题行 [start, end]；非「前言 / 尾声」类特殊标题不足 minReal 个时视为没有章节结构 */
    private static List<int[]> find(Pattern pattern, String text, int minReal) {
        List<int[]> heads = new ArrayList<>();
        int real = 0;
        Matcher m = pattern.matcher(text);
        while (m.find()) {
            heads.add(new int[]{m.start(), m.end()});
            if (!SPECIAL_ONLY.matcher(m.group(1).strip()).matches()) {
                real++;
            }
        }
        return real >= minReal ? heads : List.of();
    }
}
