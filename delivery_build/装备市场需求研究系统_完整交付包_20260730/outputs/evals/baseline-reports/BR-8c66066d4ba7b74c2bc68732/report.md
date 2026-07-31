以下报告限于公开资料与体系级分析，不涉及制造参数、攻击规程或目标选择方法。

**概念界定**
“卫星拒止条件下多源自主导航精打武器”指：在 GPS/GNSS 被压制、欺骗、遮蔽或短时不可用时，仍能依靠惯性、抗干扰/军码卫导、景象/地形/磁异常/机会信号、协同导航与任务软件，维持可用定位、航迹控制和末段精度的精确打击弹药或制导套件。需求核心不是“替代 GPS 的单一传感器”，而是可裁剪的分层 PNT 架构。GAO 明确指出，DoD 的替代 PNT 分为相对 PNT 与绝对 PNT 两类，且未来通常需要多种技术组合，没有单一替代技术可满足全部需求。([gao.gov](https://www.gao.gov/products/gao-21-320sp))

****
① 典型作战场景

1. 强电磁对抗下的纵深精确打击  
对手在前沿与纵深部署 GNSS 干扰、欺骗和反卫星能力，使传统 GPS/INS 弹药出现航迹漂移、末段误差放大、协同时间基准失配。俄乌战场公开案例显示，俄罗斯电子战对 JDAM-ER、Excalibur、GMLRS/GLSDB 等 GPS 制导武器造成显著影响，暴露了“坐标打击依赖卫星导航”的脆弱性。([rusi.org](https://www.rusi.org/explore-our-research/publications/commentary/jamming-jdam-threat-us-munitions-russian-electronic-warfare)) ([defenseone.com](https://www.defenseone.com/threats/2024/04/another-us-precision-guided-weapon-falls-prey-russian-electronic-warfare-us-says/396141/))

2. 防空压制窗口内的快速多弹协同  
载机或发射平台无法长时间滞留、照射或通信中继，弹药需在释放后自主修正、协同分配、规避干扰导致的失准。AFRL Golden Horde 公开材料将网络化、协同、自主武器定义为武器系统体系，目标是让武器共享数据、协调行为、优化目标优先级和到达时间。([afresearchlab.com](https://afresearchlab.com/wp-content/uploads/2020/02/AFRL_Golden-Horde_FS_0922.pdf))

3. 海岛、沿岸、城市和山地复杂环境打击  
城市峡谷、山地遮蔽、海岸多径和强干扰会同时降低 GNSS、通信链路和光电识别稳定性。此类环境要求弹药能在不同地貌和天气下切换导航源，例如地形匹配适合起伏地形，视觉匹配适合特征丰富区域，惯性适合短时桥接，机会信号适合存在可用电磁源的城市/沿岸区域。

4. 低成本、大批量消耗战  
俄乌经验表明，电子战可用低成本方式削弱高价精确弹药。市场需求因此转向“可升级制导套件 + 模块化多源导航 + 数字验证环境”，而不是只追求昂贵单弹极致精度。GAO 也指出，替代 PNT 项目需要明确业务案例、指标和组合管理，否则难以快速形成规模能力。([gao.gov](https://www.gao.gov/products/gao-22-106010))

② 新战法/概念技术及制胜机理

1. 从“GPS 坐标制导”转向“韧性 PNT 制导”  
传统 JDAM 公开指标显示：GPS 可用时 CEP 可达 5 米以内；GPS 被拒止时，在良好交接条件和有限飞行时间内公开指标为 30 米以内。([af.mil](https://www.af.mil/About-Us/Fact-Sheets/Display/Article/104572/joint-direct-attack-munition-gbu-313238/)) 这说明惯性可支撑短时自主飞行，但不能长期保持高精度。制胜机理是用多源观测不断校正惯性漂移，使“拒止区内精度退化”可控。

2. 从“单弹精打”转向“协同精打”  
DARPA CODE 在 GPS 不可用、通信离线条件下演示多无人机协同执行任务，强调一个操作者监督多平台、平台间在受限通信下协同适应。([darpa.mil](https://www.darpa.mil/news/2019/code-success)) 对弹药而言，协同导航和协同任务规划可提升局部定位可信度、减少重复打击、提高突防和杀伤链闭合速度。

3. 从“传感器采购”转向“架构采购”  
Belfer Center 2026 年报告提出，替代 PNT 的视觉、地形、磁异常、惯性等组件已较成熟，短板在级联架构和失败模式文档化；其建议将架构级 alt-PNT 要求纳入 2027 前后的自主系统采购。([belfercenter.org](https://www.belfercenter.org/research-analysis/navigating-without-gps-cascading-alt-pnt-architecture-american-defense)) 制胜机理是：每个导航源都有失效条件，但通过置信度评估、降级运行和多源交叉验证，体系可靠性高于任一单源。

③ 装备能力特征清单

| 能力域 | 定性特征 | 定量指标方向 |
|---|---|---|
| 抗拒止 PNT | GNSS 被干扰/欺骗时仍能维持定位、速度、姿态与时间基准 | 拒止条件下 CEP、航迹漂移率、PNT 可用率、重捕获时间 |
| 多源融合 | INS、M-code/抗干扰 GNSS、视觉、地形、磁异常、机会信号、气压/高度等可插拔融合 | 传感器失效数量下的剩余精度；融合更新率；置信度告警时间 |
| 末段自主修正 | 对固定、可重定位或有限机动目标进行末段误差收敛 | 末段识别置信度、目标定位误差、毁伤概率提升方向 |
| 协同导航/协同任务 | 多弹或弹-机-无人平台共享状态和观测，支持到达时间、目标优先级、任务重分配 | 网络可用率、低带宽下协同成功率、时间同步误差 |
| 低 SWaP-C | 小型弹药可承载，成本适合规模列装 | 体积、功耗、单套制导成本、可量产率 |
| 开放架构 | 算法、传感器、仿真、试验数据可模块化升级 | 接口标准化比例、软件升级周期、替换传感器集成周期 |
| 安全与规则约束 | 半自主、可审计，受任务规划和交战规则限制 | 人工授权节点、任务日志完整性、失效安全模式覆盖率 |

****
④ 能力实现途径判断

| 能力特征 | 实现途径判断 |
|---|---|
| 抗干扰 GNSS/M-code | 沿用改进。M-code、抗干扰天线、接收机升级已有公开列装路径；重点是弹药小型化和成本下降。美国陆军 2025 年公开称已在地面、弹药、航空域推进 M-code 和 APNT。([army.mil](https://www.army.mil/article/285302/u_s_army_partnerships_bring_critical_assured_pnt_capabilities_to_american_soldiers)) |
| 高精度惯性 | 沿用改进 + 局部原理突破。MEMS/FOG/RLG 可沿用，微型原子惯性、低漂移自校准属于突破方向。DARPA Micro-PNT 目标包括低 SWaP 高性能惯性、单芯片 TIMU、自校准 MEMS 和原子惯性传感。([darpa.mil](https://www.darpa.mil/research/programs/micro-technology-for-positioning-navigation-and-timing)) |
| 景象/视觉导航 | 集成创新。DSMAC/视觉位置识别有历史基础，现代算力与 AI 提升匹配能力；短板在云、烟尘、夜间、季节变化和对抗伪装。 |
| 地形匹配/TRN | 集成创新。公开资料认为地形匹配对 GNSS 干扰免疫，可与 INS、视觉、AI 融合，但依赖高质量地形图，在平坦地形、海面、沙漠上性能下降。([uavnavigation.com](https://www.uavnavigation.com/company/blog/tercom-based-navigation-system-drones-new-era-gps-independent-flight)) |
| 机会信号 SoOP | 集成创新。蜂窝、广播、LEO 通信星等非导航信号可提供外部观测。ION GNSS+ 论文在 Edwards AFB GPS 干扰实验中显示，单个 LTE 机会信号的 radio SLAM 方案位置 RMSE 约 32 米，而 GPS-IMU 对照约 238 米。([people.engineering.osu.edu](https://people.engineering.osu.edu/sites/default/files/2022-10/Kassas_I_am_not_afraid_of_the_jammer_navigating_with_signals_of_opportunity_in_GPS_denied_environments.pdf)) |
| 磁异常/量子磁导航 | 原理突破 + 数据工程。抗远程电磁压制潜力高，但需要高分辨率磁图、平台磁补偿和小型化传感器。 |
| 协同自主 | 集成创新。Golden Horde 和 CODE 已公开验证概念；弹药侧重点是低带宽、短时、强约束、可审计协同。([darpa.mil](https://www.darpa.mil/research/programs/collaborative-operations-in-denied-environment)) ([afresearchlab.com](https://afresearchlab.com/wp-content/uploads/2020/02/AFRL_Golden-Horde_FS_0922.pdf)) |
| 数字孪生/HIL 验证 | 沿用改进 + 集成创新。需要把 PNT 失效、传感器退化、通信中断、目标误差纳入仿真和硬件在环。Golden Horde Colosseum 已将软件在环、硬件在环和替代 UAV 测试作为快速验证基础。([afresearchlab.com](https://afresearchlab.com/wp-content/uploads/2020/02/AFRL_Golden-Horde_FS_0922.pdf)) |

⑤ 核心技术清单

1. 弹载多源融合算法：紧耦合/深耦合 INS，因子图、粒子滤波、异常观测剔除、置信度管理。  
2. GNSS 抗干扰与可信接收：M-code/军码接收、CRPA/抗干扰天线、小型化射频前端、欺骗检测。  
3. 高动态低漂移 IMU：高过载环境下的陀螺/加速度计标定、温漂补偿、发射前快速对准。  
4. 景象匹配：EO/IR/SAR 图像匹配、季节/光照/烟尘鲁棒特征、合成参考图生成、末段目标确认。  
5. 地形匹配：雷达/激光高度观测、DEM 匹配、地形可观测性评估、地图库压缩。  
6. 磁异常导航：磁图构建、平台磁干扰补偿、磁/惯性联合定位。  
7. 机会信号导航：蜂窝、广播、LEO 通信星信号测量，未知发射源定位，抗欺骗一致性检验。  
8. 协同导航与时间同步：多弹相对测距/测向、低带宽状态共享、局部一致性地图。  
9. 任务级自主与安全约束：半自主规则库、失效降级策略、任务可解释日志。  
10. 数字试验体系：导航拒止环境建模、传感器退化模型、HIL/SIL、开放接口和可复现实验基线。

⑥ 耦合关系与短板风险

| 关键耦合 | 说明 | 卡脖子风险 |
|---|---|---|
| INS 与外部校正源 | INS 是所有拒止导航的底座，但误差随时间累积；外部源负责周期校正 | IMU 漂移过大或校正源不可用，会导致全程误差不可控 |
| 地图数据与景象/地形/磁导航 | 视觉、TRN、MagNav 都依赖高质量参考库 | 地图陈旧、分辨率不足或区域覆盖不全，会拖垮多源导航上限 |
| 融合算法与传感器置信度 | 多源不等于可靠，必须识别哪一路正在被欺骗或失效 | 置信度管理失败会把错误源融合进主解算，造成系统性偏航 |
| 抗干扰 GNSS 与低 SWaP-C | M-code/抗干扰能力有用，但弹药空间、功耗、成本受限 | 只做高端方案会难以规模列装，只做低成本方案又可能抗扰不足 |
| 协同自主与通信拒止 | 协同提升效能，但通信本身会被干扰、截获或中断 | 过度依赖联网会把“多弹协同”变成新的单点失效 |
| 末段识别与法律/规则约束 | 末段自主修正必须有边界和审计 | 规则约束不清会阻碍试验、列装和盟友互操作 |

最关键短板是“地图/环境参考数据 + 融合置信度管理”。高性能 IMU 能延缓漂移，但若没有可靠外部观测与可信融合，拒止环境下仍会退化为短时惯性飞行。

****
⑦ 能力图像

能力域构成：

1. 基础层：高动态 INS、时间保持、发射平台交接。  
2. 抗扰层：M-code/抗干扰 GNSS、欺骗检测、抗干扰天线。  
3. 外部校正层：视觉匹配、地形匹配、磁异常、机会信号、必要时天文/气压辅助。  
4. 融合决策层：多源置信度、故障隔离、降级模式、任务安全边界。  
5. 协同层：弹-弹、弹-机、弹-无人平台低带宽共享。  
6. 试验升级层：数字孪生、HIL/SIL、开放接口、快速软件迭代。

指标画像：

| 谱系位置 | 代表形态 | GNSS 拒止能力 |
|---|---|---|
| 传统 INS/GPS 精确弹药 | JDAM、PGK 类 | 短时可用，拒止后精度显著退化；公开 JDAM 指标显示 GPS 可用与拒止下 CEP 差异明显。([af.mil](https://www.af.mil/About-Us/Fact-Sheets/Display/Article/104572/joint-direct-attack-munition-gbu-313238/)) |
| 双模/多模精确弹药 | GPS/INS + 激光/红外/雷达末制导 | 末段精度更强，但受天气、照射、目标特征和成本制约 |
| 多源自主导航弹药 | INS + 抗扰 GNSS + VPR/TRN/SoOP/MagNav | 重点解决中段/末段连续校正和欺骗识别 |
| 协同自主精打武器 | 多源导航 + 网络化协同 + 半自主任务软件 | 面向强拒止、高动态、批量突防和多目标任务 |

⑧ 效能贡献

1. 对发现-定位-跟踪-瞄准-打击-评估链条的贡献  
导航韧性直接影响“瞄准-打击”段：目标坐标再准确，弹药自身 PNT 不可信也会错失。多源自主导航可降低对持续外部定位、通信和照射的依赖，使平台释放后更快脱离威胁区。

2. 对突防和饱和打击的贡献  
协同弹药可在低通信条件下共享局部态势和任务状态，减少重复攻击，提高多弹到达时间一致性和目标分配效率。Golden Horde 公开目标即是通过网络化协同自主武器提升生存力和杀伤力。([afresearchlab.com](https://afresearchlab.com/wp-content/uploads/2020/02/AFRL_Golden-Horde_FS_0922.pdf))

3. 对成本交换比的贡献  
敌方 GNSS 干扰器、欺骗器成本较低，迫使高价精确弹药失效会形成不利交换比。可量化方向包括：单位成功毁伤成本、拒止条件下任务成功率、单目标所需弹药数量、重攻次数、载机暴露时间。

4. 对体系韧性的贡献  
GAO 提示应按任务澄清 PNT 性能需求，而非默认所有任务都需要 GPS 级精度。([gao.gov](https://www.gao.gov/products/gao-21-320sp)) 因此，多源导航的价值不只是“更准”，还包括按任务提供足够可信、足够便宜、可规模升级的 PNT 能力。

⑨ 发展优先级与近期抓手

优先级建议：

1. 第一优先级：多源融合架构与失效管理  
先定义开放接口、传感器置信度、失效降级和任务日志标准。没有架构，单点传感器升级难以形成体系能力。

2. 第二优先级：弹载低 SWaP-C 惯性 + 抗扰 GNSS  
这是近期最可落地路径。陆军公开实践显示，M-code、APNT、抗干扰天线、PGK/航空 EGI 升级已经进入规模化阶段。([army.mil](https://www.army.mil/article/285302/u_s_army_partnerships_bring_critical_assured_pnt_capabilities_to_american_soldiers))

3. 第三优先级：视觉/地形匹配工程化  
适合先在巡飞弹、滑翔弹、无人靶机和训练弹上演示。重点不是单一算法精度，而是跨天气、跨季节、跨地貌的可用边界。

4. 第四优先级：机会信号与磁异常导航  
作为中期增强能力，适合在城市、沿岸、岛链等外部信号或地球物理特征丰富区域验证。

5. 第五优先级：协同自主精打  
在单弹导航韧性达标后，再扩展到多弹协同，否则网络化会放大基础导航误差。

近期演示验证项目构想：

1. “拒止 PNT 制导套件”地面与飞行演示  
目标：在可控 GNSS 干扰/欺骗环境中比较 GPS/INS、M-code/INS、多源融合三种模式的轨迹误差、重捕获时间和失效告警准确率。

2. “INS + 视觉/地形匹配”滑翔弹级验证  
目标：验证在云下、山地、城市边缘、低纹理地形中的可观测性边界，输出任务区域适配规则。

3. “机会信号辅助导航”城市/沿岸验证  
目标：借鉴公开 radio SLAM 思路，评估蜂窝、广播、LEO 通信信号在 GNSS 拒止下对 INS 漂移的校正贡献。([people.engineering.osu.edu](https://people.engineering.osu.edu/sites/default/files/2022-10/Kassas_I_am_not_afraid_of_the_jammer_navigating_with_signals_of_opportunity_in_GPS_denied_environments.pdf))

4. “多弹协同 PNT”半实物仿真  
目标：基于 Golden Horde 类数字环境，验证低带宽、短时断链、多弹状态共享对命中概率、重复打击率和到达时间控制的贡献。([afresearchlab.com](https://afresearchlab.com/wp-content/uploads/2020/02/AFRL_Golden-Horde_FS_0922.pdf))

5. “开放式 alt-PNT 架构基线”  
目标：形成传感器接口、地图接口、融合置信度、失效模式、试验数据格式和升级流程，支撑后续供应商并行竞标与快速替换。

**结论**
该需求已由战场电子战、GPS 依赖型精确弹药失效风险和自主协同武器发展共同牵引。近期最现实路线是“抗扰 GNSS/M-code + 高动态 INS + 开放融合架构”，中期叠加视觉、地形、机会信号和磁异常校正，远期形成协同自主精打体系。决定成败的不是某个单传感器指标，而是地图数据、融合可信度、低 SWaP-C 工程化和可规模验证体系。