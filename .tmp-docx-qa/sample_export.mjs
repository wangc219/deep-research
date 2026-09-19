import { Document as WordDocument, Packer, Paragraph as WordParagraph, Table as WordTable, TableRow as WordTableRow, TableCell as WordTableCell, TextRun as WordTextRun, HeadingLevel, WidthType, AlignmentType, PageOrientation, TableLayoutType, ShadingType, BorderStyle, VerticalAlign } from '/Users/hitsz/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/docx/dist/index.mjs';
import { writeFile } from 'node:fs/promises';

const rows = [
  [
    '低空智能蜂群协同侦察与打击平台',
    '侦察感知维度；打击维度；战场控制维度',
    '面向复杂电磁环境和高威胁空域，形成分布式发现、识别、定位、协同决策与多方向持续打击能力。',
    '采用模块化无人机集群、边缘计算节点、抗干扰数据链和任务载荷快速换装结构；通过多源传感器融合、分布式航迹规划与自主编队保持，提升在通信受限条件下的自组织能力。',
    '先由前出节点扩大搜索扇面并完成目标初筛，再由中继节点建立临时网络；集群根据目标价值和威胁等级分配侦察、诱导、压制与打击角色，完成多轴接近、窗口突击和战果复核。',
    '将单平台的有限航程、载荷和生存性转化为集群的空间覆盖、冗余容错和连续施压能力；在敌方防空和通信节点反应前，缩短发现到打击的闭环时间并迫使其分散资源。',
    '以分布式感知换取决策先手，以低成本节点消耗高价值防御资源；通过持续重构编组和多方向突入，放大敌方识别、跟踪和拦截负担。',
  ],
  [
    '自适应认知电子压制节点',
    '电子对抗维度；压制维度；拒止维度',
    '面向敌方雷达、通信和导航链路，形成可感知、可学习、可重构的认知干扰与局部电磁拒止能力。',
    '集成宽带接收机、数字射频存储、功放阵列、干扰效果评估模块和任务级知识库；通过在线信号分类、波形生成和功率调度，适配跳频、低截获概率和组网通信目标。',
    '先对重点频段实施被动侦收和特征提取，再依据威胁排序选择压制方式；干扰节点与火力、无人平台和指挥链协同，动态调整覆盖方向、占空比和功率，完成压制效果评估与策略更新。',
    '把一次性固定参数干扰转化为可持续迭代的电磁对抗闭环，在保持己方通信可用的同时降低敌方感知、指挥和协同效率，为突防与火力行动创造窗口。',
    '关键在于先理解对手信号体系，再以最小必要功率改变其决策质量；利用认知速度和策略更新速度形成局部时间优势。',
  ],
  [
    '跨域无人补给与战损快速恢复系统',
    '生存抗毁维度；战场控制维度',
    '面向分布式作战单元的弹药、能源、备件和数据补给，形成跨域机动、按需投送与战损快速恢复能力。',
    '由无人地面车、无人艇、垂直起降补给机、智能仓储和任务数据平台组成；采用统一接口、数字孪生库存和风险感知路线规划，实现异构平台协同配送和临机改派。',
    '根据作战单元状态、消耗速度和敌情变化预测补给缺口；系统选择隐蔽路线和多批次投送方式，完成前送、接驳、卸载、回收与状态回传，必要时切换为分散缓存和空投模式。',
    '把后勤链从固定节点支撑转为可重构网络支撑，缩短战损单元恢复时间，维持关键方向的持续作战节奏并提高体系抗打击能力。',
    '以补给链的可见性和可重构性对冲敌方纵深打击；用多域冗余和分布式库存避免单点瘫痪。',
  ],
  [
    '超视距协同拦截与末端防护单元',
    '拦截维度；预警维度；生存抗毁维度',
    '面向高速、低可探测和多批次来袭目标，形成远近结合、分层响应和末端补漏的协同防护能力。',
    '融合低轨预警、地面被动探测、主动雷达、红外跟踪和可扩展拦截弹族；以统一火控接口和边缘推理节点支撑多传感器航迹融合与武器分配。',
    '预警节点提前建立航迹并估计目标意图，区域节点完成威胁分级和拦截窗口计算；多单元按射界、剩余弹量和成功概率分配射击任务，末端节点负责漏网目标复核与再拦截。',
    '通过扩大预警纵深和分散拦截责任，提升复杂目标集群下的体系覆盖率；在局部节点受损时仍可保持关键区域的最低防护能力。',
    '以多层传感器和多节点火力形成时间冗余，把敌方突防优势压缩在可管理的局部窗口内。',
  ],
  [
    '海空一体隐蔽通信中继平台',
    '侦察感知维度；战场控制维度；拒止维度',
    '面向跨域编组在复杂地形和强干扰环境下的协同通信，形成按需组网、链路自愈和低特征传输能力。',
    '采用海上无人艇、系留气球、旋翼无人机和软件定义电台组合；以多跳路由、定向波束、低功率突发传输和密钥快速更新保持链路可用。',
    '根据编组位置和威胁态势选择中继层级，先建立最小可用链路，再按任务优先级扩展带宽；出现节点失联时自动重选路由并转移关键控制信息。',
    '提高分散兵力的协同稳定性和抗毁性，减少固定通信节点暴露；让侦察、火力和补给单元在链路受限时仍能维持关键任务同步。',
    '不追求全时高带宽，而是保持关键决策和任务状态的可达性；通过链路冗余与低特征传输延长体系隐蔽窗口。',
  ],
  [
    '自主水下侦察与布设作业系统',
    '侦察感知维度；拒止维度；战场控制维度',
    '面向浅海、港口和关键航道，形成长航时隐蔽侦察、海底目标识别和快速布设作业能力。',
    '集成低噪推进器、合成孔径声呐、磁异常传感器、惯性导航和可更换作业模块；依靠水下自主规划、间歇式通信和海底地图更新完成任务闭环。',
    '平台按风险等级分配搜索航线，先完成区域建图和异常检测，再对重点目标实施近距确认；必要时布设传感器、标记器或阻滞装置，并在窗口期内隐蔽撤离。',
    '在不暴露大型平台的情况下持续积累海域态势信息，提升关键水道的监视、预警和局部拒止能力，为后续水面和空中行动提供先手。',
    '利用隐蔽接近和持久存在制造不对称的信息压力；通过低通信依赖和任务模块更换保持行动弹性。',
  ],
];

const refs = [
  ['蜂群无人机集群', '参考现役蜂群无人机与协同控制技术，侧重分布式感知、编组和低成本消耗。'],
  ['认知电子战吊舱', '参考软件定义电子战载荷和数字射频存储技术，侧重信号学习、干扰重构与效果评估。'],
  ['无人补给车与补给无人机', '参考无人运输平台和末端补给网络，侧重多域投送、库存可视化和临机改派。'],
  ['分层防空拦截系统', '参考多层防空体系和协同火控技术，侧重预警、拦截和末端防护的分层衔接。'],
  ['水下自主航行器', '参考自主水下航行器及海底传感器布设能力，侧重隐蔽侦察与持续存在。'],
];

const weights = (value) => Math.max(1, String(value || '').replace(/\s/g, '').length);
const adaptiveWidths = (data, minimums) => {
  const w = minimums.map((min, col) => Math.sqrt(Math.max(1, data.reduce((sum, row) => sum + weights(row[col]), 0) / Math.max(1, data.length))));
  const free = 100 - minimums.reduce((a, b) => a + b, 0); const total = w.reduce((a, b) => a + b, 0);
  const result = minimums.map((min, i) => min + free * w[i] / total); result[result.length - 1] += 100 - result.reduce((a, b) => a + b, 0); return result;
};
const border = { style: BorderStyle.SINGLE, size: 1, color: 'D9D9D9' };
const makeTable = (head, data, widths) => new WordTable({
  width: { size: 100, type: WidthType.PERCENTAGE }, columnWidths: widths, layout: TableLayoutType.FIXED,
  borders: { top: border, bottom: border, left: border, right: border, insideHorizontal: border, insideVertical: border },
  rows: [head, ...data].map((line, rowIndex) => new WordTableRow({ tableHeader: rowIndex === 0, cantSplit: rowIndex === 0,
    children: line.map((cell, cellIndex) => new WordTableCell({ width: { size: widths[cellIndex], type: WidthType.DXA }, verticalAlign: VerticalAlign.CENTER,
      shading: rowIndex === 0 ? { fill: 'EAF0FF', type: ShadingType.SOLID } : rowIndex % 2 === 0 ? { fill: 'FBFCFF', type: ShadingType.SOLID } : undefined,
      margins: { top: 90, bottom: 90, left: 110, right: 110 }, children: [new WordParagraph({ alignment: cellIndex < 2 ? AlignmentType.CENTER : AlignmentType.LEFT, spacing: { after: 0 }, children: [new WordTextRun({ text: String(cell), bold: rowIndex === 0, size: rowIndex === 0 ? 18 : 17 })] })] })),
  })),
});

const headers = ['装备', '能力分类', '概述', '装备与技术实现', '关键作战流程', '形成能力与作战效果', '制胜逻辑'];
const pageWidth = 16838; const pageHeight = 23811; const totalDxa = pageHeight - 1440;
const mainWidths = adaptiveWidths(rows, [10, 9, 12, 13, 12, 13, 12]).map(v => Math.round(totalDxa * v / 100));
mainWidths[mainWidths.length - 1] += totalDxa - mainWidths.reduce((a, b) => a + b, 0);
const refWidths = [Math.round(totalDxa * 0.22), Math.round(totalDxa * 0.78)];
const doc = new WordDocument({ sections: [{ properties: { page: { size: { orientation: PageOrientation.LANDSCAPE, width: pageWidth, height: pageHeight }, margin: { top: 720, bottom: 720, left: 720, right: 720 } } }, children: [
  new WordParagraph({ heading: HeadingLevel.TITLE, alignment: AlignmentType.CENTER, children: [new WordTextRun({ text: '能力画像', bold: true, size: 30, font: { ascii: 'Arial', hAnsi: 'Arial', eastAsia: 'Microsoft YaHei' } })] }),
  makeTable(headers, rows, mainWidths),
  new WordParagraph({ pageBreakBefore: true, children: [new WordTextRun({ text: '参考装备', bold: true, size: 24 })] }),
  makeTable(['参考装备', '概述'], refs, refWidths),
] }] });

const blob = await Packer.toBlob(doc);
const arrayBuffer = await blob.arrayBuffer();
await writeFile('/Users/hitsz/equipment research/.tmp-docx-qa/capability-export-current.docx', Buffer.from(arrayBuffer));
