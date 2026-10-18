"""抓取规则：每个字段都是 XPath，留空则用自动识别（parser.py 的启发式）。

两种采集模式共用一套规则：
- 单本（book）：只用到 bookName / author / intro / chapterLinks / tocNext / content / contentNext；
- 整站（site）：先按 categoryLinks / bookLinks / listNext 发现「分类 → 列表页 → 书籍」，
  再用 tocLink 从书籍详情页跳到目录页，之后与单本完全相同的流程抓正文。
  对应 copybook/bookspider/spiders/quanshuwang.py 的 4 段跳转（首页 → 分类 → 列表翻页 → 书籍 → 章节）。

预设 quanshuwang 即 copybook/bookspider/spiders/quanshuwang.py 中的 XPath（该站已下线，仅作写规则的参考样例）。
"""
from typing import Optional

from pydantic import BaseModel, Field


class CrawlRule(BaseModel):
    """XPath 规则。整站字段在首页 / 列表页 / 详情页上求值，其余按所在页面求值。"""
    # ---- 整站发现（mode=site 才用到）----
    categoryLinks: str = ""   # 首页的分类 <a>，如 //ul[@class='channel-nav-list']/li/a
    bookLinks: str = ""       # 分类列表页里的书籍 <a>，如 //ul[@class='seeWell cf']/li/span/a[1]
    listNext: str = ""        # 分类列表「下一页」的 <a>（列表分页的站点）
    tocLink: str = ""         # 书籍详情页 → 目录页的 <a>，如 //div[@class='b-oper']/a[@class='reader']
    # ---- 书籍信息 ----
    bookName: str = ""        # 书名文本，如 //div[@class='b-info']/h1/text()
    author: str = ""          # 作者文本
    intro: str = ""           # 简介文本（多个文本节点会拼接）
    chapterLinks: str = ""    # 章节 <a> 元素（取 text() 作章节名、@href 作地址），如 //div[@id='list']//dd/a
    tocNext: str = ""         # 目录分页「下一页」的 href（目录分多页的站点）
    content: str = ""         # 正文所在元素，如 //div[@id='content']（取其全部文本，<br>/<p> 换行）
    contentNext: str = ""     # 章节内分页「下一页」的 href（一章拆成多页的站点）
    encoding: str = ""        # 强制编码（如 gbk）；留空按 HTTP 头 / meta / 严格 UTF-8 → GB18030 识别
    removePatterns: list[str] = Field(default_factory=list)  # 正文中要删除的行（正则，匹配整行任意位置即删）


class Preset(BaseModel):
    key: str
    name: str
    description: str
    domains: list[str] = Field(default_factory=list)  # 命中这些域名时自动选用
    rule: CrawlRule


PRESETS: list[Preset] = [
    Preset(
        key="auto",
        name="自动识别",
        description="不写规则：按「第X章」等标题找目录里最集中的章节链接，正文取文字最多的区块。适用于大多数笔趣阁式站点。",
        rule=CrawlRule(),
    ),
    Preset(
        key="biquge",
        name="笔趣阁式模板",
        description="常见模板：目录 #list dd a，正文 #content。目录顶部的「最新章节」重复项会自动去掉。",
        rule=CrawlRule(
            bookName="//div[@id='info']/h1/text()",
            author="//meta[@property='og:novel:author']/@content",
            intro="//div[@id='intro']//text()",
            chapterLinks="//div[@id='list']//dd/a",
            content="//div[@id='content']",
        ),
    ),
    Preset(
        key="wikisource",
        name="维基文库",
        description="zh.wikisource.org 的公有领域古典小说（如 西遊記 / 紅樓夢 / 三國演義 / 水滸傳）：正文只取段落与诗词，去掉页眉导航。",
        domains=["wikisource.org"],
        rule=CrawlRule(
            content="//div[contains(@class,'mw-parser-output')]/*[self::p or self::dl or self::blockquote or contains(@class,'poem')]",
        ),
    ),
    Preset(
        key="quanshuwang",
        name="全书网（copybook 原规则）",
        description="copybook 项目中的 XPath（首页分类 → 列表翻页 → 书籍详情 → 目录 → 正文），quanshuwang.com 已下线，仅作参考。单本模式可直接填目录页地址；整站模式填首页。",
        domains=["quanshuwang.com"],
        rule=CrawlRule(
            # 整站发现：copybook 的 parse / getNext / getBooks 三段
            categoryLinks="//ul[@class='channel-nav-list']/li/a",
            bookLinks="//ul[@class='seeWell cf']/li/span/a[1]",
            listNext="//a[@class='next']",
            tocLink="//div[@class='b-oper']/a[@class='reader']",
            # 书籍信息
            bookName="//div[@class='chapName']/strong/text() | //div[@class='b-info']/h1/text()",
            author="//div[@class='bookDetail']/dl[@class='bookso']/dd[1]/text()",
            intro="//div[@id='waa']/text()",
            # 目录 / 正文
            chapterLinks="//div[@class='clearfix dirconone']//li/a",
            content="//div[@id='content']",
            encoding="gbk",
        ),
    ),
]

# 所有站点通用的广告 / 引流行
DEFAULT_REMOVE_PATTERNS = [
    r"https?://\S+",
    r"www\.[\w-]+\.\w+",
    r"(?:请记住|一秒记住|手机用户请浏览|天才一秒|最新章节|免费阅读|本站|首发|笔趣阁|加入书签|章节错误|点此举报)",
    r"^\s*(?:(?:上一章|下一章|上一回|下一回|返回目录|回目录|目录|上一页|下一页)[\s　|]*)+$",
]


def find_preset(key: str) -> Optional[Preset]:
    return next((p for p in PRESETS if p.key == key), None)


def preset_for_host(host: str) -> Optional[Preset]:
    host = host.lower()
    return next((p for p in PRESETS if any(host == d or host.endswith("." + d) for d in p.domains)), None)


def resolve(preset_key: str, custom: Optional[CrawlRule], host: str) -> tuple[str, CrawlRule]:
    """预设 + 自定义字段合并（自定义的非空字段覆盖预设）。preset_key 为空时按域名匹配，匹配不到用 auto。"""
    preset = find_preset(preset_key) if preset_key else preset_for_host(host)
    if preset_key and preset is None:
        raise ValueError(f"未知的规则预设：{preset_key}")
    preset = preset or PRESETS[0]
    rule = preset.rule.model_copy(deep=True)
    if custom:
        for name, value in custom.model_dump().items():
            if value:
                setattr(rule, name, value)
    return preset.key, rule
