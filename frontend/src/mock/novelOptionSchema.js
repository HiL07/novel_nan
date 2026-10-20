/**
 * 小说创作选项的本地示例数据（数据库接入前的占位）。
 * 结构说明见 src/novel-options/fieldTypes.js；之后由后端接口返回同样结构即可替换。
 *
 * - categories：内置分类（世界观 / 角色 / 情节推进 / 文风），每个分类的 suggestions 为「添加选项项」时的推荐字段
 * - elementTemplates：自定义元素模板（怪物 / 势力 / 种族 ...），新建自定义元素时可一键套用
 * - genericSuggestions：任何自定义元素都可用的通用推荐字段
 */

const opt = (value, label, desc, children) => ({ value, label, ...(desc ? { desc } : {}), ...(children ? { children } : {}) })

/* ============================== 世界观 ============================== */
const world = {
  key: 'world',
  label: '世界观',
  icon: 'MapLocation',
  desc: '故事发生的世界：题材、时代、力量体系与社会规则',
  fields: [
    {
      key: 'genre',
      label: '题材类型',
      type: 'single',
      desc: '决定整体基调，选中后可继续细化',
      options: [
        opt('xuanhuan', '玄幻', '异世大陆、血脉、斗气', [
          {
            key: 'power',
            label: '力量来源',
            type: 'multi',
            options: [opt('bloodline', '血脉'), opt('douqi', '斗气'), opt('magic', '魔法'), opt('rune', '符文'), opt('beast', '契约兽')]
          }
        ]),
        opt('xianxia', '仙侠', '修仙问道、宗门、飞升', [
          {
            key: 'cultivation',
            label: '修炼体系',
            type: 'single',
            options: [
              opt('classic', '经典境界', '炼气 → 筑基 → 金丹 → 元婴 → 化神 → 渡劫 → 大乘', [
                { key: 'realmNote', label: '境界补充说明', type: 'textarea', placeholder: '如：每个大境界分初/中/后期，突破需渡天劫' }
              ]),
              opt('sword', '剑修体系', '以剑入道，剑意、剑域、剑心'),
              opt('body', '炼体体系', '肉身成圣，锻骨、易筋、洗髓'),
              opt('custom_realm', '完全自定义境界', '自己定义每一个境界', [
                { key: 'realms', label: '境界列表（按从低到高）', type: 'tags', placeholder: '输入境界名后回车' }
              ])
            ]
          },
          {
            key: 'sectSystem',
            label: '宗门格局',
            type: 'single',
            options: [opt('one_dominant', '一宗独大'), opt('multi_sects', '多宗林立'), opt('court_vs_sect', '朝廷与宗门并立'), opt('scattered', '散修为主')]
          }
        ]),
        opt('wuxia', '武侠', '江湖门派、内功心法'),
        opt('urban', '都市', '现代都市背景', [
          {
            key: 'urbanFlavor',
            label: '都市类型',
            type: 'single',
            options: [opt('daily', '都市日常'), opt('supernatural', '都市异能'), opt('business', '商战职场'), opt('entertainment', '娱乐圈')]
          }
        ]),
        opt('scifi', '科幻', '未来科技、星际文明', [
          {
            key: 'techLevel',
            label: '科技水平',
            type: 'single',
            options: [opt('near', '近未来'), opt('cyberpunk', '赛博朋克'), opt('interstellar', '星际殖民'), opt('post_singularity', '奇点之后')]
          },
          { key: 'hardness', label: '科幻硬度', type: 'slider', min: 1, max: 5, default: 3, marks: { 1: '软', 3: '适中', 5: '硬核' } }
        ]),
        opt('history', '历史', '真实或架空历史', [
          { key: 'dynasty', label: '朝代 / 时期', type: 'text', placeholder: '如：北宋末年、架空的大夏王朝' }
        ]),
        opt('suspense', '悬疑', '推理、惊悚、诡秘'),
        opt('apocalypse', '末世', '灾变后的废土求生', [
          {
            key: 'disaster',
            label: '灾变类型',
            type: 'multi',
            options: [opt('zombie', '丧尸'), opt('alien', '外星入侵'), opt('climate', '天灾异变'), opt('virus', '病毒'), opt('mystery', '诡异降临')]
          }
        ]),
        opt('western', '西方奇幻', '剑与魔法、龙与骑士'),
        opt('romance', '言情', '以感情线为主')
      ]
    },
    {
      key: 'era',
      label: '时代背景',
      type: 'single',
      options: [opt('ancient', '古代'), opt('modern_early', '近代'), opt('modern', '现代'), opt('future', '未来'), opt('fictional', '完全架空')]
    },
    {
      key: 'scale',
      label: '世界规模',
      type: 'single',
      options: [
        opt('city', '一座城市'),
        opt('country', '一个国家'),
        opt('continent', '一片大陆'),
        opt('multi_realm', '多重世界', '凡界 / 灵界 / 仙界等多层世界', [
          { key: 'realmLayers', label: '世界层级', type: 'tags', placeholder: '如：凡界、灵界、仙界' }
        ]),
        opt('galaxy', '星系 / 宇宙')
      ]
    },
    {
      key: 'society',
      label: '社会结构',
      type: 'multi',
      max: 3,
      options: [opt('monarchy', '君主制'), opt('sect_rule', '宗门统治'), opt('family', '世家门阀'), opt('corporate', '财团寡头'), opt('federation', '联邦'), opt('tribal', '部落'), opt('anarchy', '无政府')]
    },
    { key: 'rules', label: '特殊世界规则', type: 'tags', desc: '这个世界独有的设定', placeholder: '如：灵气复苏、夜晚禁止外出，回车添加' },
    { key: 'worldNote', label: '世界观补充', type: 'textarea', placeholder: '任何想补充的世界设定' }
  ],
  suggestions: [
    { key: 'geography', label: '地理环境', type: 'multi', options: [opt('mountain', '群山'), opt('sea', '海洋'), opt('desert', '沙漠'), opt('forest', '森林'), opt('floating', '浮空岛')] },
    { key: 'religion', label: '宗教信仰', type: 'single', options: [opt('polytheism', '多神'), opt('monotheism', '一神'), opt('ancestor', '祖灵崇拜'), opt('none', '无宗教')] },
    { key: 'currency', label: '货币 / 资源', type: 'tags', placeholder: '如：灵石、金币、信用点' },
    { key: 'history', label: '世界历史大事', type: 'textarea' }
  ]
}

/* ============================== 角色 ============================== */
// 角色卡（参考 character.ai 的角色创建）：section 决定在卡片里的分页——
// basic 基本信息 / persona 性格与说话方式（含开场白、示例对话，可「试聊」检验口吻）/ inner 内心 / story 经历与能力
const characterFields = [
  { key: 'name', label: '姓名', type: 'text', section: 'basic', placeholder: '留空则由 AI 起名' },
  { key: 'tagline', label: '一句话人设', type: 'text', section: 'basic', placeholder: '如：嘴硬心软、欠了一屁股债的落魄剑客' },
  {
    key: 'role',
    section: 'basic',
    label: '角色定位',
    type: 'single',
    options: [opt('protagonist', '主角'), opt('heroine', '女主 / 男主'), opt('villain', '反派'), opt('mentor', '导师'), opt('partner', '伙伴'), opt('rival', '宿敌'), opt('support', '配角')]
  },
  { key: 'gender', label: '性别', type: 'single', section: 'basic', options: [opt('male', '男'), opt('female', '女'), opt('other', '其他 / 不设定')] },
  {
    key: 'age',
    section: 'basic',
    label: '年龄段',
    type: 'single',
    options: [opt('child', '少年'), opt('youth', '青年'), opt('middle', '中年'), opt('old', '老年'), opt('immortal', '不老 / 长生')]
  },
  { key: 'appearance', label: '外貌特征', type: 'textarea', section: 'basic', placeholder: '让人一眼记住的样子：身形、衣着、标志性细节' },
  {
    key: 'personality',
    label: '性格',
    type: 'multi',
    section: 'persona',
    max: 4,
    options: [opt('calm', '冷静'), opt('hot', '热血'), opt('cunning', '腹黑'), opt('kind', '善良'), opt('arrogant', '高傲'), opt('humor', '幽默'), opt('cold', '冷漠'), opt('stubborn', '执拗')]
  },
  { key: 'personalityDetail', label: '性格详述', type: 'textarea', section: 'persona', placeholder: '性格的矛盾面、对不同人的不同态度、行为习惯' },
  {
    key: 'speech',
    label: '说话风格',
    type: 'single',
    section: 'persona',
    options: [opt('terse', '简短冷淡'), opt('chatty', '话多跳脱'), opt('elegant', '文雅古风'), opt('blunt', '粗犷直率'), opt('gentle', '温柔细腻'), opt('sarcastic', '毒舌嘲讽'), opt('formal', '一板一眼')]
  },
  { key: 'catchphrases', label: '口头禅 / 常用语', type: 'tags', section: 'persona', placeholder: '如：「麻烦。」「有意思。」，回车添加' },
  {
    key: 'greeting',
    label: '开场白',
    type: 'textarea',
    section: 'persona',
    desc: '试聊时角色说的第一句话',
    placeholder: '（靠在墙边擦剑，头也不抬）又是来讨债的？我说过，剑在人在，钱……没有。'
  },
  {
    key: 'dialogue',
    label: '示例对话',
    type: 'textarea',
    section: 'persona',
    desc: '几段典型对话，定下角色的口吻（试聊满意的回合可一键存到这里）',
    placeholder: '对方：你为什么要帮我？\n角色：（别过脸）谁帮你了，我只是顺路。'
  },
  { key: 'goal', label: '核心目标 / 动机', type: 'text', section: 'inner', placeholder: '如：为家族复仇、找回失踪的妹妹' },
  { key: 'fear', label: '弱点与恐惧', type: 'text', section: 'inner', placeholder: '如：怕水；最怕再次失去亲人' },
  { key: 'secret', label: '秘密', type: 'textarea', section: 'inner', placeholder: '角色藏着、读者稍后才知道的事' },
  { key: 'bottomLine', label: '价值观 / 底线', type: 'text', section: 'inner', placeholder: '如：绝不对妇孺出手' },
  {
    key: 'cheat',
    section: 'story',
    label: '金手指',
    type: 'single',
    desc: '主角的特殊优势（配角可不选）',
    options: [
      opt('system', '系统', '任务、奖励、面板', [
        {
          key: 'systemType',
          label: '系统类型',
          type: 'single',
          options: [opt('sign_in', '签到系统'), opt('task', '任务系统'), opt('shop', '商城系统'), opt('evolve', '进化系统'), opt('sim', '模拟器')]
        },
        { key: 'systemPersona', label: '系统性格', type: 'single', options: [opt('cold', '冰冷机械'), opt('chatty', '话痨毒舌'), opt('cute', '萌系')] }
      ]),
      opt('rebirth', '重生', '带着前世记忆回到过去', [
        { key: 'rebirthPoint', label: '重生到', type: 'text', placeholder: '如：十年前高考前夕' }
      ]),
      opt('transmigration', '穿越', '穿到另一个世界 / 时代'),
      opt('mentor_soul', '随身老爷爷', '戒指 / 玉佩里的残魂'),
      opt('talent', '逆天天赋', '特殊体质、血脉'),
      opt('none', '无金手指', '纯靠自身')
    ]
  },
  { key: 'abilities', label: '能力 / 特长', type: 'tags', section: 'story', placeholder: '如：拔剑术、过目不忘，回车添加' },
  { key: 'relationToLead', label: '与主角的关系', type: 'text', section: 'story', placeholder: '如：青梅竹马，后来立场对立' },
  { key: 'background', label: '背景故事', type: 'textarea', section: 'story' },
  { key: 'arc', label: '成长弧光', type: 'textarea', section: 'story', placeholder: '开篇是什么样的人，经历什么，最后变成什么样' }
]

/** 设定结构版本：保存的工作区设定低于此版本时，在加载时补上新增的内置字段（见 novel-options/schema.js#upgradeConfig） */
export const SCHEMA_VERSION = 2

const characters = {
  key: 'characters',
  label: '角色',
  icon: 'User',
  desc: '主要人物及其关系',
  fields: [
    {
      key: 'cast',
      label: '主要角色',
      type: 'group',
      display: 'characterCards',
      itemLabel: '角色',
      desc: '角色卡：一句话让 AI 创建角色，填好性格与说话方式后可以「试聊」检验口吻',
      fields: characterFields
    },
    {
      key: 'growth',
      label: '主角成长路线',
      type: 'single',
      options: [opt('zero_to_hero', '废柴逆袭'), opt('genius', '天才崛起'), opt('hidden', '扮猪吃虎'), opt('fall_rise', '跌落再起'), opt('steady', '稳健苟道')]
    },
    {
      key: 'relations',
      label: '核心人物关系',
      type: 'multi',
      options: [opt('love', '感情线'), opt('harem', '多角恋'), opt('master', '师徒'), opt('brotherhood', '兄弟情'), opt('enemy_to_lover', '欢喜冤家'), opt('family_feud', '家族恩怨')]
    }
  ],
  suggestions: [
    { key: 'castSize', label: '配角数量', type: 'slider', min: 1, max: 30, default: 8 },
    { key: 'pairing', label: '感情线设定', type: 'single', options: [opt('single', '单女主 / 单男主'), opt('multi', '多线'), opt('none', '无感情线')] },
    { key: 'relationNote', label: '人物关系说明', type: 'textarea' }
  ]
}

/* ============================== 情节推进 ============================== */
const plot = {
  key: 'plot',
  label: '情节推进',
  icon: 'Guide',
  desc: '主线结构、节奏、冲突与结局',
  fields: [
    {
      key: 'mainline',
      label: '主线结构',
      type: 'single',
      options: [
        opt('level_up', '升级流', '不断变强、换地图'),
        opt('revenge', '复仇流', '为某事复仇'),
        opt('mystery', '解谜 / 探案', '围绕谜团推进', [
          { key: 'caseMode', label: '案件组织', type: 'single', options: [opt('unit', '单元案件'), opt('long', '一案到底'), opt('mixed', '单元 + 主线大案')] }
        ]),
        opt('farming', '种田经营', '建设、经营、发展势力'),
        opt('war', '争霸', '势力斗争、战争'),
        opt('romance_line', '感情为主线'),
        opt('survival', '生存求存')
      ]
    },
    {
      key: 'opening',
      label: '开局方式',
      type: 'single',
      options: [opt('crisis', '危机开局'), opt('humiliation', '退婚 / 受辱开局'), opt('awaken', '觉醒开局'), opt('daily', '平静日常切入'), opt('in_media_res', '直接进入高潮场面')]
    },
    { key: 'pace', label: '节奏', type: 'slider', min: 1, max: 5, default: 3, marks: { 1: '慢热', 3: '适中', 5: '爽快' } },
    {
      key: 'conflicts',
      label: '主要冲突',
      type: 'multi',
      options: [opt('vs_person', '人与人'), opt('vs_world', '人与世界'), opt('vs_self', '人与自我'), opt('vs_fate', '人与命运'), opt('faction', '势力之间')]
    },
    {
      key: 'ending',
      label: '结局倾向',
      type: 'single',
      options: [opt('happy', '圆满'), opt('bittersweet', '悲喜交加'), opt('tragic', '悲剧'), opt('open', '开放式'), opt('twist', '反转')]
    },
    { key: 'chapters', label: '预计章节数', type: 'number', min: 1, max: 5000, default: 100 },
    { key: 'wordsPerChapter', label: '每章字数', type: 'number', min: 500, max: 10000, step: 500, default: 3000 },
    {
      key: 'milestones',
      label: '关键情节节点',
      type: 'group',
      itemLabel: '节点',
      fields: [
        { key: 'name', label: '节点名称', type: 'text', placeholder: '如：宗门大比' },
        { key: 'stage', label: '所处阶段', type: 'single', options: [opt('begin', '开篇'), opt('rising', '发展'), opt('climax', '高潮'), opt('end', '结局')] },
        { key: 'detail', label: '情节描述', type: 'textarea' }
      ]
    }
  ],
  suggestions: [
    { key: 'foreshadow', label: '伏笔设计', type: 'tags', placeholder: '如：神秘玉佩的来历' },
    { key: 'twists', label: '反转次数', type: 'slider', min: 0, max: 10, default: 2 },
    { key: 'subplots', label: '支线', type: 'multi', options: [opt('romance', '感情支线'), opt('growth', '配角成长'), opt('mystery', '身世之谜'), opt('comedy', '日常搞笑')] }
  ]
}

/* ============================== 文风 ============================== */
const style = {
  key: 'style',
  label: '文风',
  icon: 'EditPen',
  desc: '叙事视角、语言风格与读者定位',
  fields: [
    { key: 'pov', label: '叙事视角', type: 'single', options: [opt('first', '第一人称'), opt('third_limited', '第三人称限知'), opt('third_omni', '第三人称全知'), opt('multi_pov', '多视角轮换')] },
    {
      key: 'language',
      label: '语言风格',
      type: 'multi',
      max: 3,
      options: [opt('plain', '白话流畅'), opt('classical', '古风雅致'), opt('humor', '诙谐幽默'), opt('dark', '冷峻克制'), opt('poetic', '细腻抒情'), opt('meme', '网感玩梗')]
    },
    { key: 'tone', label: '整体基调', type: 'multi', options: [opt('light', '轻松'), opt('hot', '热血'), opt('dark', '黑暗'), opt('warm', '温暖'), opt('tense', '紧张'), opt('sad', '虐心')] },
    { key: 'dialogue', label: '对话比例', type: 'slider', min: 0, max: 100, step: 10, default: 40, marks: { 0: '少', 50: '适中', 100: '多' } },
    { key: 'audience', label: '目标读者', type: 'single', options: [opt('male', '男频'), opt('female', '女频'), opt('general', '通用')] },
    { key: 'avoid', label: '避免出现', type: 'tags', placeholder: '如：过度暴力、某类桥段，回车添加' },
    { key: 'reference', label: '参考作品 / 作者', type: 'tags', placeholder: '如：《三体》、金庸' }
  ],
  suggestions: [
    { key: 'description', label: '描写侧重', type: 'multi', options: [opt('action', '动作打斗'), opt('psych', '心理'), opt('scene', '景物'), opt('detail', '细节考据')] },
    { key: 'rating', label: '内容分级', type: 'single', options: [opt('all', '全年龄'), opt('teen', '青少年'), opt('adult', '成人向（克制）')] }
  ]
}

/* ============================== 自定义元素模板 ============================== */
const elementTemplates = [
  {
    key: 'monster',
    label: '怪物',
    icon: 'Warning',
    desc: '妖兽、魔物、异种等非人生物',
    fields: [
      {
        key: 'origin',
        label: '怪物来源',
        type: 'multi',
        options: [opt('mutation', '生物变异'), opt('demonic', '魔气侵蚀'), opt('ancient', '上古遗种'), opt('artificial', '人造 / 实验产物'), opt('otherworld', '异界入侵'), opt('spirit', '天地精怪')]
      },
      {
        key: 'kinds',
        label: '怪物种类',
        type: 'multi',
        options: [opt('beast', '兽类'), opt('undead', '亡灵'), opt('elemental', '元素生物'), opt('insect', '虫族'), opt('giant', '巨兽'), opt('dragon', '龙类'), opt('mechanical', '机械体'), opt('eldritch', '不可名状')]
      },
      {
        key: 'ranking',
        label: '危险分级',
        type: 'single',
        options: [
          opt('star', '星级（一星~九星）'),
          opt('letter', '字母级（F~S）'),
          opt('realm', '对应修炼境界'),
          opt('custom_rank', '自定义等级', '', [{ key: 'ranks', label: '等级列表（从低到高）', type: 'tags', placeholder: '输入等级名后回车' }])
        ]
      },
      { key: 'intelligence', label: '智慧程度', type: 'single', options: [opt('instinct', '纯本能'), opt('cunning', '狡诈'), opt('sentient', '有完整智慧'), opt('civilization', '有自己的文明')] },
      { key: 'relation', label: '与人类关系', type: 'single', options: [opt('hostile', '敌对'), opt('neutral', '中立'), opt('tamable', '可驯服 / 契约'), opt('symbiotic', '共生')] },
      {
        key: 'list',
        label: '典型怪物',
        type: 'group',
        itemLabel: '怪物',
        fields: [
          { key: 'name', label: '名称', type: 'text', placeholder: '如：赤瞳妖狼' },
          { key: 'appearance', label: '外形', type: 'text' },
          { key: 'abilities', label: '能力', type: 'tags', placeholder: '回车添加' },
          { key: 'weakness', label: '弱点', type: 'tags', placeholder: '回车添加' },
          { key: 'habitat', label: '栖息地', type: 'text' },
          { key: 'danger', label: '危险程度', type: 'slider', min: 1, max: 10, default: 5 }
        ]
      }
    ],
    suggestions: [
      { key: 'drops', label: '击杀收获', type: 'multi', options: [opt('core', '妖丹 / 魔核'), opt('material', '材料'), opt('exp', '经验 / 修为'), opt('none', '无')] },
      { key: 'tide', label: '兽潮 / 怪物潮', type: 'single', options: [opt('none', '不出现'), opt('periodic', '周期性爆发'), opt('climax', '作为高潮事件')] }
    ]
  },
  {
    key: 'faction',
    label: '势力组织',
    icon: 'OfficeBuilding',
    desc: '宗门、帝国、公司、帮派',
    fields: [
      { key: 'type', label: '势力类型', type: 'multi', options: [opt('sect', '宗门'), opt('empire', '王朝 / 帝国'), opt('family', '世家'), opt('guild', '公会'), opt('company', '财团 / 公司'), opt('cult', '邪教'), opt('rebel', '反抗军')] },
      {
        key: 'list',
        label: '具体势力',
        type: 'group',
        itemLabel: '势力',
        fields: [
          { key: 'name', label: '名称', type: 'text' },
          { key: 'stance', label: '立场', type: 'single', options: [opt('ally', '友方'), opt('neutral', '中立'), opt('enemy', '敌对')] },
          { key: 'strength', label: '实力', type: 'slider', min: 1, max: 10, default: 5 },
          { key: 'feature', label: '特点', type: 'textarea' }
        ]
      }
    ],
    suggestions: [{ key: 'hierarchy', label: '内部等级', type: 'tags', placeholder: '如：外门、内门、核心、长老' }]
  },
  {
    key: 'race',
    label: '种族',
    icon: 'Avatar',
    desc: '人族以外的智慧种族',
    fields: [
      { key: 'races', label: '存在的种族', type: 'multi', options: [opt('human', '人族'), opt('elf', '精灵'), opt('demon', '魔族'), opt('yao', '妖族'), opt('dwarf', '矮人'), opt('dragonkin', '龙族'), opt('beastman', '兽人')] },
      { key: 'relation', label: '种族关系', type: 'single', options: [opt('peace', '和平共处'), opt('war', '长期战争'), opt('dominant', '一族统治'), opt('isolated', '彼此隔绝')] }
    ],
    suggestions: [{ key: 'raceNote', label: '种族特性说明', type: 'textarea' }]
  },
  {
    key: 'location',
    label: '地点',
    icon: 'Location',
    desc: '城市、秘境、遗迹等重要场景',
    fields: [
      {
        key: 'list',
        label: '重要地点',
        type: 'group',
        itemLabel: '地点',
        fields: [
          { key: 'name', label: '名称', type: 'text' },
          { key: 'kind', label: '类型', type: 'single', options: [opt('city', '城市'), opt('secret', '秘境'), opt('ruin', '遗迹'), opt('wild', '荒野'), opt('palace', '宫殿 / 宗门驻地')] },
          { key: 'detail', label: '描述', type: 'textarea' }
        ]
      }
    ],
    suggestions: [{ key: 'map', label: '地图结构', type: 'single', options: [opt('linear', '线性换地图'), opt('open', '开放世界'), opt('hub', '以一地为中心辐射')] }]
  },
  {
    key: 'item',
    label: '物品神器',
    icon: 'Present',
    desc: '法宝、武器、关键道具',
    fields: [
      { key: 'grading', label: '品阶体系', type: 'single', options: [opt('tiers', '凡/灵/宝/仙/神'), opt('rarity', '普通/稀有/史诗/传说'), opt('none', '不分级')] },
      {
        key: 'list',
        label: '关键物品',
        type: 'group',
        itemLabel: '物品',
        fields: [
          { key: 'name', label: '名称', type: 'text' },
          { key: 'kind', label: '类别', type: 'single', options: [opt('weapon', '武器'), opt('armor', '防具'), opt('pill', '丹药'), opt('artifact', '法宝'), opt('plot', '剧情道具')] },
          { key: 'effect', label: '作用', type: 'textarea' }
        ]
      }
    ],
    suggestions: []
  },
  {
    key: 'skill',
    label: '功法技能',
    icon: 'MagicStick',
    desc: '功法、魔法、异能',
    fields: [
      { key: 'system', label: '技能体系', type: 'multi', options: [opt('martial', '武技'), opt('spell', '法术'), opt('esper', '异能'), opt('tech', '科技装备'), opt('summon', '召唤')] },
      {
        key: 'list',
        label: '代表技能',
        type: 'group',
        itemLabel: '技能',
        fields: [
          { key: 'name', label: '名称', type: 'text' },
          { key: 'owner', label: '使用者', type: 'text' },
          { key: 'effect', label: '效果', type: 'textarea' }
        ]
      }
    ],
    suggestions: [{ key: 'cost', label: '使用代价', type: 'multi', options: [opt('mana', '灵力 / 法力'), opt('life', '寿命'), opt('sanity', '理智'), opt('material', '材料')] }]
  }
]

/** 任意自定义元素都可添加的通用推荐字段 */
const genericSuggestions = [
  { key: 'name', label: '名称', type: 'text' },
  { key: 'kind', label: '类型', type: 'multi', options: [] },
  { key: 'level', label: '等级', type: 'single', options: [opt('low', '低'), opt('mid', '中'), opt('high', '高'), opt('top', '顶级')] },
  { key: 'importance', label: '在故事中的重要程度', type: 'slider', min: 1, max: 5, default: 3 },
  { key: 'features', label: '特点', type: 'tags' },
  { key: 'items', label: '具体条目', type: 'group', itemLabel: '条目', fields: [{ key: 'name', label: '名称', type: 'text' }, { key: 'detail', label: '描述', type: 'textarea' }] },
  { key: 'note', label: '补充说明', type: 'textarea' }
]

export default {
  schemaVersion: SCHEMA_VERSION,
  categories: [world, characters, plot, style],
  elementTemplates,
  genericSuggestions
}
