# jinsei-soudan Makefile

# === GAS デプロイ ===
gas:
	@echo "GASをデプロイ中..."
	@cd gas && clasp push
	@echo "完了"

deploy: gas

# === ワークフロー実行 ===
朝準備:
	@echo "朝準備ワークフローを実行中..."
	@gh workflow run syouwa-morning-prepare.yml
	@sleep 2
	@gh run list --workflow=syouwa-morning-prepare.yml --limit=1

動画生成:
	@echo "動画生成ワークフローを実行中..."
	@gh workflow run generate-video.yml
	@sleep 2
	@gh run list --workflow=generate-video.yml --limit=1

# チャンネル指定版
動画生成-%:
	@echo "ch$* の動画生成ワークフローを実行中..."
	@gh workflow run generate-video.yml -f channel=$*
	@sleep 2
	@gh run list --workflow=generate-video.yml --limit=1

# === Git + GAS 一括 ===
push: gas
	@git add -A
	@git status --short
	@read -p "コミットメッセージ: " msg && git commit -m "$$msg" || true
	@git push

# === ステータス確認 ===
status:
	@echo "=== 最近のワークフロー実行 ==="
	@gh run list --limit=5

# === ヘルプ ===
help:
	@echo "使い方:"
	@echo "  make gas        - GASをデプロイ"
	@echo "  make 朝準備      - 朝準備ワークフロー実行"
	@echo "  make 動画生成    - 動画生成ワークフロー実行"
	@echo "  make 動画生成-27 - ch27の動画生成"
	@echo "  make push       - GASデプロイ + git push"
	@echo "  make status     - ワークフロー実行状況"

.PHONY: gas deploy 朝準備 動画生成 push status help
