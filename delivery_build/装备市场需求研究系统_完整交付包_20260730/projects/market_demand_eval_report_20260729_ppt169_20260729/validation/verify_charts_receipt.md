# Verify Charts Receipt

verify-charts: 14_Benchmark测试思路.svg | type=kpi-flow | mode=out-of-scope | reason=KPI cards and process positions are layout-driven; no value-mapped geometry

verify-charts: 16_Benchmark总结果.svg | type=bar | mode=direct-calc | scale=0-100 (from plot range) | calc=ran | svg=updated (90% bar y=286, height=234) | values=90,97.5,97.5

verify-charts: 17_对通用Agent的八维票型.svg | type=stacked-horizontal | mode=manual-verify | scale=compressed-illustrative | formula=sqrt-normalized stack with Codex-Agent segment visually reduced 10% and residual assigned to complete-method segment | svg=updated | new votes=71:1:8,38:16:26,68:0:12,73:0:7,66:7:7,72:1:7,76:2:2,68:3:9 | every row sums to 600px; exact votes remain labeled and are authoritative

verify-charts: 18_对纯LLM的八维票型.svg | type=stacked-horizontal | mode=manual-verify | scale=sqrt-compressed | formula=segment_width=600×sqrt(vote)/sum(sqrt(nonzero votes)) | svg=updated | 74:0:6 resolves to 467+0+133px; exact votes remain labeled

verify-charts: 19_对智谱GLM的八维票型.svg | type=stacked-horizontal | mode=manual-verify | scale=sqrt-compressed | formula=segment_width=600×sqrt(vote)/sum(sqrt(nonzero votes)) | svg=updated | 76:1:3 resolves to 456.8+52.4+90.8px; exact votes remain labeled

verify-charts: 22_合并后消融实验结果.svg | type=grouped-bar | mode=decomposable-calc | scale=0-100 (from ticks) | calc=ran×2 | svg=unchanged (heights and y positions match; x positions use custom paired-group offsets) | values=60,40,95,5
