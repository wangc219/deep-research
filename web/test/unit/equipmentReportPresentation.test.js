import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import {
  capabilityPortraitModules,
  compactReportInlineLinks,
  normalizeReportDocument,
  normalizeReportMarkdownTables,
  reporterLifecycle,
  reportFilename
} from '../../src/views/equipment/reportPresentation.js'

describe('研究报告旧数据兼容与展示规范化', () => {
  it('展平迁移前事件，并允许 Reporter 在运行失败后继续写盘', () => {
    const lifecycle = reporterLifecycle(
      [
        {
          event_type: 'legacy_wrapper',
          payload: {
            event: {
              event_type: 'report_model_call_started',
              actor: 'reporter',
              payload: { current_step: '撰写第三层能力画像', elapsed_seconds: 8 }
            }
          }
        }
      ],
      'failed'
    )

    assert.equal(lifecycle.status, 'running')
    assert.equal(lifecycle.started, true)
    assert.equal(lifecycle.terminalFailure, false)
    assert.match(lifecycle.progressText, /撰写第三层能力画像/)
  })

  it('只把显式 Reporter 失败视为报告终态，并支持断点续跑后的新事件', () => {
    const failed = reporterLifecycle(
      [
        {
          event_type: 'report_model_failed',
          actor: 'reporter',
          details: { detail: '模型调用超时' }
        }
      ],
      'failed'
    )
    assert.equal(failed.status, 'failed')
    assert.equal(failed.terminalFailure, true)
    assert.equal(failed.failureDetail, '模型调用超时')

    const resumed = reporterLifecycle(
      [
        { event_type: 'report_model_failed', actor: 'reporter' },
        { event_type: 'report_model_queue_started', actor: 'reporter' }
      ],
      'failed'
    )
    assert.equal(resumed.status, 'running')
    assert.equal(resumed.terminalFailure, false)
    assert.equal(resumed.failureDetail, '')
  })

  it('把旧版单段能力画像恢复为五模块卡片', () => {
    const modules = capabilityPortraitModules({
      capability_image:
        '概述：面向低空突防。装备与技术实现：采用分布式光电组件。关键作战流程：侦察、释放、评估。形成能力与作战效果：压缩对手反应窗口。制胜逻辑机理：以低成本饱和改变交换比。'
    })

    assert.deepEqual(
      modules.map((item) => item.label),
      ['概述', '装备与技术实现', '关键作战流程', '形成能力与作战效果', '制胜逻辑机理']
    )
    assert.match(modules[4].text, /改变交换比/)
  })

  it('修复缺失和重复的 Markdown 表格分隔行', () => {
    const normalized = normalizeReportMarkdownTables(
      '| 装备 | 能力\n| A | B\n| --- | --- |\n| C | D'
    )

    assert.equal((normalized.match(/\| --- \| --- \|/g) || []).length, 1)
    assert.match(normalized, /\| 装备 \| 能力 \|\n\| --- \| --- \|\n\| A \| B \|/)
  })

  it('规范化 HTML 表格、补充装备表和待核验深研版本', () => {
    const normalized = normalizeReportDocument(
      '# 低空体系研究\n\n## 第三层：能力图像\n\n<table><tr><th>指标</th><th>结论</th></tr><tr><td>链路</td><td>可恢复</td></tr></table>',
      { report_template_mode: 'three_layer_nine_item' },
      [
        {
          name: '分布式诱饵节点',
          equipment_form: '一次性空中节点',
          confidence: 0.71,
          capability_portrait_modules: {
            overview: '在末端防区制造多源假目标。',
            technology_implementation: '采用低成本光电与射频载荷。',
            operational_process: '抵近、释放、协同、撤离。',
            capability_effects: '稀释拦截资源并增加识别时延。',
            winning_logic: '以低成本交换高价值防空弹药。'
          },
          is_deep_research: true,
          version_no: 2,
          verification_status: 'pending_verification',
          source: 'deep_thinking'
        }
      ]
    )

    assert.match(normalized, /\| 指标 \| 结论 \|/)
    assert.match(normalized, /\| 武器装备 \| 核心技术 \| 形成能力 \| 作战概念与主要效果 \|/)
    assert.match(normalized, /## 深研补充（待核验）/)
    assert.match(normalized, /### 分布式诱饵节点 · v2/)
  })

  it('保留以加粗短标题开头的 Markdown 段落边界', () => {
    const normalized = normalizeReportDocument(
      [
        '# 低空体系研究',
        '',
        '**能力域七：高价值精确拦截。**核心要求是可靠毁伤。',
        '',
        '**能力域八：快速部署与独立运行。**核心要求是快速形成战斗力。',
        '',
        '**抗干扰信号处理算法。**成熟度仍需验证。',
        '',
        '**核心公开来源索引**',
        '',
        '- **E01** [公开来源](https://example.com/source)'
      ].join('\n')
    )

    assert.match(
      normalized,
      /可靠毁伤。\n\n\*\*能力域八：快速部署与独立运行。\*\* 核心要求是快速形成战斗力。/
    )
    assert.match(
      normalized,
      /战斗力。\n\n\*\*抗干扰信号处理算法。\*\* 成熟度/
    )
    assert.match(normalized, /仍需验证。\n\n\*\*核心公开来源索引\*\*\n\n- \*\*E01\*\*/)
    assert.doesNotMatch(normalized, /可靠毁伤。\*\*能力域八/)
  })

  it('正式 S6 基线即使置信度受限也不会重复追加为深研补充', () => {
    const normalized = normalizeReportDocument(
      '# 低空体系研究\n\n## 第三层：能力图像\n\n正式报告正文。',
      { report_template_mode: 'three_layer_nine_item' },
      [
        {
          id: 'baseline-formal-s6-card',
          version_id: 'baseline-formal-s6-card',
          name: '正式 S6 装备',
          source: 'formal_s6',
          status: 'formal',
          confidence_limited: true,
          capability_portrait_modules: {
            overview: '概述',
            technology_implementation: '技术实现',
            operational_process: '作战流程',
            capability_effects: '能力效果',
            winning_logic: '制胜逻辑'
          }
        }
      ]
    )

    assert.doesNotMatch(normalized, /深研补充（待核验）/)
  })

  it('正文只保留前两个链接，来源索引和导出正文保持完整', () => {
    const source = [
      '[一](https://one.example) [二](https://two.example) [三](https://three.example)',
      '',
      '## 核心公开来源索引',
      '',
      '[四](https://four.example)'
    ].join('\n')
    const displayed = compactReportInlineLinks(source)

    assert.match(displayed, /\[一\]\(https:\/\/one\.example\)/)
    assert.match(displayed, /\[二\]\(https:\/\/two\.example\)/)
    assert.doesNotMatch(displayed, /\[三\]\(/)
    assert.match(displayed, /\[四\]\(https:\/\/four\.example\)/)
  })

  it('生成去除路径控制字符且带运行 ID 的 Markdown 文件名', () => {
    assert.equal(
      reportFilename({ topic: '低空 / 体系：研究?', run_id: 'run-1' }),
      '低空-体系：研究-run-1.md'
    )
  })
})
