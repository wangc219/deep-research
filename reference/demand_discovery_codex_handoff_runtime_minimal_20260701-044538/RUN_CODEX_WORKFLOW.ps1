# Runtime launcher for the demand discovery Codex workflow.
# Run from this package root. It uses bundled .env and the collaborator's own Codex environment.
param(
  [string]$Topic = "低空无人机探测预警能力缺口",
  [string]$RunId = "collaborator-codex-check",
  [int]$MaxRounds = 1,
  [int]$MaxWorkerTasksPerRound = 1
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

codex --version
python scripts\demand_discovery_autonomous_research.py `
  --mode codex `
  --topic $Topic `
  --run-id $RunId `
  --max-rounds $MaxRounds `
  --codex-max-worker-tasks-per-round $MaxWorkerTasksPerRound `
  --codex-max-report-rewrites 1
