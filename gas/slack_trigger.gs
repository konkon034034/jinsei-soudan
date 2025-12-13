/**
 * Slack → GitHub Actions トリガー
 *
 * 設定手順:
 * 1. Google Apps Script で新規プロジェクト作成
 * 2. このコードを貼り付け
 * 3. スクリプトプロパティに設定:
 *    - SLACK_SIGNING_SECRET: Slackアプリの署名シークレット
 *    - GITHUB_TOKEN: GitHub Personal Access Token (workflow権限必要)
 *    - SLACK_BOT_TOKEN: Slack Bot Token (xoxb-...)
 * 4. ウェブアプリとしてデプロイ（誰でもアクセス可能）
 * 5. デプロイURLをSlackアプリのInteractivity URLに設定
 */

const GITHUB_OWNER = 'konkon034034';
const GITHUB_REPO = 'jinsei-soudan';
const WORKFLOW_FILE = 'generate-video.yml';

// Slackからのリクエスト受信
function doPost(e) {
  const payload = e.parameter.payload ? JSON.parse(e.parameter.payload) : JSON.parse(e.postData.contents);

  // URL検証（Slack設定時）
  if (payload.type === 'url_verification') {
    return ContentService.createTextOutput(payload.challenge);
  }

  // ボタンクリック処理
  if (payload.type === 'block_actions' || payload.type === 'interactive_message') {
    return handleButtonClick(payload);
  }

  // スラッシュコマンド処理
  if (e.parameter.command) {
    return handleSlashCommand(e.parameter);
  }

  return ContentService.createTextOutput('OK');
}

// ボタンクリック処理
function handleButtonClick(payload) {
  const action = payload.actions[0];
  const actionId = action.action_id || action.value;
  const userId = payload.user.id;
  const channelId = payload.channel.id;

  // 即座に応答（3秒以内に返す必要あり）
  const response = {
    response_type: 'ephemeral',
    text: '⏳ 処理中...'
  };

  // 非同期で実際の処理を実行
  if (actionId.startsWith('generate_')) {
    const channelNum = actionId.replace('generate_', '');
    triggerGitHubActionAsync(channelNum, payload.response_url);
  }

  return ContentService.createTextOutput(JSON.stringify(response))
    .setMimeType(ContentService.MimeType.JSON);
}

// GitHub Actions をトリガー（非同期）
function triggerGitHubActionAsync(channelNum, responseUrl) {
  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');

  const url = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/${WORKFLOW_FILE}/dispatches`;

  const options = {
    method: 'post',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Accept': 'application/vnd.github.v3+json',
      'Content-Type': 'application/json'
    },
    payload: JSON.stringify({
      ref: 'main',
      inputs: {
        channel: channelNum
      }
    }),
    muteHttpExceptions: true
  };

  try {
    const response = UrlFetchApp.fetch(url, options);
    const code = response.getResponseCode();

    if (code === 204) {
      sendSlackMessage(responseUrl, `✅ ch${channelNum} の動画生成を開始しました！\nGitHub Actionsで処理中...`);
    } else {
      sendSlackMessage(responseUrl, `❌ エラー: ${response.getContentText()}`);
    }
  } catch (error) {
    sendSlackMessage(responseUrl, `❌ エラー: ${error.message}`);
  }
}

// Slackにメッセージ送信
function sendSlackMessage(responseUrl, text) {
  UrlFetchApp.fetch(responseUrl, {
    method: 'post',
    headers: { 'Content-Type': 'application/json' },
    payload: JSON.stringify({ text: text, response_type: 'ephemeral' })
  });
}

// スラッシュコマンド: /generate
function handleSlashCommand(params) {
  const text = params.text || '';
  const channelNum = text.trim() || '1';

  // チャンネル選択ボタンを表示
  const blocks = [
    {
      type: 'section',
      text: { type: 'mrkdwn', text: '🎬 *動画生成チャンネルを選択*' }
    },
    {
      type: 'actions',
      elements: [
        { type: 'button', text: { type: 'plain_text', text: 'ch23 昭和歌謡' }, action_id: 'generate_23', style: 'primary' },
        { type: 'button', text: { type: 'plain_text', text: 'ch24 朝ドラ' }, action_id: 'generate_24', style: 'primary' },
        { type: 'button', text: { type: 'plain_text', text: 'ch27 今年の話題' }, action_id: 'generate_27', style: 'primary' }
      ]
    }
  ];

  return ContentService.createTextOutput(JSON.stringify({
    response_type: 'ephemeral',
    blocks: blocks
  })).setMimeType(ContentService.MimeType.JSON);
}

// 手動テスト用
function testTrigger() {
  triggerGitHubActionAsync('23', 'https://hooks.slack.com/test');
}
