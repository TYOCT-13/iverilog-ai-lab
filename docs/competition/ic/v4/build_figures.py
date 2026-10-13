"""Build original diagrams and descriptive charts from recorded evidence."""
from pathlib import Path
import json
import html
import hashlib
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
OUT = HERE / "figures"
OUT.mkdir(parents=True, exist_ok=True)
W, H = 1800, 660
BG, INK, MUTED, CYAN, LINE = "#F7F9FB", "#17212B", "#566575", "#009FBA", "#D8E0E6"
FONT = "C:/Windows/Fonts/msyh.ttc"
FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"
manifest = []


class Figure:
    def __init__(self, name, title, source, subtitle=""):
        self.name, self.source = name, source
        self.im = Image.new("RGB", (W, H), BG)
        self.draw = ImageDraw.Draw(self.im)
        self.svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">', f'<rect width="{W}" height="{H}" fill="{BG}"/>']
        self.text(55, 25, title, 54, INK, True)
        if subtitle:
            self.text(55, 105, subtitle, 30, MUTED)
        self.line(55, 170, 1745, 170, LINE, 2)

    def text(self, x, y, text, size=38, color=INK, bold=False):
        font = ImageFont.truetype(FONT_BOLD if bold else FONT, size)
        for i, part in enumerate(str(text).split("\n")):
            yy = y + i * (size + 12)
            self.draw.text((x, yy), part, font=font, fill=color)
            self.svg.append(f'<text x="{x}" y="{yy + size}" fill="{color}" font-family="Microsoft YaHei" font-size="{size}" font-weight="{700 if bold else 400}">{html.escape(part)}</text>')

    def rect(self, x, y, w, h, fill="white", stroke=LINE):
        self.draw.rectangle((x, y, x+w, y+h), fill=fill, outline=stroke, width=2)
        self.svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')

    def line(self, x, y, xx, yy, color=CYAN, width=4):
        self.draw.line((x, y, xx, yy), fill=color, width=width)
        self.svg.append(f'<line x1="{x}" y1="{y}" x2="{xx}" y2="{yy}" stroke="{color}" stroke-width="{width}"/>')

    def arrow(self, x, y, xx, yy):
        self.line(x, y, xx, yy)
        if xx != x:
            sign = 1 if xx > x else -1
            self.line(xx, yy, xx-sign*16, yy-10)
            self.line(xx, yy, xx-sign*16, yy+10)
        else:
            sign = 1 if yy > y else -1
            self.line(xx, yy, xx-10, yy-sign*16)
            self.line(xx, yy, xx+10, yy-sign*16)

    def box(self, x, y, w, h, number, title, detail, accent=False):
        self.rect(x, y, w, h, "#E8F5F8" if accent else "white")
        self.text(x+20, y+18, number, 31, CYAN, True)
        self.text(x+20, y+65, title, 38, INK, True)
        self.text(x+20, y+124, detail, 29, MUTED)

    def save(self):
        self.svg.append('</svg>')
        self.im.save(OUT / f"{self.name}.png", optimize=True)
        (OUT / f"{self.name}.svg").write_text('\n'.join(self.svg), encoding='utf-8')
        manifest.append({"id": self.name, "source": self.source, "kind": "original schematic or descriptive data chart", "png_sha256": hashlib.sha256((OUT/f'{self.name}.png').read_bytes()).hexdigest()})


def flow(name, title, subtitle, nodes, source, foot):
    f = Figure(name, title, source, subtitle)
    gap, x0, y0 = 38, 55, 220
    width = (1690 - (len(nodes)-1)*gap)/len(nodes)
    for i, (a,b) in enumerate(nodes):
        x = x0 + i*(width+gap)
        f.box(x,y0,width,230,f'{i+1:02}',a,b,i==len(nodes)-1)
        if i < len(nodes)-1:
            f.arrow(x+width+5,y0+110,x+width+gap-6,y0+110)
    f.text(55, 525, foot, 33, MUTED)
    f.save()


flow('theme_map','赛题主题与项目落点','定位于数字 IP 设计阶段的功能验证和教学实训',[
    ('AI 技术','自然语言规划\n反馈驱动探索'),('集成电路设计','RTL 与协议行为\n边界及状态验证'),('工程实现','Icarus 仿真\n独立参考判据'),('应用场景','模块调试\n教学与轻量工具链')],
    'official notice 4756; project v3 report and current application',
    '关联智能设计与综合创新方向；不外推为芯片制造或流片成果')
flow('timeline','迭代重点的变化','按工程能力组织，历史实验保持原始数据和边界',[
    ('单轮计划','规则与 API 输入\n结构化 TestPlan'),('可信判据','参考模型对齐\n逐拍输出检查'),('受限 Agent','格式恢复与预算\n真实反馈摘要'),('交付与试用','跨平台复现\n界面与手册调整')],
    'v3/material_data.json; git f75f619 7059d25 d9ffded; human trial record',
    '工程机制逐步完善；不同实验批次不作为单因素性能提升曲线')
flow('architecture','系统架构','模型规划与本地执行、判据、证据管理分工',[
    ('网页或 CLI','RTL 与接口定义\n目标和设置'),('在线模型 API','结构化动作\n有界请求'),('本地验证','测试台生成\nIcarus 与参考'),('运行证据','结果与波形\nSHA 和重放包')],
    'src/iverilog_ai/ai/agent.py; core/pipeline.py; ui/app.py',
    '使用 DeepSeek Flash API；本机不加载模型权重，不声称已微调 Agent')
flow('preflight','编译与接口前置检查','把依赖、端口与工具错误定位到实际停止阶段',[
    ('完整源码导入','顶层及子模块\n选择目标 module'),('接口确认','端口 时钟 复位\n生成 JSON 并校验'),('编译预检查','Icarus -tnull\n缺失依赖即阻断'),('执行测试','已确认计划\n仿真及输出检查')],
    'git f75f619 and 7059d25; ui/app.py; human trial PC-07',
    '编译通过是执行前提，不构成功能或协议正确性证明')
flow('planner','验证目标的执行路径','自然语言用于指导测试方向，强制检查来自明确判据',[
    ('需求文本','目标与规格\n接口定义'),('模型规划','输入值与周期\n测试意图'),('结构校验','字段与位宽\n采样和预算'),('实际检查','参考或 expected\n受限断言')],
    'ai/planner.py; ai/schema.py; ui/app.py',
    '目标文字不自动成为断言；零比对不能认定功能验证通过')
flow('agent_loop','Agent 补测循环','每轮输入由允许的状态与反馈决定',[
    ('已有计划','先执行原计划\n固定起始输入'),('真实采样','端口位串及 X/Z\n来源交叉绑定'),('缺口反馈','场景及拒绝原因\n剩余预算'),('下一轮提案','追加或独立输入\n反例或预算停止')],
    'ai/agent.py; core/observations.py; core/functional_coverage.py',
    '模型调整测试输入，不自动改写 RTL，也不修改独立参考判据')

f = Figure('oracle_fifo','FIFO 同拍读写的语义修复','spec/sync_fifo_spec.md; rtl/sync_fifo.v','展示计数更新机制，图中没有使用芯片实测波形')
# Replace the source label assigned above with the exact document reference.
f.source = 'spec/sync_fifo_spec.md; rtl/sync_fifo.v; reference_model_alignment tests'
f.box(55,215,760,265,'旧机制','两次赋值更新 count','接受写入：count + 1\n接受读取：count - 1\n后一次非阻塞赋值覆盖前一次')
f.box(985,215,760,265,'修复机制','按接受组合更新一次','仅写：+1    仅读：-1\n同时接受：保持占用量\n空与满边界按前态判定',True)
f.arrow(840,345,960,345)
f.text(55,540,'规格先明确，同时修正 RTL 与参考模型，再逐拍核对输出',35,MUTED)
f.save()

f = Figure('token_ledger','实验预算与失败留存','latest budget receipt','最新两模块完整批次，预算口径为输入加输出 tokens')
f.source='v3/material_data.json latest_new108 tokens; latest budget receipt'
f.box(55,210,510,250,'实际报告用量','339,624 tokens','87 次实际 API 请求\n未知用量预留 0')
f.box(645,210,510,250,'批次共享上限','1,000,000 tokens','剩余额度 660,376\n失败请求保留在分母')
f.box(1235,210,510,250,'受限恢复','原始响应与拒绝原因','格式与计划预算拒绝\n一次重提仍是新请求',True)
f.text(55,530,'网页服务默认输出选项仅省略单次输出参数，不撤销已登记实验总预算',32,MUTED)
f.save()

data=json.loads((ROOT/'docs/competition/ic/v3/material_data.json').read_text(encoding='utf-8'))
labels=['固定模板','随机策略','协议随机','单次 API','反馈 Agent','无反馈 Agent']
for name,key,den,subtitle in [
    ('latest_results','latest_new108',12,'4 个不同缺陷 × 3 次重复；仅作描述性统计'),
    ('historical_results','historical_v8_432',48,'历史 432 任务批次，独立分母与原始失败保持不变')]:
    raw=data[key]
    rows=raw.get('strategies')
    values=[r['detected_samples'] for r in rows]
    f=Figure(name,'缺陷检出任务的完整策略对照',f'v3/material_data.json {key}',subtitle)
    plot_y, baseline, scale=210,500,270/den
    for tick in [0,den//3,2*den//3,den]:
        yy=baseline-tick*scale;f.line(80,yy,1720,yy,LINE,2);f.text(30,yy-18,str(tick),26,MUTED)
    for i,(label,value) in enumerate(zip(labels,values)):
        x=135+i*262;height=value*scale
        f.rect(x,baseline-height,155,height,CYAN if i==4 else '#8493A0',CYAN if i==4 else '#8493A0')
        f.text(x-5,baseline-height-54,f'{value}/{den}',40,INK,True)
        f.text(x-18,530,label,32,INK)
    f.text(55,600,'反馈相对基线的差异不构成显著性、因果性或工业泛化证明',28,MUTED)
    f.save()

flow('engineering','工程可靠性的改进与当前边界','把历史成功和当前失败绑定到各自版本',[
    ('路径可配置','自动发现工具\nWindows 与 Linux'),('证据可搬运','原字节快照\n日志与重放包'),('历史回归','216438d\n云端 5 jobs 成功'),('当前保护失败','df7ccfa\n冻结依赖变更检测')],
    'github_actions_repair_2026-10-08.md; evidence_audit.json',
    '当前提交云端全仓检查未通过；保留冻结实验原件，修复另行验收')
flow('user_trial','异机真人试用发现的问题','有 AI 协助的真实操作反馈，完整复测尚待补充',[
    ('安装与环境','命令缺失和下载\nPATH 与路径差异'),('输入与判据','缺少 bit 子模块\n空 expected 与断言'),('界面定位','表单默认展开\n校验入口过深'),('处理与复测','11 项问题登记\n修复状态分别标注')],
    'docs/trial/other_pc_user_trial_2026-10-13.md',
    '两次编译失败，0 次输出比较；不计为协议通过或独立 H02 完成')
flow('product_changes','用户反馈驱动的产品调整','对比结构与行为变化，不使用未经实测的节时比例',[
    ('入口调整','操作常驻上传区\n蓝色主按钮'),('默认折叠','端口 时钟 JSON\n减少首屏展开'),('校验前置','确认接口后规划\n编译失败阻断执行'),('说明一致','模型模式与用量\n结果字段和手册')],
    'git7059d25 d9ffded 2c6a4d9 671512e d763530',
    '改动已实现与发布；异机用户对新版操作体验的复测待确认')
flow('roadmap','应用落地与后续验证','按可检查的阶段交付，不把规划写成已实现成果',[
    ('当前范围','教学数字 IP\n模块级验证'),('近期验收','冻结夹具修复\n异机与 H02 复核'),('扩展方向','更多规格及参考\n协议从设备环境'),('推广验证','课程或小组试点\n记录用时与效果')],
    'report scope; human trial record; competition IC gap checklist',
    '不声明芯片流片、时序签核、工业协议认证或已测得经济收益')
(OUT/'figure_sources.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(f'Built {len(manifest)} original figures')
