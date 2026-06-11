"""
astrbot_plugin_meihua - 梅花易数占卜插件
基于梅花易数原理，支持时间起卦与数字起卦。
语言风格：白话夹杂文言文。
功能说明：
- 用户发送触发词（占卜/起卦/算卦/梅花等）即可起卦
- 若用户附带事件描述，则结合事件进行关联解读与建议
- 若用户未提事件，则单纯解读卦象吉凶与寓意
- 全程语言风格为白话夹杂文言文
起卦方式：
- 时间起卦（无数）：年取地支数，月取月数（公历近似农历），日取日数，时取时辰地支数
  上卦 = (年+月+日) % 8，下卦 = (年+月+日+时) % 8，动爻 = (年+月+日+时) % 6
- 一数起卦：上卦 = 数%8，下卦 = (数+时辰)%8，动爻 = (数+时辰)%6
- 两数起卦：上卦 = 数1%8，下卦 = 数2%8，动爻 = (数1+数2+时辰)%6
体用分析：动爻所在卦为用卦，不动之卦为体卦
互卦：取本卦2/3/4爻为下卦，3/4/5爻为上卦
变卦：动爻阴阳翻转后所得之卦
五行生克：用生体大吉，体用比和吉，体克用小吉，体生用泄气，用克体凶
"""

import random
from .xiang_data import get_xiang_summary
from datetime import datetime
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
import re

# ╔══════════════════════════════════════════════════════════════╗
# ║                    八卦基础数据                              ║
# ╚══════════════════════════════════════════════════════════════╝

BAGUA = {
    1: {"name": "乾", "element": "金", "nature": "天", "symbol": "☰", "lines": [1, 1, 1],
        "trait": "刚健", "direction": "西北", "season": "秋冬间", "number": "一"},
    2: {"name": "兑", "element": "金", "nature": "泽", "symbol": "☱", "lines": [1, 1, 0],
        "trait": "喜悦", "direction": "西", "season": "秋", "number": "二"},
    3: {"name": "离", "element": "火", "nature": "火", "symbol": "☲", "lines": [1, 0, 1],
        "trait": "光明", "direction": "南", "season": "夏", "number": "三"},
    4: {"name": "震", "element": "木", "nature": "雷", "symbol": "☳", "lines": [1, 0, 0],
        "trait": "震动", "direction": "东", "season": "春", "number": "四"},
    5: {"name": "巽", "element": "木", "nature": "风", "symbol": "☴", "lines": [0, 1, 1],
        "trait": "柔顺", "direction": "东南", "season": "春夏间", "number": "五"},
    6: {"name": "坎", "element": "水", "nature": "水", "symbol": "☵", "lines": [0, 1, 0],
        "trait": "险陷", "direction": "北", "season": "冬", "number": "六"},
    7: {"name": "艮", "element": "土", "nature": "山", "symbol": "☶", "lines": [0, 0, 1],
        "trait": "静止", "direction": "东北", "season": "冬春间", "number": "七"},
    8: {"name": "坤", "element": "土", "nature": "地", "symbol": "☷", "lines": [0, 0, 0],
        "trait": "柔顺", "direction": "西南", "season": "夏秋间", "number": "八"},
}

# 五行生克关系
# A生B：GENERATING[A] == B
GENERATING = {"金": "水", "水": "木", "木": "火", "火": "土", "土": "金"}
# A克B：OVERCOMING[A] == B
OVERCOMING = {"金": "木", "木": "土", "土": "水", "水": "火", "火": "金"}

# 天干地支
TIANGAN = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
DIZHI = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]

# 动爻位置含义
MOVING_LINE_MEANING = {
    1: "初爻·事之始", 2: "二爻·事之渐", 3: "三爻·事之转",
    4: "四爻·事之深", 5: "五爻·事之盛", 6: "上爻·事之终",
}

# ╔══════════════════════════════════════════════════════════════╗
# ║                  六十四卦完整数据                             ║
# ║  键：(上卦序号, 下卦序号)                                     ║
# ║  值：name=全名, keyword=关键词, desc=卦辞摘要                 ║
# ╚══════════════════════════════════════════════════════════════╝

HEXAGRAMS = {
    # ── 乾宫八卦（上卦为乾） ──
    (1, 1): {"name": "乾为天", "keyword": "刚健中正", "desc": "元亨利贞，天行健，君子以自强不息"},
    (1, 2): {"name": "天泽履", "keyword": "谨慎前行", "desc": "履虎尾，不咥人，亨"},
    (1, 3): {"name": "天火同人", "keyword": "志同道合", "desc": "同人于野，亨，利涉大川"},
    (1, 4): {"name": "天雷无妄", "keyword": "顺应天时", "desc": "元亨利贞，无妄之行"},
    (1, 5): {"name": "天风姤", "keyword": "不期而遇", "desc": "女壮，勿用取女"},
    (1, 6): {"name": "天水讼", "keyword": "争讼纷扰", "desc": "有孚窒惕，中吉终凶"},
    (1, 7): {"name": "天山遁", "keyword": "隐退避祸", "desc": "亨，小利贞，退而保全"},
    (1, 8): {"name": "天地否", "keyword": "闭塞不通", "desc": "否之匪人，不利君子贞"},

    # ── 兑宫八卦（上卦为兑） ──
    (2, 1): {"name": "泽天夬", "keyword": "果断决裂", "desc": "扬于王庭，刚决柔也"},
    (2, 2): {"name": "兑为泽", "keyword": "喜悦和乐", "desc": "亨，利贞，刚中而柔外"},
    (2, 3): {"name": "泽火革", "keyword": "变革更新", "desc": "己日乃孚，元亨利贞，悔亡"},
    (2, 4): {"name": "泽雷随", "keyword": "随顺而行", "desc": "元亨利贞，无咎"},
    (2, 5): {"name": "泽风大过", "keyword": "非常之举", "desc": "栋桡，利有攸往，亨"},
    (2, 6): {"name": "泽水困", "keyword": "困境求通", "desc": "亨，贞大人吉，无咎，有言不信"},
    (2, 7): {"name": "泽山咸", "keyword": "感应相通", "desc": "亨，利贞，取女吉"},
    (2, 8): {"name": "泽地萃", "keyword": "聚集汇合", "desc": "亨，王假有庙，利见大人"},

    # ── 离宫八卦（上卦为离） ──
    (3, 1): {"name": "火天大有", "keyword": "大有所获", "desc": "元亨，柔得尊位大中"},
    (3, 2): {"name": "火泽睽", "keyword": "乖违背离", "desc": "小事吉，二女同居其志不同行"},
    (3, 3): {"name": "离为火", "keyword": "光明附丽", "desc": "利贞，亨，畜牝牛吉"},
    (3, 4): {"name": "火雷噬嗑", "keyword": "明罚敕法", "desc": "亨，利用狱"},
    (3, 5): {"name": "火风鼎", "keyword": "革故鼎新", "desc": "元吉，亨，以木巽火"},
    (3, 6): {"name": "火水未济", "keyword": "事未完成", "desc": "亨，小狐汔济，濡其尾"},
    (3, 7): {"name": "火山旅", "keyword": "旅途不安", "desc": "小亨，旅贞吉"},
    (3, 8): {"name": "火地晋", "keyword": "晋升进取", "desc": "康侯用锡马蕃庶，昼日三接"},

    # ── 震宫八卦（上卦为震） ──
    (4, 1): {"name": "雷天大壮", "keyword": "壮盛有力", "desc": "利贞，刚以动故壮"},
    (4, 2): {"name": "雷泽归妹", "keyword": "行事仓促", "desc": "征凶，无攸利"},
    (4, 3): {"name": "雷火丰", "keyword": "丰盛盈满", "desc": "亨，王假之，勿忧宜日中"},
    (4, 4): {"name": "震为雷", "keyword": "惊动奋发", "desc": "亨，震来虩虩，笑言哑哑"},
    (4, 5): {"name": "雷风恒", "keyword": "持之以恒", "desc": "亨，无咎，利贞，利有攸往"},
    (4, 6): {"name": "雷水解", "keyword": "化解困难", "desc": "利西南，无所往其来复吉"},
    (4, 7): {"name": "雷山小过", "keyword": "小有过越", "desc": "亨，利贞，可小事不可大事"},
    (4, 8): {"name": "雷地豫", "keyword": "安乐愉悦", "desc": "利建侯行师"},

    # ── 巽宫八卦（上卦为巽） ──
    (5, 1): {"name": "风天小畜", "keyword": "积蓄待发", "desc": "亨，密云不雨，自我西郊"},
    (5, 2): {"name": "风泽中孚", "keyword": "诚信为本", "desc": "豚鱼吉，利涉大川，利贞"},
    (5, 3): {"name": "风火家人", "keyword": "治家之道", "desc": "利女贞，正位居体"},
    (5, 4): {"name": "风雷益", "keyword": "增益进取", "desc": "利有攸往，利涉大川"},
    (5, 5): {"name": "巽为风", "keyword": "谦逊柔顺", "desc": "小亨，利有攸往，利见大人"},
    (5, 6): {"name": "风水涣", "keyword": "涣散离析", "desc": "亨，王假有庙，利涉大川"},
    (5, 7): {"name": "风山渐", "keyword": "循序渐进", "desc": "女归吉，利贞"},
    (5, 8): {"name": "风地观", "keyword": "观察审视", "desc": "盥而不荐，有孚颙若"},

    # ── 坎宫八卦（上卦为坎） ──
    (6, 1): {"name": "水天需", "keyword": "等待时机", "desc": "有孚，光亨贞吉，利涉大川"},
    (6, 2): {"name": "水泽节", "keyword": "适度节制", "desc": "亨，苦节不可贞"},
    (6, 3): {"name": "水火既济", "keyword": "事已成就", "desc": "亨小，利贞，初吉终乱"},
    (6, 4): {"name": "水雷屯", "keyword": "创始艰难", "desc": "元亨利贞，勿用有攸往，利建侯"},
    (6, 5): {"name": "水风井", "keyword": "汲养不穷", "desc": "改邑不改井，无丧无得"},
    (6, 6): {"name": "坎为水", "keyword": "重险陷溺", "desc": "有孚，维心亨，行有尚"},
    (6, 7): {"name": "水山蹇", "keyword": "行路艰难", "desc": "利西南，不利东北，利见大人"},
    (6, 8): {"name": "水地比", "keyword": "亲附相助", "desc": "吉，原筮元永贞，无咎"},

    # ── 艮宫八卦（上卦为艮） ──
    (7, 1): {"name": "山天大畜", "keyword": "大有蓄积", "desc": "利贞，不家食吉，利涉大川"},
    (7, 2): {"name": "山泽损", "keyword": "减损奉上", "desc": "有孚，元吉，无咎，可贞"},
    (7, 3): {"name": "山火贲", "keyword": "文饰美化", "desc": "亨，小利有攸往"},
    (7, 4): {"name": "山雷颐", "keyword": "慎养修身", "desc": "贞吉，观颐自求口实"},
    (7, 5): {"name": "山风蛊", "keyword": "整饬弊乱", "desc": "元亨，利涉大川，先甲三日后甲三日"},
    (7, 6): {"name": "山水蒙", "keyword": "启蒙教化", "desc": "亨，匪我求童蒙，童蒙求我"},
    (7, 7): {"name": "艮为山", "keyword": "安止不动", "desc": "艮其背，不获其身，行其庭不见其人"},
    (7, 8): {"name": "山地剥", "keyword": "剥落衰败", "desc": "不利有攸往，柔变刚也"},

    # ── 坤宫八卦（上卦为坤） ──
    (8, 1): {"name": "地天泰", "keyword": "通泰和畅", "desc": "小往大来，吉亨，天地交而万物通"},
    (8, 2): {"name": "地泽临", "keyword": "居高临下", "desc": "元亨利贞，至于八月有凶"},
    (8, 3): {"name": "地火明夷", "keyword": "明入地中", "desc": "利艰贞，内文明而外柔顺"},
    (8, 4): {"name": "地雷复", "keyword": "一阳来复", "desc": "亨，出入无疾，朋来无咎"},
    (8, 5): {"name": "地风升", "keyword": "上升进取", "desc": "元亨，用见大人，勿恤南征吉"},
    (8, 6): {"name": "地水师", "keyword": "兵众统率", "desc": "贞，丈人吉，无咎"},
    (8, 7): {"name": "地山谦", "keyword": "谦虚受益", "desc": "亨，君子有终，谦尊而光"},
    (8, 8): {"name": "坤为地", "keyword": "柔顺承载", "desc": "元亨，利牝马之贞，地势坤君子以厚德载物"},
}

# ╔══════════════════════════════════════════════════════════════╗
# ║                    触发关键词                                ║
# ╚══════════════════════════════════════════════════════════════╝

TRIGGER_KEYWORDS = ["占卜", "起卦", "算卦", "梅花", "梅花易数", "卜卦", "测卦", "问卦", "求卦"]


# ╔══════════════════════════════════════════════════════════════╗
# ║                   工具函数                                   ║
# ╚══════════════════════════════════════════════════════════════╝

def get_hour_dizhi_num(hour: int) -> int:
    """将24小时制转换为时辰地支序号（1-12）
    23-1时=子(1), 1-3时=丑(2), 3-5时=寅(3), ..., 21-23时=亥(12)
    """
    if hour == 23 or hour == 0:
        return 1
    return (hour + 1) // 2 + 1


def lines_to_trigram(lines: list) -> int:
    """将三爻序列 [初爻, 中爻, 上爻] 转换为八卦序号（1-8）"""
    pattern = tuple(lines)
    TRIGRAM_PATTERNS = {
        (1, 1, 1): 1,  # 乾
        (1, 1, 0): 2,  # 兑
        (1, 0, 1): 3,  # 离
        (1, 0, 0): 4,  # 震
        (0, 1, 1): 5,  # 巽
        (0, 1, 0): 6,  # 坎
        (0, 0, 1): 7,  # 艮
        (0, 0, 0): 8,  # 坤
    }
    return TRIGRAM_PATTERNS.get(pattern, 1)


def get_element_relation(body_element: str, use_element: str) -> tuple:
    """判断体用五行关系及吉凶
    返回: (关系描述, 吉凶判断)
    """
    if body_element == use_element:
        return "体用比和", "吉"
    # 用生体：用卦五行生体卦五行 → 大吉
    if GENERATING.get(use_element) == body_element:
        return "用生体", "大吉"
    # 体生用：体卦五行生用卦五行 → 泄气耗损
    if GENERATING.get(body_element) == use_element:
        return "体生用", "泄气"
    # 体克用：体卦五行克用卦五行 → 小吉，有阻力但可成
    if OVERCOMING.get(body_element) == use_element:
        return "体克用", "小吉"
    # 用克体：用卦五行克体卦五行 → 凶
    if OVERCOMING.get(use_element) == body_element:
        return "用克体", "凶"
    return "未知", "平"


def get_element_detail(body_element: str, other_element: str) -> str:
    """获取体卦与另一卦之间的五行关系描述"""
    if body_element == other_element:
        return f"比和（{body_element}同{other_element}）· 吉"
    if GENERATING.get(other_element) == body_element:
        return f"生体（{other_element}生{body_element}）· 大吉"
    if GENERATING.get(body_element) == other_element:
        return f"泄体（{body_element}生{other_element}）· 耗损"
    if OVERCOMING.get(body_element) == other_element:
        return f"体克（{body_element}克{other_element}）· 小吉"
    if OVERCOMING.get(other_element) == body_element:
        return f"克体（{other_element}克{body_element}）· 凶"
    return "关系未明 · 平"


def format_hexagram_display(upper_num: int, lower_num: int) -> str:
    """格式化卦象显示：卦名 + 符号"""
    upper = BAGUA[upper_num]
    lower = BAGUA[lower_num]
    hex_info = HEXAGRAMS.get((upper_num, lower_num), {
        "name": f"{upper['nature']}{lower['nature']}",
        "keyword": "未知",
        "desc": "卦象待解"
    })
    return (
        f"{hex_info['name']}（{upper['symbol']}{lower['symbol']}）"
        f"· {hex_info['keyword']}"
    )


# ╔══════════════════════════════════════════════════════════════╗
# ║                  插件主类                                    ║
# ╚══════════════════════════════════════════════════════════════╝

@register("astrbot_plugin_meihua", "Author", "梅花易数占卜", "1.0.0", "https://github.com/your/repo")
class MeihuaPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.custom_prompt = self.config.get("custom_divination_prompt", "")
        self.allow_random = self.config.get("allow_random_divination", True)
        self.default_style = self.config.get("default_style", "白话夹文言")
        self.include_xiang = self.config.get("include_xiang_data", True)
        self.max_words = self.config.get("interpretation_max_words", 500)
        if not self.max_words or self.max_words < 200:
            self.max_words = 500
        self.allow_emoji = self.config.get("allow_emoji", False)
        self.allow_action = self.config.get("allow_action_desc", False)
        self.allow_excl = self.config.get("allow_exclamation", False)

        logger.info("🔮 梅花易数占卜插件已加载。")

    @filter.command("占卜")
    async def cmd_zhanbu(self, event: AstrMessageEvent):
        async for result in self._do_divination(event):
            yield result

    @filter.command("起卦")
    async def cmd_qigua(self, event: AstrMessageEvent):
        async for result in self._do_divination(event):
            yield result

    @filter.command("算卦")
    async def cmd_suangua(self, event: AstrMessageEvent):
        async for result in self._do_divination(event):
            yield result

    @filter.command("梅花")
    async def cmd_meihua(self, event: AstrMessageEvent):
        async for result in self._do_divination(event):
            yield result

    @filter.command("梅花易数")
    async def cmd_meihuayishu(self, event: AstrMessageEvent):
        async for result in self._do_divination(event):
            yield result

    @filter.command("卜卦")
    async def cmd_bugua(self, event: AstrMessageEvent):
        async for result in self._do_divination(event):
            yield result

    @filter.command("测卦")
    async def cmd_cegua(self, event: AstrMessageEvent):
        async for result in self._do_divination(event):
            yield result

    @filter.command("问卦")
    async def cmd_wengua(self, event: AstrMessageEvent):
        async for result in self._do_divination(event):
            yield result

    @filter.command("求卦")
    async def cmd_qiugua(self, event: AstrMessageEvent):
        async for result in self._do_divination(event):
            yield result

    def _build_style_instruction(self) -> str:
        if self.custom_prompt:
            instruction = self.custom_prompt
        else:
            instruction = self._get_default_style_prompt()

        prohibitions = []
        if not self.allow_action:
            prohibitions.append("  - 严格禁止添加动作描述（如*走*、*看*、*摇头*等）")
            prohibitions.append("  - 禁止添加角色独白或旁白")
        if not self.allow_emoji:
            prohibitions.append("  - 禁止使用emoji表情")
        if not self.allow_excl:
            prohibitions.append("  - 禁止过度使用感叹号")

        if prohibitions:
            instruction += "\n【禁止事项】\n" + "\n".join(prohibitions)
        return instruction

    def _get_default_style_prompt(self) -> str:
        if self.default_style == "纯白话":
            return (
                "你是一位精通梅花易数的占卜师。你的语言风格遵循以下规则：\n"
                "【核心风格】全部使用现代白话文，通俗易懂。具体要求：\n"
                "  - 全部使用现代汉语白话写作，通顺自然，贴近口语\n"
                "  - 引用卦辞时先用原文，再用白话详细解释\n"
                "  - 开头可用白话总起，如'从这个卦象来看……'\n"
                "  - 避免使用成语串和过度书面化的表达\n"
            )
        elif self.default_style == "古风文言文":
            return (
                "你是一位精通梅花易数的占卜师，道号'观梅子'。你的语言风格遵循以下规则：\n"
                "【核心风格】纯正文言文，古雅简练。具体要求：\n"
                "  - 全部使用文言文写作，不掺杂白话\n"
                "  - 多用四六骈句、之乎者也等虚词\n"
                "  - 引用卦辞时直接使用原文，并用文言深入阐发\n"
                "  - 开头用'观此卦象……'或'夫卦者……'等文言起式\n"
                "  - 语气庄重，不轻浮，不诙谐\n"
            )
        elif self.default_style == "俏皮风格":
            return (
                "你是一位精通梅花易数的占卜师，性格活泼幽默。你的语言风格遵循以下规则：\n"
                "【核心风格】白话为主，接地气，幽默风趣。具体要求：\n"
                "  - 用日常口语化的白话交流，像朋友聊天\n"
                "  - 卦象解读要生动有趣，善用比喻和俏皮话\n"
                "  - 引用卦辞时先用原文，再用大白话翻译\n"
                "  - 开头可用轻松的语气，如'好啦好啦，来看看今天抽到了啥卦～'\n"
                "  - 在专业的基础上，让人读起来会心一笑\n"
            )
        else:
            # 默认：白话夹文言
            return (
                "你是一位精通梅花易数的占卜师，道号'观梅子'。你的语言风格遵循以下规则：\n"
                "【核心风格】白话为主，间杂文言文。具体要求：\n"
                "  - 句子主体为现代白话，通俗易懂\n"
                "  - 关键判断处用四字成语或文言句式点睛，如'此卦体用比和，吉'、'用克体，事恐难成，宜守不宜进'\n"
                "  - 引用卦辞或古语时用文言，解释时转回白话\n"
                "  - 开头可用一句简短文言总起，如'观此卦象……'\n"
            )

    def _build_xiang_block(self, body_trigram, body_trigram_num, use_trigram, use_trigram_num,
                            hu_gua, mutual_upper_num, bian_gua, changed_upper_num) -> str:
        if not self.include_xiang:
            return ""
        return (
            f"【万物类象·按角色精要】\n"
            f" 体卦{body_trigram['name']}（主事之本质）：{get_xiang_summary(body_trigram_num, '体')}\n"
            f" 用卦{use_trigram['name']}（事之来源与影响）：{get_xiang_summary(use_trigram_num, '用')}\n"
            f" 互卦{hu_gua['name']}（过程之变数）：{get_xiang_summary(mutual_upper_num, '互')}\n"
            f" 变卦{bian_gua['name']}（结局之趋向）：{get_xiang_summary(changed_upper_num, '变')}\n"
            f" 注：类象供断卦参考，请在解读中自然融入与所问之事相关者，无需逐项罗列，无关联者不必提及。\n"
        )

    async def _do_divination(self, event: AstrMessageEvent):
        """核心起卦与解读逻辑"""
        # @filter.command 模式下，event.message_str 是命令后的参数部分
        # 例如 "@bot 占卜 3 8 明天考试" → message_str = "3 8 明天考试"
        message_str = event.message_str.strip() if event.message_str else ""
        event_desc = message_str
        has_event = False
        # ── 2. 起卦 ──
        # 梅花易数起卦规则：
        #   2个数字 → 数字起卦：上卦=数1%8，下卦=数2%8，动爻=(数1+数2+时辰)%6
        #   0或1个数字 → 随机起卦：两个随机数，动爻=(随机1+随机2+时辰)%6
        now = datetime.now()
        hour_dizhi_num = get_hour_dizhi_num(now.hour)

        # 提取独立数字token（按空格和常用标点分割，排除日期中的数字如"5.22"）
        tokens = re.split(r'[\s?？。！!,，;；:：]+', message_str) if message_str else []
        standalone_numbers = [t for t in tokens if t.isdigit()]

        # 只有2个及以上独立数字时才用数字起卦，否则走随机
        numbers = standalone_numbers if len(standalone_numbers) >= 2 else []

        if len(numbers) >= 2:
            # 两数起卦
            num1 = int(numbers[0])
            num2 = int(numbers[1])
            upper_num = num1 % 8 or 8
            lower_num = num2 % 8 or 8
            moving_line = (num1 + num2 + hour_dizhi_num) % 6 or 6
            divination_method = f"数字起卦（{num1}、{num2}）"
        elif self.allow_random:
            # 随机起卦
            num1 = random.randint(1, 99)
            num2 = random.randint(1, 99)
            upper_num = num1 % 8 or 8
            lower_num = num2 % 8 or 8
            moving_line = (num1 + num2 + hour_dizhi_num) % 6 or 6
            divination_method = f"随机起卦（{num1}、{num2}）"
        else:
            yield event.plain_result(
                "🔮 请提供两个数字起卦，如「起卦 3 8」。\n"
                "（随机起卦未开启，需手动指定数字。可在插件配置中开启。）"
            )
            return

        # 从事件描述中移除已用于起卦的独立数字，避免LLM看到多余数字
        if numbers:
            for n in numbers[:2]:
                event_desc = event_desc.replace(n, "", 1)
            event_desc = event_desc.strip()
        has_event = bool(event_desc)

        # ── 3. 获取卦象数据 ──
        upper = BAGUA[upper_num]
        lower = BAGUA[lower_num]

        # 本卦
        ben_gua = HEXAGRAMS.get((upper_num, lower_num), {
            "name": f"{upper['nature']}{lower['nature']}",
            "keyword": "未知",
            "desc": "卦象待解"
        })

        # ── 4. 体用分析 ──
        # 动爻在下卦（1-3爻）→ 下卦为用，上卦为体
        # 动爻在上卦（4-6爻）→ 上卦为用，下卦为体
        if moving_line <= 3:
            body_trigram = upper
            use_trigram = lower
            body_trigram_num = upper_num
            use_trigram_num = lower_num
            body_position = "上卦"
            use_position = "下卦"
        else:
            body_trigram = lower
            use_trigram = upper
            body_trigram_num = lower_num
            use_trigram_num = upper_num
            body_position = "下卦"
            use_position = "上卦"

        relation, fortune = get_element_relation(body_trigram["element"], use_trigram["element"])

        # ── 5. 计算互卦 ──
        # 互下卦 = 本卦第2、3、4爻（下卦中爻、下卦上爻、上卦初爻）
        # 互上卦 = 本卦第3、4、5爻（下卦上爻、上卦初爻、上卦中爻）
        L = lower["lines"]  # [初爻, 中爻, 上爻]
        U = upper["lines"]
        mutual_lower_lines = [L[1], L[2], U[0]]
        mutual_upper_lines = [L[2], U[0], U[1]]
        mutual_lower_num = lines_to_trigram(mutual_lower_lines)
        mutual_upper_num = lines_to_trigram(mutual_upper_lines)
        mutual_lower = BAGUA[mutual_lower_num]
        mutual_upper = BAGUA[mutual_upper_num]
        hu_gua = HEXAGRAMS.get((mutual_upper_num, mutual_lower_num), {
            "name": f"{mutual_upper['nature']}{mutual_lower['nature']}",
            "keyword": "未知",
            "desc": "卦象待解"
        })

        # ── 6. 计算变卦 ──
        # 动爻阴阳翻转
        if moving_line <= 3:
            changed_lower_lines = L.copy()
            changed_lower_lines[moving_line - 1] = 1 - changed_lower_lines[moving_line - 1]
            changed_upper_lines = U.copy()
        else:
            changed_lower_lines = L.copy()
            changed_upper_lines = U.copy()
            changed_upper_lines[moving_line - 4] = 1 - changed_upper_lines[moving_line - 4]
        changed_lower_num = lines_to_trigram(changed_lower_lines)
        changed_upper_num = lines_to_trigram(changed_upper_lines)
        changed_lower = BAGUA[changed_lower_num]
        changed_upper = BAGUA[changed_upper_num]
        bian_gua = HEXAGRAMS.get((changed_upper_num, changed_lower_num), {
            "name": f"{changed_upper['nature']}{changed_lower['nature']}",
            "keyword": "未知",
            "desc": "卦象待解"
        })

        # ── 7. 五行细析 ──
        body_element = body_trigram["element"]
        detail_use = get_element_detail(body_element, use_trigram["element"])
        detail_hu_upper = get_element_detail(body_element, mutual_upper["element"])
        detail_hu_lower = get_element_detail(body_element, mutual_lower["element"])
        detail_bian_upper = get_element_detail(body_element, changed_upper["element"])
        detail_bian_lower = get_element_detail(body_element, changed_lower["element"])

        # ── 8. 格式化时间 ──
        year_ganzhi = TIANGAN[(now.year - 4) % 10] + DIZHI[(now.year - 4) % 12]
        hour_dizhi = DIZHI[hour_dizhi_num - 1]
        time_str = f"{year_ganzhi}年{now.month}月{now.day}日{hour_dizhi}时"

        # ── 9. 构建卦象数据摘要（供LLM解读） ──
        data_summary = (
            f"起卦时间：{time_str}\n"
            f"═══════════════════════\n"
            f"【本卦】{ben_gua['name']}（{upper['nature']}上{lower['nature']}下）· {ben_gua['keyword']}\n"
            f"  卦辞：{ben_gua['desc']}\n"
            f"  上卦：{upper['name']}（{upper['element']}·{upper['trait']}） 下卦：{lower['name']}（{lower['element']}·{lower['trait']}）\n"
            f"【互卦】{hu_gua['name']}（{mutual_upper['nature']}上{mutual_lower['nature']}下）· {hu_gua['keyword']}\n"
            f"  卦辞：{hu_gua['desc']}\n"
            f"  上卦：{mutual_upper['name']}（{mutual_upper['element']}） 下卦：{mutual_lower['name']}（{mutual_lower['element']}）\n"
            f"【变卦】{bian_gua['name']}（{changed_upper['nature']}上{changed_lower['nature']}下）· {bian_gua['keyword']}\n"
            f"  卦辞：{bian_gua['desc']}\n"
            f"  上卦：{changed_upper['name']}（{changed_upper['element']}） 下卦：{changed_lower['name']}（{changed_lower['element']}）\n"
            f"【动爻】第{moving_line}爻 · {MOVING_LINE_MEANING[moving_line]}\n"
            f"【体卦】{body_trigram['name']}（{body_trigram['element']}·{body_trigram['trait']}）· {body_position}\n"
            f"【用卦】{use_trigram['name']}（{use_trigram['element']}·{use_trigram['trait']}）· {use_position}\n"
            f"【体用关系】{relation} · {fortune}\n"
            f"═══════════════════════\n"
            f"【五行细析】\n"
            f"  体({body_element}) vs 用({use_trigram['element']})：{detail_use}\n"
            f"  体({body_element}) vs 互上({mutual_upper['element']})：{detail_hu_upper}\n"
            f"  体({body_element}) vs 互下({mutual_lower['element']})：{detail_hu_lower}\n"
            f"  体({body_element}) vs 变上({changed_upper['element']})：{detail_bian_upper}\n"
            f"  体({body_element}) vs 变下({changed_lower['element']})：{detail_bian_lower}\n"
            f"═══════════════════════\n"
            f"{self._build_xiang_block(body_trigram, body_trigram_num, use_trigram, use_trigram_num, hu_gua, mutual_upper_num, bian_gua, changed_upper_num)}"
        )

        # ── 11. 构建解读 prompt（核心：动态风格+禁止项） ──
        base_style_instruction = self._build_style_instruction()

        if has_event:
            # 有事件：结合事件进行关联解读与建议
            interp_prompt = (
                f"{base_style_instruction}\n\n"
                f"以下是起卦所得数据：\n{data_summary}\n"
                f"═══════════════════════\n"
                f"用户所问之事：「{event_desc}」\n\n"
                f"请基于以上卦象数据，结合用户所问之事，进行专业的梅花易数解读。要求：\n"
                f"1. 先以一句简练文言总起，概括此卦对所问之事的整体吉凶\n"
                f"2. 分析本卦体用关系对所问之事的具体影响——用生体则事易成，用克体则事多阻\n"
                f"2.5 当万物类象与所问之事有明显关联时，可据类象推断具体指向（如问考试而遇离主文事、问出行而遇艮主阻滞），若无明显关联则不必强行附会\n"
                f"3. 结合互卦推断事情发展过程中的关键转折与潜在变数\n"
                f"4. 结合变卦推断事情最终走向与结局\n"
                f"5. 综合五行细析，给出针对此事的具体建议——宜进宜退、宜缓宜急\n"
                f"6. 全程白话夹杂文言文，语气可略带俏皮但以专业为主\n"
                f"7. 解读篇幅200-{self.max_words}字，言之有物，不可空泛"
            )
        else:
            # 无事件：单纯解读卦象
            interp_prompt = (
                f"{base_style_instruction}\n\n"
                f"以下是起卦所得数据：\n{data_summary}\n\n"
                f"用户未问具体之事，请单纯解读此卦象。要求：\n"
                f"1. 先以一句简练文言总起，概括此卦整体气象\n"
                f"2. 解读本卦的整体吉凶与寓意——此卦主何事、利何方\n"
                f"2.5 可据体卦万物类象推断此卦最可能对应何类事务、何方、何时，但仅取最相关的一两项，不必面面俱到\n"
                f"3. 分析体用关系所揭示的运势走向——体强则自主，用强则受制\n"
                f"4. 结合互卦看事情发展中的内在潜质与暗流\n"
                f"5. 结合变卦看最终趋势与转机\n"
                f"6. 综合五行细析，给出通用的趋吉避凶之策\n"
                f"7. 全程白话夹杂文言文，语气可略带俏皮但以专业为主\n"
                f"8. 解读篇幅200-{self.max_words}字，言之有物，不可空泛"
            )

        # ── 12. 调用 LLM 生成解读 ──
        system_prompt = None
        interpretation = ""
        try:
            umo = event.unified_msg_origin
            provider_id = await self.context.get_current_chat_provider_id(umo=umo)
            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=interp_prompt,
                system_prompt=system_prompt
            )
            if llm_resp and hasattr(llm_resp, 'completion_text'):
                interpretation = llm_resp.completion_text.strip()
        except Exception as e:
            logger.warning(f"调用 LLM 失败: {e}")

        # ── 13. 组装最终输出 ──
        output_header = (
            f" 梅花易数 · {divination_method}\n\n"
            f" {time_str}\n"
            f"本卦：{format_hexagram_display(upper_num, lower_num)}\n"
            f"卦辞：{ben_gua['desc']}\n"
            f"互卦：{format_hexagram_display(mutual_upper_num, mutual_lower_num)}\n"
            f"变卦：{format_hexagram_display(changed_upper_num, changed_lower_num)}\n"
            f"动爻：第{moving_line}爻 · {MOVING_LINE_MEANING[moving_line]}\n"
            f"体卦：{body_trigram['name']}（{body_trigram['element']}）· {body_position}\n"
            f"用卦：{use_trigram['name']}（{use_trigram['element']}）· {use_position}\n"
            f"体用：{relation} · {fortune}\n"
        )

        if has_event:
            output_header += f"所问：{event_desc}\n"

        if interpretation:
            output = output_header + f"\n─── 卦象解读 ───\n\n{interpretation}"
        else:
            # LLM 调用失败时的降级输出
            output = (
                output_header
                + f"\n─── 卦象概要 ───\n\n"
                f"此卦{ben_gua['name']}，{ben_gua['keyword']}。"
                f"体用{relation}，{fortune}。"
                f"卦辞云：{ben_gua['desc']}。"
                f"互卦{hu_gua['name']}主过程，变卦{bian_gua['name']}主结局。"
            )

        yield event.plain_result(output)
