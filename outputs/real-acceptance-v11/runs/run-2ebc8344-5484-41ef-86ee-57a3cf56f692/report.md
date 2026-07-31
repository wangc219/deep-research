# 复杂地形条件下现役低空无人机探测预警体系的传统能力缺口与升级需求 装备能力图像需求报告

## 研究路线
traditional_gap

## 执行摘要
执行摘要：本报告按“traditional_gap”路线展开，结论已通过审计，但仅适合边界化发布。研究主线是：从复杂地形下的传统低空预警作战链出发，对照现役M-LIDS、FS-LIDS、Coyote、Ku波段雷达族与FAAD-C2等公开能力，识别山谷、背坡、林冠、街谷、海岸低空通道中的连续预警缺口，再提出“补盲节点+融合升级”的产品化补位方案。

制胜逻辑不是继续强化单站雷达或单车闭环，而是把“前沿发现—多源确认—本地分级—共同空情分发—分层处置—补网”做成韧性链路。核心原因是复杂地形会放大视距遮挡、杂波误报、链路中断、主动辐射暴露和保障负担，导致“看见目标”不等于“稳定共享并完成授权处置”。

建议的产品方向有两类：一是低SWaP分布式被动补盲节点，前推到沟谷、林缘、街谷和海岸通道，承担低特征初始发现、多点定位、本地告警、中继与快速转移；二是多模态边缘融合与可信分类升级，融合雷达、RF、EO/IR线索，完成目标关联、置信度标注、背景抑制、多源冲突管理，并提供开放接口、多链路备份、缓存转发和断链降级。

证据边界需明确：现有判断主要依据美国陆军、DoD、GAO及相关公开需求、条令、采办材料，另含部分专业期刊与经验性材料。它们能支持体系构成、接口方向和升级需求，但不能直接等同复杂地形实测性能。当前仍缺少公开的探测概率、误报率、识别时间、端到端时延、断链降级、可靠性改进幅度和全寿命保障成本基线；SBIR需求、标称航迹容量或全速生产状态，也不能直接外推为复杂地形下的实战有效覆盖能力。

## Agent覆盖情况
- 已覆盖能力标签：capability_gap, coa, coordination, environment, equipment, lessons, operation, scenario, technology_readiness
- 缺失关键能力标签：无
- 审计状态：approved

## 制胜机理思考维度
- 业务问题链：国际形势/威胁 -> 对抗场景 -> 传统场景/制胜/战法 -> 当前装备对比 -> 能力不足与空白 -> 新能力补位和现有装备升级。
- 四类知识资源：理论工具、局部战争战例、前沿装备与技术情报、持续展开的问题链。
- 六步推理：防御解构 -> 制胜路径 -> 效果链 -> 能力映射 -> 差距量化 -> 文字能力画像。
- 分层门控：L1 制胜逻辑、L2 概念创新、L3 能力画像；证据或覆盖不足时定向再调。

## 制胜机理阶段结论
### L1 制胜逻辑分析
- 置信度：0.72
- 门控：通过
- 原因：满足当前阶段条件

### L2 概念创新评估
- 置信度：0.72
- 门控：通过
- 原因：满足当前阶段条件

### L3 能力图像生成
- 置信度：0.72
- 门控：通过
- 原因：满足当前阶段条件

## 作战能力图像需求

### cap-new-001-r2 低SWaP分布式被动补盲节点
- 类型：新作战能力方向
- 装备类别：任务补位平台、传感器、效应器与协同节点
- 来源制胜逻辑：传统场景/制胜/战法 -> 当前装备对比 -> 能力空白 -> 新功能产品补位
- 关联场景：复杂地形条件下现役低空无人机探测预警体系的传统能力缺口与升级需求
- 优先级：高：关键性高、紧迫性高、可行性中高
- 能力差距：现有装备组合无法覆盖传统作战链中的关键空白节点或极端边界条件；本次基线：[{'system': 'M-LIDS', 'status': '现役条令覆盖的短停式机动C-sUAS体系', 'configuration': 'ATP 3-01.81描述为电子战车加动能拦截车；动能车含KuRFS、Coyote Block 2、EO/IR。', 'interfaces': 'FAAD-C2；可与Link-16互操作。', 'scene_boundary': '可支持机动部队阶段性防护，但短停部署及地基传感器视距属性决定其不能保证在沟谷、背坡、林冠和建筑遮挡区连续预警。', 'confidence': '高（构成和接口）；中等（复杂地形实际效能）'}, {'system': 'FS-LIDS/M-LIDS、Coyote及Ku波段雷达族', 'status': '陆军正式采办项目，FY2024进入全速生产阶段。', 'maturity_signal': '从紧急或过渡性能力向项目化采购和保障转换。', 'boundary': '全速生产代表采办成熟度，不证明各型号在复杂地形、强对抗和多目标饱和下的探测—识别—处置闭环性能。', 'confidence': '高'}, {'system': '传统电子反制手段', 'parameter': '部分干扰/失效技术有效距离约1,000英尺或更低。', 'boundary': '受目标链路、频谱环境、授权及民用通信/导航安全约束；不适宜作为山地、城市等环境唯一预警或处置手段。', 'confidence': '中高'}]；[{'constraint': '低空视距遮挡', 'impact': '山脊背坡、沟谷、林地和建筑密集区使地基雷达与EO/IR出现持续或间歇盲区，压缩告警和传感器交接窗口。', 'defensive_requirement': '采用高低搭配、前沿低SWaP节点、多点交叉定位和可快速转移的中继/边缘融合能力。'}, {'constraint': '多源探测的非对称失效', 'impact': '雷达受地物和杂波影响，RF受静默或非标准链路限制，EO/IR受遮挡和气象限制，电子反制受距离和规则约束。', 'defensive_requirement': '以多模态交叉确认、置信度标注和本地目标关联降低单源漏报与误报；不将被动RF或雷达单独视为完整解。'}, {'constraint': '机动部队连续伴随不足', 'impact': 'M-LIDS短停式双车部署可提供阶段性保护，但难保证高速机动、地形分割部队的连续全向覆盖。', 'defensive_requirement': '将重型LIDS用于关键点/走廊的确认与处置，辅以徒步、车载轻型或临时架设节点承担前沿发现和告警中继。'}, {'constraint': '接口与通信依赖', 'impact': '发现目标若不能经FAAD-C2、Link-16或其他共同态势链路及时共享，将无法稳定转换为授权和处置；集中融合节点也可能形成脆弱点。', 'defensive_requirement': '建设开放数据接口、边缘本地告警、多链路备份、缓存转发和断链降级规则。'}, {'constraint': '保障和可负担性', 'impact': '正式采购推进并未消除备件、软件更新、传感器标定、供电、操作员培训和电子对抗频谱适配的持续负担。', 'defensive_requirement': '按威胁等级分层配置传感器与效应器，优先评估单位覆盖面积的人员、供电、维修、备件和训练需求，而非只比较采购单价。'}]；[{'capability': 'LIDS、Coyote、Ku波段雷达及FAAD-C2基础集成', 'readiness': '高', 'basis': '条令、陆军选型公告和GAO项目状态共同支持。', 'boundary': '成熟的是体系构件与采办状态，非复杂地形全场景探测覆盖。'}, {'capability': '联合共同态势图与跨系统告警分发', 'readiness': '中高', 'basis': 'FAAD-C2互操作和IGSSR-C自动融合需求已明确。', 'boundary': '弱网、断链、电磁压制和多国数据标准条件下的可用性未量化。'}, {'capability': '低SWaP分布式被动低空探测', 'readiness': '中低至中', 'basis': '仍以SBIR需求形式出现。', 'boundary': '缺乏公开复杂地形实测和持续保障数据。'}, {'capability': '便携式电子对抗换代', 'readiness': '中等', 'basis': 'SOCOM下一代便携构型在FY2025进入初始生产。', 'boundary': '电子对抗距离、目标适配性、民用环境约束及抗频谱变化能力决定实际效用。'}]
- 能力画像：在山谷、背坡、林缘、街谷和海岸低空通道前推部署，提供低特征初始发现、多点定位和本地告警。；证据驱动重点：[{'constraints': ['地形遮蔽造成雷达和光电视距盲区', '无人机可利用谷地、山脊背向面和起伏地形降低暴露', '通信中继和供电部署困难'], 'mapped_equipment_functions': ['分布式前沿传感器', '机动补盲雷达/光电节点', '中继通信和边缘融合', '低功耗长续航监视'], 'terrain': '山地/峡谷'}, {'constraints': ['城市峡谷导致遮挡、多径和杂波', '鸟类、民用无人机和建筑热源增加误报', '强干扰可能影响民用通信、导航和公共安全'], 'mapped_equipment_functions': ['多源融合识别', '非协作目标分类', '低附带风险反制', '军地空域与频谱协同接口'], 'terrain': '城市/建筑密集区'}, {'constraints': ['植被遮挡削弱光电和目视确认', '低空小目标与自然背景混杂', '声学和射频探测受环境噪声及传播条件影响'], 'mapped_equipment_functions': ['被动射频与光电复合探测', 'AI辅助背景抑制', '多点交叉定位', '可快速布设的隐蔽传感器'], 'terrain': '林地/丘陵'}, {'constraints': ['海杂波、港口金属结构和民用通信密集', '低空目标可贴近岸线或基础设施活动', '动能处置和强干扰面临航运、航空和通信安全约束'], 'mapped_equipment_functions': ['杂波抑制雷达', '精细化目标识别', '低功率定向反制', '港口/海空域协同告警'], 'terrain': '海岸/港口'}, {'constraints': ['低温、强风、降水和低氧影响设备可靠性与人员持续值守', '云雾和沙尘削弱光电持续跟踪', '补给和维修周期拉长'], 'mapped_equipment_functions': ['环境适应性设计', '多模态传感器冗余', '远程健康监测', '模块化快速更换'], 'terrain': '高原/严寒或恶劣天气区'}, {'constraints': ['GNSS欺骗、链路干扰和频谱拥塞影响无人机、传感器、C2和反制设备', '过度电磁发射可能暴露己方关键节点', '单一数据链失效会导致告警无法闭环'], 'mapped_equipment_functions': ['抗干扰通信', '多链路备份', '被动探测', '边缘自治识别', '电磁暴露管理'], 'terrain': '强电磁对抗环境'}]；[{'critical_interfaces': ['传感器到C2的低时延数据接口', '断链情况下的本地告警与自治规则', '军地空域/频谱协调', '战损后快速重新入网'], 'failure_modes': ['局部发现不能被上送或共享', '多源冲突导致授权迟滞', '高价值效应器过早消耗', '关键节点暴露后空情图断裂'], 'key_nodes': ['前沿被动/混合传感器', '机动雷达/EO-IR补盲节点', '边缘融合与AI分类单元', '防空/C-UAS C2', '电子战与低成本拦截单元', '通信中继与保障分队'], 'task_chain': '前沿发现→多源交叉确认→本地威胁分级→共同空情分发→效应器选择→毁伤/脱离评估→补网'}]；[{'boundary': '无法公开量化不同地形的统一修正系数。', 'conclusion': '山谷、背坡、街谷、林缘和海岸线使低空目标呈现“短时出现—再遮蔽”特征，传统固定点覆盖会出现持续盲区。', 'constraint': '地形遮蔽与低空通道效应'}, {'boundary': '单一传感器不宜承担最终识别责任。', 'conclusion': '低RCS、低热特征、鸟类/车辆/建筑热源/海杂波会推高误报与人工复核负担，压缩处置窗口。', 'constraint': '低慢小与杂波/误报'}, {'boundary': '开放接口是必要条件，不是充分条件。', 'conclusion': '干扰、拥塞和断链会把‘看见目标’变成‘无法稳定共享和授权’，导致局部发现不能转化为体系预警。', 'constraint': '电磁与链路韧性'}, {'boundary': '复杂地形下道路、供电、维修和轮换会放大保障短板。', 'conclusion': '主动辐射节点、固定站和高价值拦截器在持续侦察与消耗战中容易暴露并造成成本失衡。', 'constraint': '生存性与保障'}, {'boundary': '不同国家法规差异大，无法一概外推。', 'conclusion': '城市、机场、港口等区域会限制强干扰和动能处置，迫使体系更依赖精细识别、定向反制和授权前置。', 'constraint': '军地规则约束'}]

### cap-upgrade-001-r2 多模态边缘融合与可信分类升级
- 类型：现有装备升级需求
- 装备类别：现役装备、任务软件、通信指控与保障系统
- 来源制胜逻辑：传统打法目标能力 -> 当前装备参数与运用表现 -> 残余差距 -> 升级需求
- 关联场景：复杂地形条件下现役低空无人机探测预警体系的传统能力缺口与升级需求
- 优先级：中高：紧迫性高、工程可行性高
- 能力差距：现有装备在复杂环境识别、抗干扰、协同接口、任务重构和持续保障方面存在差距；本次基线：[{'system': 'M-LIDS', 'status': '现役条令覆盖的短停式机动C-sUAS体系', 'configuration': 'ATP 3-01.81描述为电子战车加动能拦截车；动能车含KuRFS、Coyote Block 2、EO/IR。', 'interfaces': 'FAAD-C2；可与Link-16互操作。', 'scene_boundary': '可支持机动部队阶段性防护，但短停部署及地基传感器视距属性决定其不能保证在沟谷、背坡、林冠和建筑遮挡区连续预警。', 'confidence': '高（构成和接口）；中等（复杂地形实际效能）'}, {'system': 'FS-LIDS/M-LIDS、Coyote及Ku波段雷达族', 'status': '陆军正式采办项目，FY2024进入全速生产阶段。', 'maturity_signal': '从紧急或过渡性能力向项目化采购和保障转换。', 'boundary': '全速生产代表采办成熟度，不证明各型号在复杂地形、强对抗和多目标饱和下的探测—识别—处置闭环性能。', 'confidence': '高'}, {'system': '传统电子反制手段', 'parameter': '部分干扰/失效技术有效距离约1,000英尺或更低。', 'boundary': '受目标链路、频谱环境、授权及民用通信/导航安全约束；不适宜作为山地、城市等环境唯一预警或处置手段。', 'confidence': '中高'}]；[{'constraint': '低空视距遮挡', 'impact': '山脊背坡、沟谷、林地和建筑密集区使地基雷达与EO/IR出现持续或间歇盲区，压缩告警和传感器交接窗口。', 'defensive_requirement': '采用高低搭配、前沿低SWaP节点、多点交叉定位和可快速转移的中继/边缘融合能力。'}, {'constraint': '多源探测的非对称失效', 'impact': '雷达受地物和杂波影响，RF受静默或非标准链路限制，EO/IR受遮挡和气象限制，电子反制受距离和规则约束。', 'defensive_requirement': '以多模态交叉确认、置信度标注和本地目标关联降低单源漏报与误报；不将被动RF或雷达单独视为完整解。'}, {'constraint': '机动部队连续伴随不足', 'impact': 'M-LIDS短停式双车部署可提供阶段性保护，但难保证高速机动、地形分割部队的连续全向覆盖。', 'defensive_requirement': '将重型LIDS用于关键点/走廊的确认与处置，辅以徒步、车载轻型或临时架设节点承担前沿发现和告警中继。'}, {'constraint': '接口与通信依赖', 'impact': '发现目标若不能经FAAD-C2、Link-16或其他共同态势链路及时共享，将无法稳定转换为授权和处置；集中融合节点也可能形成脆弱点。', 'defensive_requirement': '建设开放数据接口、边缘本地告警、多链路备份、缓存转发和断链降级规则。'}, {'constraint': '保障和可负担性', 'impact': '正式采购推进并未消除备件、软件更新、传感器标定、供电、操作员培训和电子对抗频谱适配的持续负担。', 'defensive_requirement': '按威胁等级分层配置传感器与效应器，优先评估单位覆盖面积的人员、供电、维修、备件和训练需求，而非只比较采购单价。'}]；[{'capability': 'LIDS、Coyote、Ku波段雷达及FAAD-C2基础集成', 'readiness': '高', 'basis': '条令、陆军选型公告和GAO项目状态共同支持。', 'boundary': '成熟的是体系构件与采办状态，非复杂地形全场景探测覆盖。'}, {'capability': '联合共同态势图与跨系统告警分发', 'readiness': '中高', 'basis': 'FAAD-C2互操作和IGSSR-C自动融合需求已明确。', 'boundary': '弱网、断链、电磁压制和多国数据标准条件下的可用性未量化。'}, {'capability': '低SWaP分布式被动低空探测', 'readiness': '中低至中', 'basis': '仍以SBIR需求形式出现。', 'boundary': '缺乏公开复杂地形实测和持续保障数据。'}, {'capability': '便携式电子对抗换代', 'readiness': '中等', 'basis': 'SOCOM下一代便携构型在FY2025进入初始生产。', 'boundary': '电子对抗距离、目标适配性、民用环境约束及抗频谱变化能力决定实际效用。'}]
- 能力画像：融合雷达、RF、EO/IR等线索，执行目标关联、置信度标注、背景抑制和多源冲突管理，降低误报与人工负担。；证据驱动重点：[{'constraints': ['地形遮蔽造成雷达和光电视距盲区', '无人机可利用谷地、山脊背向面和起伏地形降低暴露', '通信中继和供电部署困难'], 'mapped_equipment_functions': ['分布式前沿传感器', '机动补盲雷达/光电节点', '中继通信和边缘融合', '低功耗长续航监视'], 'terrain': '山地/峡谷'}, {'constraints': ['城市峡谷导致遮挡、多径和杂波', '鸟类、民用无人机和建筑热源增加误报', '强干扰可能影响民用通信、导航和公共安全'], 'mapped_equipment_functions': ['多源融合识别', '非协作目标分类', '低附带风险反制', '军地空域与频谱协同接口'], 'terrain': '城市/建筑密集区'}, {'constraints': ['植被遮挡削弱光电和目视确认', '低空小目标与自然背景混杂', '声学和射频探测受环境噪声及传播条件影响'], 'mapped_equipment_functions': ['被动射频与光电复合探测', 'AI辅助背景抑制', '多点交叉定位', '可快速布设的隐蔽传感器'], 'terrain': '林地/丘陵'}, {'constraints': ['海杂波、港口金属结构和民用通信密集', '低空目标可贴近岸线或基础设施活动', '动能处置和强干扰面临航运、航空和通信安全约束'], 'mapped_equipment_functions': ['杂波抑制雷达', '精细化目标识别', '低功率定向反制', '港口/海空域协同告警'], 'terrain': '海岸/港口'}, {'constraints': ['低温、强风、降水和低氧影响设备可靠性与人员持续值守', '云雾和沙尘削弱光电持续跟踪', '补给和维修周期拉长'], 'mapped_equipment_functions': ['环境适应性设计', '多模态传感器冗余', '远程健康监测', '模块化快速更换'], 'terrain': '高原/严寒或恶劣天气区'}, {'constraints': ['GNSS欺骗、链路干扰和频谱拥塞影响无人机、传感器、C2和反制设备', '过度电磁发射可能暴露己方关键节点', '单一数据链失效会导致告警无法闭环'], 'mapped_equipment_functions': ['抗干扰通信', '多链路备份', '被动探测', '边缘自治识别', '电磁暴露管理'], 'terrain': '强电磁对抗环境'}]；[{'critical_interfaces': ['传感器到C2的低时延数据接口', '断链情况下的本地告警与自治规则', '军地空域/频谱协调', '战损后快速重新入网'], 'failure_modes': ['局部发现不能被上送或共享', '多源冲突导致授权迟滞', '高价值效应器过早消耗', '关键节点暴露后空情图断裂'], 'key_nodes': ['前沿被动/混合传感器', '机动雷达/EO-IR补盲节点', '边缘融合与AI分类单元', '防空/C-UAS C2', '电子战与低成本拦截单元', '通信中继与保障分队'], 'task_chain': '前沿发现→多源交叉确认→本地威胁分级→共同空情分发→效应器选择→毁伤/脱离评估→补网'}]；[{'boundary': '无法公开量化不同地形的统一修正系数。', 'conclusion': '山谷、背坡、街谷、林缘和海岸线使低空目标呈现“短时出现—再遮蔽”特征，传统固定点覆盖会出现持续盲区。', 'constraint': '地形遮蔽与低空通道效应'}, {'boundary': '单一传感器不宜承担最终识别责任。', 'conclusion': '低RCS、低热特征、鸟类/车辆/建筑热源/海杂波会推高误报与人工复核负担，压缩处置窗口。', 'constraint': '低慢小与杂波/误报'}, {'boundary': '开放接口是必要条件，不是充分条件。', 'conclusion': '干扰、拥塞和断链会把‘看见目标’变成‘无法稳定共享和授权’，导致局部发现不能转化为体系预警。', 'constraint': '电磁与链路韧性'}, {'boundary': '复杂地形下道路、供电、维修和轮换会放大保障短板。', 'conclusion': '主动辐射节点、固定站和高价值拦截器在持续侦察与消耗战中容易暴露并造成成本失衡。', 'constraint': '生存性与保障'}, {'boundary': '不同国家法规差异大，无法一概外推。', 'conclusion': '城市、机场、港口等区域会限制强干扰和动能处置，迫使体系更依赖精细识别、定向反制和授权前置。', 'constraint': '军地规则约束'}]

## 最终回答：需要发展什么功能的产品

- 低SWaP分布式被动补盲节点：在山谷、背坡、林缘、街谷和海岸低空通道前推部署，提供低特征初始发现、多点定位和本地告警。；证据驱动重点：[{'constraints': ['地形遮蔽造成雷达和光电视距盲区', '无人机可利用谷地、山脊背向面和起伏地形降低暴露', '通信中继和供电部署困难'], 'mapped_equipment_functions': ['分布式前沿传感器', '机动补盲雷达/光电节点', '中继通信和边缘融合', '低功耗长续航监视'], 'terrain': '山地/峡谷'}, {'constraints': ['城市峡谷导致遮挡、多径和杂波', '鸟类、民用无人机和建筑热源增加误报', '强干扰可能影响民用通信、导航和公共安全'], 'mapped_equipment_functions': ['多源融合识别', '非协作目标分类', '低附带风险反制', '军地空域与频谱协同接口'], 'terrain': '城市/建筑密集区'}, {'constraints': ['植被遮挡削弱光电和目视确认', '低空小目标与自然背景混杂', '声学和射频探测受环境噪声及传播条件影响'], 'mapped_equipment_functions': ['被动射频与光电复合探测', 'AI辅助背景抑制', '多点交叉定位', '可快速布设的隐蔽传感器'], 'terrain': '林地/丘陵'}, {'constraints': ['海杂波、港口金属结构和民用通信密集', '低空目标可贴近岸线或基础设施活动', '动能处置和强干扰面临航运、航空和通信安全约束'], 'mapped_equipment_functions': ['杂波抑制雷达', '精细化目标识别', '低功率定向反制', '港口/海空域协同告警'], 'terrain': '海岸/港口'}, {'constraints': ['低温、强风、降水和低氧影响设备可靠性与人员持续值守', '云雾和沙尘削弱光电持续跟踪', '补给和维修周期拉长'], 'mapped_equipment_functions': ['环境适应性设计', '多模态传感器冗余', '远程健康监测', '模块化快速更换'], 'terrain': '高原/严寒或恶劣天气区'}, {'constraints': ['GNSS欺骗、链路干扰和频谱拥塞影响无人机、传感器、C2和反制设备', '过度电磁发射可能暴露己方关键节点', '单一数据链失效会导致告警无法闭环'], 'mapped_equipment_functions': ['抗干扰通信', '多链路备份', '被动探测', '边缘自治识别', '电磁暴露管理'], 'terrain': '强电磁对抗环境'}]；[{'critical_interfaces': ['传感器到C2的低时延数据接口', '断链情况下的本地告警与自治规则', '军地空域/频谱协调', '战损后快速重新入网'], 'failure_modes': ['局部发现不能被上送或共享', '多源冲突导致授权迟滞', '高价值效应器过早消耗', '关键节点暴露后空情图断裂'], 'key_nodes': ['前沿被动/混合传感器', '机动雷达/EO-IR补盲节点', '边缘融合与AI分类单元', '防空/C-UAS C2', '电子战与低成本拦截单元', '通信中继与保障分队'], 'task_chain': '前沿发现→多源交叉确认→本地威胁分级→共同空情分发→效应器选择→毁伤/脱离评估→补网'}]；[{'boundary': '无法公开量化不同地形的统一修正系数。', 'conclusion': '山谷、背坡、街谷、林缘和海岸线使低空目标呈现“短时出现—再遮蔽”特征，传统固定点覆盖会出现持续盲区。', 'constraint': '地形遮蔽与低空通道效应'}, {'boundary': '单一传感器不宜承担最终识别责任。', 'conclusion': '低RCS、低热特征、鸟类/车辆/建筑热源/海杂波会推高误报与人工复核负担，压缩处置窗口。', 'constraint': '低慢小与杂波/误报'}, {'boundary': '开放接口是必要条件，不是充分条件。', 'conclusion': '干扰、拥塞和断链会把‘看见目标’变成‘无法稳定共享和授权’，导致局部发现不能转化为体系预警。', 'constraint': '电磁与链路韧性'}, {'boundary': '复杂地形下道路、供电、维修和轮换会放大保障短板。', 'conclusion': '主动辐射节点、固定站和高价值拦截器在持续侦察与消耗战中容易暴露并造成成本失衡。', 'constraint': '生存性与保障'}, {'boundary': '不同国家法规差异大，无法一概外推。', 'conclusion': '城市、机场、港口等区域会限制强干扰和动能处置，迫使体系更依赖精细识别、定向反制和授权前置。', 'constraint': '军地规则约束'}]
- 多模态边缘融合与可信分类升级：融合雷达、RF、EO/IR等线索，执行目标关联、置信度标注、背景抑制和多源冲突管理，降低误报与人工负担。；证据驱动重点：[{'constraints': ['地形遮蔽造成雷达和光电视距盲区', '无人机可利用谷地、山脊背向面和起伏地形降低暴露', '通信中继和供电部署困难'], 'mapped_equipment_functions': ['分布式前沿传感器', '机动补盲雷达/光电节点', '中继通信和边缘融合', '低功耗长续航监视'], 'terrain': '山地/峡谷'}, {'constraints': ['城市峡谷导致遮挡、多径和杂波', '鸟类、民用无人机和建筑热源增加误报', '强干扰可能影响民用通信、导航和公共安全'], 'mapped_equipment_functions': ['多源融合识别', '非协作目标分类', '低附带风险反制', '军地空域与频谱协同接口'], 'terrain': '城市/建筑密集区'}, {'constraints': ['植被遮挡削弱光电和目视确认', '低空小目标与自然背景混杂', '声学和射频探测受环境噪声及传播条件影响'], 'mapped_equipment_functions': ['被动射频与光电复合探测', 'AI辅助背景抑制', '多点交叉定位', '可快速布设的隐蔽传感器'], 'terrain': '林地/丘陵'}, {'constraints': ['海杂波、港口金属结构和民用通信密集', '低空目标可贴近岸线或基础设施活动', '动能处置和强干扰面临航运、航空和通信安全约束'], 'mapped_equipment_functions': ['杂波抑制雷达', '精细化目标识别', '低功率定向反制', '港口/海空域协同告警'], 'terrain': '海岸/港口'}, {'constraints': ['低温、强风、降水和低氧影响设备可靠性与人员持续值守', '云雾和沙尘削弱光电持续跟踪', '补给和维修周期拉长'], 'mapped_equipment_functions': ['环境适应性设计', '多模态传感器冗余', '远程健康监测', '模块化快速更换'], 'terrain': '高原/严寒或恶劣天气区'}, {'constraints': ['GNSS欺骗、链路干扰和频谱拥塞影响无人机、传感器、C2和反制设备', '过度电磁发射可能暴露己方关键节点', '单一数据链失效会导致告警无法闭环'], 'mapped_equipment_functions': ['抗干扰通信', '多链路备份', '被动探测', '边缘自治识别', '电磁暴露管理'], 'terrain': '强电磁对抗环境'}]；[{'critical_interfaces': ['传感器到C2的低时延数据接口', '断链情况下的本地告警与自治规则', '军地空域/频谱协调', '战损后快速重新入网'], 'failure_modes': ['局部发现不能被上送或共享', '多源冲突导致授权迟滞', '高价值效应器过早消耗', '关键节点暴露后空情图断裂'], 'key_nodes': ['前沿被动/混合传感器', '机动雷达/EO-IR补盲节点', '边缘融合与AI分类单元', '防空/C-UAS C2', '电子战与低成本拦截单元', '通信中继与保障分队'], 'task_chain': '前沿发现→多源交叉确认→本地威胁分级→共同空情分发→效应器选择→毁伤/脱离评估→补网'}]；[{'boundary': '无法公开量化不同地形的统一修正系数。', 'conclusion': '山谷、背坡、街谷、林缘和海岸线使低空目标呈现“短时出现—再遮蔽”特征，传统固定点覆盖会出现持续盲区。', 'constraint': '地形遮蔽与低空通道效应'}, {'boundary': '单一传感器不宜承担最终识别责任。', 'conclusion': '低RCS、低热特征、鸟类/车辆/建筑热源/海杂波会推高误报与人工复核负担，压缩处置窗口。', 'constraint': '低慢小与杂波/误报'}, {'boundary': '开放接口是必要条件，不是充分条件。', 'conclusion': '干扰、拥塞和断链会把‘看见目标’变成‘无法稳定共享和授权’，导致局部发现不能转化为体系预警。', 'constraint': '电磁与链路韧性'}, {'boundary': '复杂地形下道路、供电、维修和轮换会放大保障短板。', 'conclusion': '主动辐射节点、固定站和高价值拦截器在持续侦察与消耗战中容易暴露并造成成本失衡。', 'constraint': '生存性与保障'}, {'boundary': '不同国家法规差异大，无法一概外推。', 'conclusion': '城市、机场、港口等区域会限制强干扰和动能处置，迫使体系更依赖精细识别、定向反制和授权前置。', 'constraint': '军地规则约束'}]
## 证据索引

- ev-combat_scenario-web-f5b871d2abb2：英国国防部将乌克兰战场描述为无人系统普及、战场数字化和高强度电子战并存的环境，并强调反无人能力需要以作战相关速度快速迭代。（Defence Drone Strategy - the UK’s approach to Defence Uncrewed Systems - GOV.UK，B级，https://www.gov.uk/government/publications/defence-drone-strategy-the-uks-approach-to-defence-uncrewed-systems/defence-drone-strategy-the-uks-approach-to-defence-uncrewed-systems，位置=text:d9c90819f551e67c#p6，artifact=html:5f8da01f3af3a2f8,text:d9c90819f551e67c）
- ev-operational_employment-web-281d9196c4ee：2025年陆军资助通告再次将低空多架sUAS探测不足归因于地形、曲率与遮障，并强调轻量化、模块化和前沿使用。（Army SBIR|STTR Launches $2M Funding Opportunity for Low-Altitude sUAS Detection – Army SBIR|STTR Program，B级，https://armysbir.army.mil/announcement/launch-2m-funding-opportunity-low-altitude-suas-detection/，位置=text:25198a09cef1a9f3#p1，artifact=html:b5f7f050ff734f58,text:25198a09cef1a9f3）
- ev-operational_employment-web-3d6f178c0a98：CSIS Missile Threat以公开案例说明，低空飞行武器和无人机能够利用传统防空部署、覆盖方向和低空监视上的空缺实施突防。（Don't Waste This Lesson: How drone attacks reveal fixable flaws with American air defenses | Missile Threat，B级，https://missilethreat.csis.org/how-drone-attacks-reveal-fixable-flaws-with-american-air-defenses/，位置=text:499b546bdd99ab14#p3，artifact=html:806905330b6817f7,text:499b546bdd99ab14）
- ev-operational_employment-web-9ca48c4ae0bc：CSIS认为，美国现有空情监视对无人机仍是不完整图景，传统雷达不适合持续跟踪小型低空无人机，而Remote ID不足以覆盖敌对或不合作目标。（Why Are There So Many Unexplained Drones Flying Over the United States?，B级，https://www.csis.org/analysis/why-are-there-so-many-unexplained-drones-flying-over-united-states，位置=text:f0a6d2a60b4c515c#p1，artifact=html:46b4c40411e76c33,text:f0a6d2a60b4c515c）
- ev-weapon_equipment-web-85d513d8dda4：{
  "findings": [
    "传统低空预警体系的核心缺口是物理视距受限：美国陆军2025年需求文件明确指出，地球曲率、地形和障碍物会压缩地基雷达对低空小型无人机的探测距离；山脊背坡、沟谷、密集林地与城市街谷会使单站雷达、RF侦测或光电设备形成持续盲区，预警时间难以稳定满足任务需求。",
    "现役LIDS代表“雷达+RF/电子战+EO/IR+指挥控制+效应器”的成熟集成路线。FS-LIDS适于相对固定重点目标防护，M-LIDS适于伴随机动；但其探测、识别和处置能力仍依赖传感器视线、频谱环境、部署位置及外部指挥网，不能仅凭单个平台覆盖复杂地形。",
    "现役体系已有较强的多目标处理和组网基础：公开资料称M-LIDS采用Ku波段火控雷达、可同时跟踪256个目标，面向Group 1—3无人机；FAAD-C2、Joint Data Network和TAK等接口支持将异构传感器、任务单位和上级防空节点接入共同态势图。但“可接入”不等于复杂地形下已实现稳定、低时延、跨域融合。",
    "传统系统的机动与生存性构成现实短板。专业军刊材料称M-LIDS短停展开约需7分钟，主动雷达辐射可能增加被侦察、游荡弹药或火力定位的风险；早期M-ATV型M-LIDS还暴露可靠性和性能问题，促成向Stryker单车2.1型迭代。复杂地形下，频繁转移、供电、道路通行和维修保障会进一步放大这些约束。",
    "升级方向已从“增强单部雷达”转向分布式、低SWaP和开放接口的多模态感知。陆军低空被动探测SBIR项目要求覆盖0—6,000英尺AGL、至少3分钟告警、模块化开放架构并接入TAK及陆军报告系统；这反映出前沿补盲、低可探测部署和跨节点融合的明确需求，但该项目是研发需求，不能视为已验证的现役性能。",
    "保障与成本边界要求采取分层配置而非以高价值拦截系统覆盖全部空域。FY2025美国陆军C-sUAS采购申请约2.801亿美元，另有约1.174亿美元的C-sUAS拦截器采购申请，表明体系建设同时受传感、指控、效应器和持续补给共同驱动；公开材料不足以推导单套LIDS全寿命成本或复杂地形单位面积覆盖成本。"
  ],
  "confidence": 0.81,
  "open_questions": [
    "公开资料未给出FS-LIDS、M-LIDS在山地、林地和城市峡谷中针对不同RCS/速度/高度小型无人机的实测探测距离、虚警率和识别时间，无法形成可审计的地形修正覆盖模型。",
    "低空被动探测项目的原型测试结果、实际探测概率、抗非合作/静默飞行无人机能力及量产节点尚未在所给来源中得到证实。",
    "FAAD-C2、TAK和Joint Data Network在弱通信、断续链路、多国伙伴或高电磁对抗条件下的端到端时延、数据质量和降级运行机制仍缺少公开量化证据。",
    "M-LIDS Stryker 2.1相较早期M-ATV型号的可靠性改进幅度、人员编制、油电消耗、备件周转与全寿命成本未见公开一致数据。"
  ],
  "handoff_summary": "面向复杂地形的防御性升级，应以“分布式前沿发现—多模态交叉确认—开放指控融合—分层处置”替代单站雷达或单车系统的全域覆盖假设。现役LIDS及FAAD-C2路线已具备可用集成基础，但山脊/沟谷/建筑遮挡、主动辐射暴露、展开时间、数量有限和保障负担仍限制其伴随与持续覆盖。需求优先级应置于低SWaP被动节点、可快速前推或高点部署的补盲载荷、断链条件下的本地关联告警、与既有FAAD-C2/TAK/JDN兼容的数据接口，以及可负担的规模化保障；不应将SBIR指标或雷达标称航迹容量直接等同于实战有效覆盖能力。",
  "search_plan": [
    {
      "track": "复杂地形实测性能与反证",
      "queries": [
        "site:dote.osd.mil C-sUAS terrain masking detection range operational test",
        "site:gao.gov counter UAS radar terrain urban canyon detection report",
        "site:army.mil LIDS mountain terrain operational assessment"
      ]
    },
    {
      "track": "在研被动探测成熟度与接口验证",
      "queries": [
        "site:armysbir.army.mil \"Low-Altitude Passive Detection System\" award prototype",
        "site:army.mil passive counter UAS TAK FAAD C2 test",
        "site:api.army.mil M-LIDS Stryker 2.1 reliability sustainment"
      ]
    },
    {
      "track": "保障成本与部署规模",
      "queries": [
        "site:comptroller.defense.gov LIDS sustainment cost FY2025",
        "site:army.mil M-LIDS fielding unit personnel maintenance",
        "site:gao.gov counter small UAS sustainment procurement cost"
      ]
    }
  ],
  "contradictions": [
    "SBIR文件确认传统地基雷达受低空地形遮蔽限制，并提出至少3分钟告警这一目标；但它是需求/征集文件，不构成任何被动探测方案已达到该告警时间或覆盖0—6,000英尺AGL的验证证据。",
    "M-LIDS公开资料中的“256目标同时跟踪”是传感器标称航迹处理参数，不等同于在遮蔽地形、低RCS、杂波、通信受限或集群饱和条件下的有效发现、分类、识别和交战容量。",
    "FM 3-01和陆军采办资料显示LIDS已部署且集成多类传感器与效应器，说明体系成熟度较高；DOT&E FY2020报告同时显示当时部分手持反制系统不具备独立探测能力、依赖外部引导或目视，反证“所有C-sUAS装备均单装闭环”的假设。",
    "主动雷达的辐射暴露和约7分钟展开时间主要来自军种专业期刊文章，具有作战经验价值但不是正式测试基线；其适用性可能随雷达工作方式、平台状态、地形、敌方侦察能力和战术规程而变化。",
    "替代解释是复杂地形中的主要瓶颈未必总是雷达本身：无人机静默飞行、非标准控制链路、地面杂波、EO/IR气象限制、RF误报以及数据链中断均可能导致预警失败。因此被动RF不能单独替代雷达和光电，而应作为冗余感知层。"
  ],
  "confidence_basis": "结论由美国陆军需求、条令、采办机构资料、作战测试报告、军方专业出版物及国防预算等多类一手或准一手公开来源交叉支撑。地形遮蔽、现役LIDS构成、接口升级方向和采购投入均有直接来源支持；但复杂地形下的实测距离、探测概率、虚警率、可靠性改进量和单套全寿命成本未公开，故对具体性能边界保持中等不确定性。军种专业文章中有关展开时间、辐射暴露和数量不足的判断按经验性证据处理，未作为唯一结论依据。",
  "source_claims": [
    {
      "url": "https://armysbir.army.mil/topics/low-altitude-passive-detection-system/",
      "claim": "陆军低空被动探测项目明确称，地球曲率、地形和障碍物会限制地基雷达对低空小型无人机的探测距离；项目要求面向0—6,000英尺AGL、低SWaP、模块化被动探测，目标为至少3分钟告警，并要求接入TAK和其他陆军系统。"
    },
    {
      "url": "https://www.dote.osd.mil/Portals/97/pub/reports/FY2020/other/2020DOTEAnnualReport.pdf?ver=rvLsaCQ_njLmPDrNIFJBWQ%3D%3D",
      "claim": "DOT&E FY2020评估覆盖5个海外地点、11套系统和281架次；典型C-sUAS体系组合包括雷达、RF扫描与EO/IR，且部分手持系统不具备自身探测能力，需外部引导或人工目视。"
    },
    {
      "url": "https://rdl.train.army.mil/catalog-ws/view/100.ATSC/C01CC9C1-DA1C-4D5E-A6EB-5FCFAE218DCD-1398170439966/FM_3_01wc1.pdf?utm_source=openai",
      "claim": "FM 3-01将LIDS列为部署中的C-sUAS体系，区分固定型FS-LIDS与机动型M-LIDS；其基础组合包括空情监视雷达、C-UAS电子战与EO/IR，机动型还包括测向、多任务雷达和30毫米炮。"
    },
    {
      "url": "https://asc.army.mil/web/news-innovation-draws-international-interest/",
      "claim": "美国陆军采办资料称FS-LIDS集成FAAD C2、反无人机电子战、EO/IR、测向、网状IP电台、AN/TPQ-50多任务雷达、Ku波段雷达及Coyote Block 2；LIDS最初于2017年部署至美国中央司令部责任区。"
    },
    {
      "url": "https://api.army.mil/e2/c/downloads/2025/05/21/71f75107/equipment-at-army-festival-parade.pdf",
      "claim": "陆军公开资料称M-LIDS Single Vehicle 2.1基于Stryker平台、面向Group 1—3无人机；其Ku波段火控雷达标称可同时跟踪256个目标，Coyote拦截器速度为125—150米/秒，并指出该型号旨在解决早期M-ATV M-LIDS的可靠性和性能问题。"
    },
    {
      "url": "https://www.lineofdeparture.army.mil/Journals/Air-Defense-Artillery/ADA-Archive/2026-E-Edition/Armor-in-2025/",
      "claim": "美国陆军专业期刊文章称，M-LIDS的KU-720雷达对Group 1/2及FPV目标有效，但短停展开约需7分钟；文章同时认为主动辐射会增加被敌无人机、游荡弹药和炮兵定位的风险，并以一个师仅获5套系统说明数量与饱和压力。"
    },
    {
      "url": "https://www.army.mil/article/236713/army_announces_selection_of_interim_c_suas_systems?utm_source=openai",
      "claim": "美国陆军2020年公告显示，国防部从已部署能力中选择FS-LIDS、NINJA、CORIAN、L-MADIS及若干单兵系统作为临时C-sUAS能力；FAAD-C2及可互操作系统被定位为指挥控制核心，并计划接入MEDUSA C2。"
    },
    {
      "url": "https://www.armyupress.army.mil/Journals/Military-Review/Online-Exclusive/2024-OLE/C-UAS-Operations/",
      "claim": "陆军大学出版社文章称，FAAD-C2已由旅级防空和空域管理用途扩展至连级，并以单一界面融合传感器；Joint Data Network可向不同层级共享近实时共同态势图。"
    },
    {
      "url": "https://comptroller.defense.gov/Portals/45/Documents/defbudget/FY2025/FY2025_p1.pdf",
      "claim": "美国陆军FY2025 P-1采购预算中，Counter Small Unmanned Aerial System采购线FY2023实际约2.998亿美元、FY2024持续决议调整约3.654亿美元、FY2025申请约2.801亿美元；Counter Small UAS Interceptor采购线FY2025申请约1.174亿美元。"
    }
  ],
  "analysis_sections": {
    "current_parameters": [
      {
        "system": "FS-LIDS",
        "status": "现役/已部署体系",
        "configuration": "FAAD C2、反无人机电子战、EO/IR、测向、网状IP电台、AN/TPQ-50多任务雷达、Ku波段雷达、Coyote Block 2",
        "interface": "FAAD-C2；可互操作C2体系",
        "scene_boundary": "适于重点目标固定防护；单站低空视距仍受山脊、建筑、林冠和地形遮蔽约束",
        "source_date": "采办资料未在发现材料中明确发布日期；部署起点为2017年",
        "confidence": "中高"
      },
      {
        "system": "M-LIDS Single Vehicle 2.1",
        "status": "现役迭代型/公开展示资料",
        "platform_and_target_set": "Stryker平台，面向Group 1—3无人机",
        "parameters": "Ku波段火控雷达标称同时跟踪256目标；Coyote拦截器速度125—150米/秒",
        "mobility_and_maintenance": "为处理早期M-ATV M-LIDS可靠性和性能问题而迭代；公开资料未给出MTBF、维修工时或油电消耗",
        "scene_boundary": "可伴随机动但短停展开约7分钟的说法仅见专业期刊，需按条件性经验数据使用",
        "source_date": "2025年陆军公开资料；展开时间来自2026年专业期刊",
        "confidence": "中等"
      },
      {
        "system": "传统C-sUAS传感链",
        "status": "DOT&E测试样本中的典型架构",
        "configuration": "雷达、RF扫描、EO/IR；部分手持反制装置需外部探测或人工目视",
        "parameters": "FY2020报告样本为5处海外地点、11套系统、281架次",
        "scene_boundary": "传感器组合提升交叉确认能力，但不保证每个平台独立完成发现—识别—处置闭环",
        "source_date": "FY2020",
        "confidence": "高"
      }
    ],
    "development_models": [
      {
        "model": "Low-Altitude Passive Detection System",
        "stage": "SBIR在研需求，非已部署能力",
        "required_capability": "0—6,000英尺AGL；至少3分钟告警；低成本、低SWaP、模块化被动探测",
        "integration": "模块化开放系统方法；接入TAK、陆军报告系统；适配Group 1小型或系留无人机载荷接口",
        "upgrade_value": "面向地形遮蔽、前沿补盲、降低主动辐射特征和快速分布部署",
        "maturity_boundary": "未提供原型实测性能、量产时间或复杂地形效能数据",
        "confidence": "高（需求存在）；低至中（能力兑现）"
      },
      {
        "model": "LIDS体系迭代与共同指控",
        "stage": "现役集成能力持续升级",
        "direction": "FS-LIDS/M-LIDS与FAAD-C2、MEDUSA C2、Joint Data Network和TAK等互操作接口结合",
        "upgrade_value": "将异构传感器、任务单位和上级防空节点纳入共享空情与传感器引导效应器链路",
        "maturity_boundary": "公开资料仅证明接口和组织方向，未量化断链、拥塞或对抗条件下的融合质量",
        "confidence": "中高"
      }
    ],
    "technology_readiness": [
      {
        "capability": "雷达+RF+EO/IR+电子战+拦截器集成",
        "readiness": "高",
        "basis": "LIDS已部署，且被列入条令与临时C-sUAS能力遴选",
        "boundary": "部署成熟不等同于对全部低空小目标、所有地形和集群饱和场景均有效"
      },
      {
        "capability": "FAAD-C2/JDN跨层级态势共享",
        "readiness": "中高",
        "basis": "已有陆军体系应用和向连级下沉的公开描述",
        "boundary": "开放接口、数据标准和网络可用性仍是效能前提"
      },
      {
        "capability": "低SWaP分布式被动低空探测",
        "readiness": "中低至中",
        "basis": "2025年仍以SBIR项目需求提出",
        "boundary": "无公开的复杂地形实测探测概率、抗干扰、误报率和规模化保障数据"
      },
      {
        "capability": "M-LIDS平台可靠性改进",
        "readiness": "中等",
        "basis": "Stryker 2.1针对早期M-ATV系统问题迭代",
        "boundary": "改进幅度及长期保障数据未公开"
      }
    ],
    "capability_constraints": [
      {
        "constraint": "地形和障碍物遮蔽",
        "impact": "低空目标在背坡、沟谷、林冠和城市街谷中容易脱离地基传感器视线，压缩告警与交接窗口",
        "defensive_requirement": "以高低搭配、分布式低SWaP节点及被动RF/声学/EO-IR等多模态感知补盲；避免把任何单一传感器视为全域解"
      },
      {
        "constraint": "主动辐射暴露与固定节点脆弱性",
        "impact": "主动雷达可被侦察，且高价值节点可能成为优先压制或饱和对象",
        "defensive_requirement": "被动优先发现、按需主动确认、节点冗余、机动转移和诱饵/替代节点；公开证据不足以量化各手段风险降低幅度"
      },
      {
        "constraint": "探测—识别—处置链条并非天然闭环",
        "impact": "部分反制设备依赖外部探测、人工目视或上级引导；复杂地形会加剧目标交接失败和时延",
        "defensive_requirement": "建设共同态势图、本地自动关联、跨传感器目标接力和断链降级告警；接口应兼容FAAD-C2、TAK及JDN类架构"
      },
      {
        "constraint": "机动、可靠性和保障负担",
        "impact": "展开时间、道路条件、供电、备件、操作员负荷及平台可靠性会限制连续伴随覆盖；高端拦截器难以经济地应对低成本、大数量威胁",
        "defensive_requirement": "按威胁等级分层配置传感器与处置手段，优先降低前沿节点SWaP和维护负担，并将可负担性纳入传感器—C2—效应器全链设计"
      },
      {
        "constraint": "标称参数向场景效能转换存在不确定性",
        "impact": "256目标航迹容量、拦截器速度和系统部署状态不能直接推导复杂地形中的有效覆盖面积或抗饱和能力",
        "defensive_requirement": "后续评估应按地形类型、目标特征、通信状态和气象条件报告发现率、虚警率、识别时间、交接成功率及持续保障指标"
      }
    }
  }
}（Low-Altitude Passive Detection System – Army SBIR|STTR Program，B级，https://armysbir.army.mil/topics/low-altitude-passive-detection-system/，位置=text:332035637360ce54#p1，artifact=html:afc2980c951c7755,text:332035637360ce54）
- ev-weapon_equipment-web-e9c9cd579be6：陆军需求指出地球曲率、地形和障碍物限制地基雷达对低空小型无人机的探测距离，并提出低SWaP、模块化、被动多传感器的低空探测需求，目标覆盖0—6,000英尺AGL。（Low-Altitude Passive Detection System – Army SBIR|STTR Program，B级，https://armysbir.army.mil/topics/low-altitude-passive-detection-system/?utm_source=openai，位置=text:332035637360ce54#p1，artifact=html:9b2fdfc4967e64b2,text:332035637360ce54）
- ev-weapon_equipment-web-953c31096379：GAO称陆军于2022年将C-sUAS纳入防空反导现代化组合并形成6个正式采办项目；FS-LIDS、M-LIDS、Coyote、Ku波段雷达族及手持/徒步系统在FY2024进入中途采办路径的全速生产阶段。（GAO-25-107491, ARMY MODERNIZATION: Air and Missile Defense Efforts Would Benefit from Applying Leading Practices，B级，https://files.gao.gov/reports/GAO-25-107491/index.html?utm_source=openai，位置=text:8134b9d631487f9d#p7，artifact=html:31e0eb26fa5c1f74,text:8134b9d631487f9d）
- ev-weapon_equipment-web-64d60c0aa2e5：FoCUS采用政府拥有的系统—传感器族架构，把多种传感模态融合到单一车载平台，并面向未知地形降低误报、提高探测概率。（C5ISR Center supports border operations with C-UAS technology :: FORT BELVOIR，B级，https://home.army.mil/belvoir/about/Garrison/public-affairs/digital-belvoir-eagle/c5isr-center-supports-border-operations-c-uas-technology?utm_source=openai，位置=text:d805fa938c9b0182#p2，artifact=html:8a9e6d493a02afcc,text:d805fa938c9b0182）

## 限制与后续补证

- 门控链路内部基本一致：deterministic_status为approved，deterministic_checks全部为true，coverage_passed为true，stage-L1/L2/L3均gate_passed=true，整体置信度0.723高于阈值0.70。
- 覆盖性满足输入要求：required_tags全部出现且无缺失，provided_tags覆盖了capability_gap、equipment、operation、scenario等关键维度，研究路线traditional_gap与各阶段输出一致。
- 证据追溯基本可审计：各阶段均给出evidence_ids，evidence_index与source_claims可对应到公开来源；但部分证据表述是需求/征集文件或经验性期刊材料，不能直接等同于现役实测性能。
- 发布风险仍为有限：当前材料对复杂地形中的探测概率、误报率、识别时间、断链降级和持续保障缺乏公开量化基线，且存在少量格式/结构冗长的证据条目，适合边界化发布，不适合无条件对外定稿。
- 独立审计Agent意见：整体审计结果为通过但带边界限制：输入中的一致性、置信度阈值、覆盖、用户确认、轮次限制与证据材料化均已按自检标记为满足，且各阶段门控均为approved；不过结论主要依赖美国陆军/DoD公开材料，复杂地形下的实测探测距离、虚警率、端到端时延、可靠性改进幅度和全寿命保障成本仍缺少公开量化证据，因此存在明显的外推与发布边界风险。
