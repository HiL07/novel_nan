"""网络小说抓取：目录页 → 章节列表 → 逐章正文 → 一份 UTF-8 txt（由 Java 存入文件管理）。

两种采集模式（共用一套 XPath 规则与限速 / robots / 重试）：
- 单本（book）：用户给一本书的目录页地址，抓完合成一个 txt；
- 整站（site）：复刻 copybook 的跳转链——站点首页 → 分类 → 分类列表翻页 → 书籍详情 → 目录 → 正文，
  先 discover() 有界采样出书籍清单，再由 Java 逐本提交普通抓取任务，每本一个 txt。

思路来自 copybook/（scrapy 爬 quanshuwang.com：XPath 硬编码，直接写 Django 的 sqlite）。
这里改为：规则可配置（内置预设 / 自定义 XPath / 自动识别）、限速串行、有界采样，
结果交给 Java 落盘入库（Python 不碰数据库）。
"""
