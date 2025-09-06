# S3 GetObject → Slack 通知（CDK）セットアップ手順

前提
	•	AWS CLI v2 / Node.js 18+ / AWS CDK v2（npm i -g aws-cdk）
	•	Slack Incoming Webhook（通知先チャンネル）
	•	監視したい S3 バケットが存在
	•	権限：CloudTrail / EventBridge / Lambda / Secrets Manager / Logs を作成できる

このスタックは 専用の CloudTrail（Data Events） を作るので、既存のTrailを壊しません。

⸻

クイックスタート（コマンドだけ）

zsh の人は同じ行にコメントを書かないでください（unset: #: invalid parameter name になる）。

# 1) 環境変数（必要に応じて書き換え）
export CDK_DEFAULT_REGION=ap-northeast-1
export APP_NAME='GetObjectMonitor-A'                  # Lambda名＝EventBridgeルール名
export BUCKET_NAMES='your-bucket-1 your-bucket-2'     # 監視バケット（スペース/カンマ区切りOK）
export SLACK_SECRET_NAME='slack/webhook-getobject'    # Secrets Manager の名前

# 2) Slack Webhook を Secrets Manager へ（初回のみ）
aws secretsmanager create-secret \
  --name "$SLACK_SECRET_NAME" \
  --secret-string '{"url":"https://hooks.slack.com/services/XXX/YYY/ZZZ"}' \
  --region "$CDK_DEFAULT_REGION"

# 3) CDK ブートストラップ（アカウント/リージョンで1回）
cdk bootstrap

# 4) デプロイ
cdk deploy --require-approval never

動作確認

# リソース確認
aws lambda get-function --function-name "$APP_NAME" --region "$CDK_DEFAULT_REGION" --query 'Configuration.FunctionArn' --output text
aws events describe-rule --name "$APP_NAME" --region "$CDK_DEFAULT_REGION" --query 'State' --output text
aws cloudtrail describe-trails --region "$CDK_DEFAULT_REGION" --query "trailList[?Name=='${APP_NAME}-Trail'].Name" --output text

# Lambda 単体テスト（Slack疎通）
cat > /tmp/evt.json <<'JSON'
{
  "version": "0",
  "detail-type": "AWS API Call via CloudTrail",
  "source": "aws.s3",
  "account": "000000000000",
  "time": "2025-01-01T00:00:00Z",
  "region": "ap-northeast-1",
  "detail": {
    "eventSource": "s3.amazonaws.com",
    "eventName": "GetObject",
    "sourceIPAddress": "1.2.3.4",
    "userAgent": "aws-cli/2.15.0 Python/3.11 botocore/2.14.0",
    "requestParameters": { "bucketName": "your-bucket-1", "key": "dummy.txt" },
    "userIdentity": { "type": "IAMUser", "accessKeyId": "ASIAXXXXX", "arn": "arn:aws:iam::123456789012:user/test" }
  }
}
JSON

aws lambda invoke --function-name "$APP_NAME" \
  --payload fileb:///tmp/evt.json \
  --region "$CDK_DEFAULT_REGION" /tmp/out.json >/dev/null

# 本番経路テスト（実オブジェクトでGetObject）
KEY=$(aws s3api list-objects-v2 --bucket your-bucket-1 --max-items 1 \
  --query 'Contents[0].Key' --output text --region "$CDK_DEFAULT_REGION")
aws s3api get-object --bucket your-bucket-1 --key "$KEY" /dev/null \
  --region "$CDK_DEFAULT_REGION" >/dev/null 2>&1 || true


⸻

カスタマイズ（Lambda 環境変数で切替）

デプロイ済みでも update-function-configuration で変更できます。

aws lambda update-function-configuration \
  --function-name "$APP_NAME" \
  --region "$CDK_DEFAULT_REGION" \
  --environment "Variables={
    SLACK_SECRET_NAME=$SLACK_SECRET_NAME,
    REGION=$CDK_DEFAULT_REGION,
    MASK_IP=true,
    MASK_ACCESS_KEY=true,
    MASK_ACCOUNT_ID=true,
    EMOJI_HUMAN=:inbox_tray:,      # 人間っぽいアクセスのヘッダー絵文字
    EMOJI_ROBOT=:robot_face:,      # 自動/タスクっぽいアクセス
    TREAT_CLI_AS_HUMAN=false       # aws-cli/botocore を人扱いにしたい場合は true
  }"

	•	MASK_IP：IPv4は /24、IPv6は /64 に丸めて表示
	•	MASK_ACCESS_KEY：アクセスキー末尾4桁のみ
	•	MASK_ACCOUNT_ID：アカウントIDを 12***3456 形式に
	•	人/ロボ判定は UA・ID種別から推定し、ヘッダーに👤/🤖（Slack絵文字）を出し分け

⸻

トラブルシュート（よくある）
	•	通知が来ない（Lambda単体もNG）
→ Secret名/中身（URL）を再チェック：
aws secretsmanager get-secret-value --secret-id "$SLACK_SECRET_NAME" --region "$CDK_DEFAULT_REGION"
	•	Lambda単体はOKだが本番経路で来ない
→ aws cloudtrail get-event-selectors --trail-name ${APP_NAME}-Trail に対象バケットの arn:aws:s3:::bucket/ が入っているか
→ aws events describe-rule --name "$APP_NAME" --query State が ENABLED か
→ 直近ログ：aws logs tail /aws/lambda/$APP_NAME --region "$CDK_DEFAULT_REGION" --since 10m
	•	BUCKET_NAMES 未設定エラー
→ export BUCKET_NAMES='...' を忘れているか、値が空。

⸻

片付け

cdk destroy
aws secretsmanager delete-secret --secret-id "$SLACK_SECRET_NAME" \
  --region "$CDK_DEFAULT_REGION" --force-delete-without-recovery

CloudTrailログ用のS3バケットが残る場合は、中身を空にしてから再実行。

⸻

アーキ図（Mermaid）

flowchart LR
  subgraph S3["S3 Buckets (BUCKET_NAMES)"]
  end
  S3 -- "GetObject (Data Events)" --> CT["CloudTrail\n(APP_NAME-Trail)"]
  CT --> EB["EventBridge Rule\n(APP_NAME)"]
  EB --> L["Lambda\n(APP_NAME)"]
  Secrets["Secrets Manager\n(SLACK_SECRET_NAME)\nWebhook URL 保管"] --> L
  L --> Slack["Slack Incoming Webhook\n(チャンネル通知)"]

リポジトリ構成（GitHub はこのままが👍）

s3-getobject-monitor-cdk/
├─ bin/                         # CDKエントリ（envを読む）
│   └─ s3-getobject-monitor-cdk.ts
├─ lib/                         # スタック定義（Trail/Rule/Lambda）
│   └─ s3-getobject-monitor-cdk-stack.ts
├─ lambda/                      # Slack通知ロジック（Webhook/マスク/絵文字）
│   └─ notify_app.py
├─ cdk.json
├─ package.json
├─ tsconfig.json
├─ .gitignore                   # .env, cdk.out など除外
└─ README.md

注意（コスト/情報露出）
	•	S3 Data Events はイベント量課金。対象バケットは必要最小限に。
	•	通知本文には「Who/UA/AccessKey末尾」等が含まれます。公開範囲に応じてマスクを設定してください。
