# Chart Verification Receipt

verify-charts: 15_benchmark_asset.svg | type=donut | mode=direct-calc | scale=N/A | calc=ran | svg=unchanged (8 equal values produce 45-degree sectors; SVG rotations are -90,-45,0,45,90,135,180,225; 104px painted arc plus intentional 17px gap on 967.6px centerline circumference)

verify-charts: 16_pairwise_benchmark.svg | type=stacked-bar | mode=decomposable-calc | scale=0-72 (fixed total votes per dimension) | calc=ran×3 | svg=unchanged (all three series widths match 600/72 pixels per vote; segment x positions equal cumulative preceding widths; row placement is layout-driven)
