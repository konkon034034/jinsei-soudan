/**
 * Slack → GitHub Actions トリガー + 画像選択状態管理
 *
 * 設定手順:
 * 1. Google Apps Script で新規プロジェクト作成
 * 2. このコードを貼り付け
 * 3. スクリプトプロパティに設定:
 *    - GITHUB_TOKEN: GitHub Personal Access Token (workflow権限必要)
 *    - SLACK_BOT_TOKEN: Slack Bot Token (xoxb-...)
 * 4. ウェブアプリとしてデプロイ（誰でもアクセス可能）
 * 5. デプロイURLをSlackアプリのInteractivity URLに設定
 */

const GITHUB_OWNER = 'konkon034034';
const GITHUB_REPO = 'jinsei-soudan';
const WORKFLOW_FILE = 'generate-video.yml';

// 画像選択状態を保存（ScriptPropertiesを使用）
function getImageSelections(channelNum) {
  const props = PropertiesService.getScriptProperties();
  const key = `selections_${channelNum}`;
  const data = props.getProperty(key);
  return data ? JSON.parse(data) : {};
}

function setImageSelection(channelNum, imgNum, selected) {
  const props = PropertiesService.getScriptProperties();
  const key = `selections_${channelNum}`;
  const selections = getImageSelections(channelNum);
  selections[imgNum] = selected;
  props.setProperty(key, JSON.stringify(selections));
  return selections;
}

function clearImageSelections(channelNum) {
  const props = PropertiesService.getScriptProperties();
  props.deleteProperty(`selections_${channelNum}`);
}

function countSelectedImages(channelNum, totalImages) {
  const selections = getImageSelections(channelNum);
  let selected = 0;
  for (let i = 1; i <= totalImages; i++) {
    // デフォルトは選択状態（true）
    if (selections[i] !== false) {
      selected++;
    }
  }
  return selected;
}

// Slackからのリクエスト受信
function doPost(e) {
  try {
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
  } catch (error) {
    console.error('Error in doPost:', error);
    return ContentService.createTextOutput('Error: ' + error.message);
  }
}

// ボタンクリック処理
function handleButtonClick(payload) {
  const action = payload.actions[0];
  const actionId = action.action_id || action.value;
  const responseUrl = payload.response_url;
  const messageTs = payload.message ? payload.message.ts : null;
  const channelId = payload.channel.id;

  // 画像選択ボタン: use_img_{channel}_{imgNum} または skip_img_{channel}_{imgNum}
  if (actionId.startsWith('use_img_') || actionId.startsWith('skip_img_')) {
    const parts = actionId.split('_');
    const channelNum = parts[2];
    const imgNum = parseInt(parts[3]);
    const selected = actionId.startsWith('use_img_');

    // 選択状態を保存
    const selections = setImageSelection(channelNum, imgNum, selected);

    // カウントを計算（30枚想定）
    const totalImages = 30;
    const selectedCount = countSelectedImages(channelNum, totalImages);

    // 即座に応答
    return ContentService.createTextOutput(JSON.stringify({
      response_type: 'ephemeral',
      replace_original: false,
      text: selected
        ? `✅ 画像${imgNum}を選択しました（選択中: ${selectedCount}/${totalImages}枚）`
        : `❌ 画像${imgNum}を除外しました（選択中: ${selectedCount}/${totalImages}枚）`
    })).setMimeType(ContentService.MimeType.JSON);
  }

  // 動画生成ボタン: generate_{channel}
  if (actionId.startsWith('generate_')) {
    const channelNum = actionId.replace('generate_', '');
    const valueData = action.value ? JSON.parse(action.value) : {};

    // 選択された画像を取得
    const totalImages = valueData.total_images || 30;
    const selectedCount = countSelectedImages(channelNum, totalImages);

    if (selectedCount === 0) {
      return ContentService.createTextOutput(JSON.stringify({
        response_type: 'ephemeral',
        text: '⚠️ 画像が1枚も選択されていません。画像を選択してください。'
      })).setMimeType(ContentService.MimeType.JSON);
    }

    // GitHub Actions トリガー
    triggerGitHubActionAsync(channelNum, responseUrl, selectedCount);

    // 選択状態をクリア
    clearImageSelections(channelNum);

    return ContentService.createTextOutput(JSON.stringify({
      response_type: 'ephemeral',
      text: `🎬 ch${channelNum}の動画生成を開始します！\n選択画像: ${selectedCount}枚`
    })).setMimeType(ContentService.MimeType.JSON);
  }

  // 再生成ボタン: regenerate_{channel}
  if (actionId.startsWith('regenerate_')) {
    const channelNum = actionId.replace('regenerate_', '');
    clearImageSelections(channelNum);

    // 再生成ワークフローをトリガー
    triggerPrepareWorkflow(channelNum, responseUrl);

    return ContentService.createTextOutput(JSON.stringify({
      response_type: 'ephemeral',
      text: '🔄 別のテーマで再生成します...'
    })).setMimeType(ContentService.MimeType.JSON);
  }

  // スキップボタン: skip_{channel}
  if (actionId.startsWith('skip_')) {
    const channelNum = actionId.replace('skip_', '');
    clearImageSelections(channelNum);

    return ContentService.createTextOutput(JSON.stringify({
      response_type: 'ephemeral',
      text: '⏭️ スキップしました'
    })).setMimeType(ContentService.MimeType.JSON);
  }

  return ContentService.createTextOutput(JSON.stringify({
    response_type: 'ephemeral',
    text: '⏳ 処理中...'
  })).setMimeType(ContentService.MimeType.JSON);
}

// GitHub Actions: 動画生成ワークフローをトリガー
function triggerGitHubActionAsync(channelNum, responseUrl, selectedCount) {
  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  if (!token) {
    sendSlackMessage(responseUrl, '❌ GITHUB_TOKENが設定されていません');
    return;
  }

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
      sendSlackMessage(responseUrl, `✅ ch${channelNum}の動画生成を開始しました！\n選択画像: ${selectedCount}枚\nGitHub Actionsで処理中...`);
    } else {
      sendSlackMessage(responseUrl, `❌ GitHub Actions エラー: ${response.getContentText()}`);
    }
  } catch (error) {
    sendSlackMessage(responseUrl, `❌ エラー: ${error.message}`);
  }
}

// GitHub Actions: 準備ワークフローをトリガー（再生成用）
function triggerPrepareWorkflow(channelNum, responseUrl) {
  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  if (!token) {
    sendSlackMessage(responseUrl, '❌ GITHUB_TOKENが設定されていません');
    return;
  }

  // チャンネル番号をインデックスに変換
  const channelIndex = { '27': '1', '24': '2', '23': '3' }[channelNum] || '0';

  const url = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/syouwa-morning-prepare.yml/dispatches`;

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
        channel_index: channelIndex
      }
    }),
    muteHttpExceptions: true
  };

  try {
    const response = UrlFetchApp.fetch(url, options);
    const code = response.getResponseCode();

    if (code === 204) {
      sendSlackMessage(responseUrl, `🔄 ch${channelNum}の再生成を開始しました！\n新しいテーマで台本と画像を準備中...`);
    } else {
      sendSlackMessage(responseUrl, `❌ GitHub Actions エラー: ${response.getContentText()}`);
    }
  } catch (error) {
    sendSlackMessage(responseUrl, `❌ エラー: ${error.message}`);
  }
}

// Slackにメッセージ送信
function sendSlackMessage(responseUrl, text) {
  if (!responseUrl) return;

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
        { type: 'button', text: { type: 'plain_text', text: 'ch27 銀幕スター' }, action_id: 'generate_27', style: 'primary' },
        { type: 'button', text: { type: 'plain_text', text: 'ch24 アイドル伝説' }, action_id: 'generate_24', style: 'primary' },
        { type: 'button', text: { type: 'plain_text', text: 'ch23 朝ドラヒロイン' }, action_id: 'generate_23', style: 'primary' }
      ]
    }
  ];

  return ContentService.createTextOutput(JSON.stringify({
    response_type: 'ephemeral',
    blocks: blocks
  })).setMimeType(ContentService.MimeType.JSON);
}

// 手動テスト用
function testImageSelection() {
  setImageSelection('27', 1, true);
  setImageSelection('27', 2, false);
  setImageSelection('27', 3, true);

  const count = countSelectedImages('27', 30);
  console.log('Selected count:', count); // 28 (30 - 2 = 28, since img 2 is false)

  clearImageSelections('27');
}
