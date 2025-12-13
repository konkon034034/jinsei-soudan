/**
 * Slack → GitHub Actions トリガー + 画像選択状態管理
 *
 * GAS URL: https://script.google.com/macros/s/AKfycbwvKV-ZXP9ecJAIwD-qdi6K7XF8HtZvK4X8JEEdNqqTijkAX2gMNWeYN3j9CuqUX8XI/exec
 */

const GITHUB_OWNER = 'konkon034034';
const GITHUB_REPO = 'jinsei-soudan';
// GITHUB_TOKEN は Script Properties に設定してください
// GASエディタ → プロジェクトの設定 → スクリプトプロパティ → GITHUB_TOKEN を追加

function getGitHubToken() {
  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  if (!token) {
    throw new Error('GITHUB_TOKEN not set in Script Properties');
  }
  return token;
}

// ========== 画像選択状態管理 ==========

function getSelections(channelNum) {
  const props = PropertiesService.getScriptProperties();
  const data = props.getProperty('sel_' + channelNum);
  return data ? JSON.parse(data) : {};
}

function setSelection(channelNum, imgNum, selected) {
  const props = PropertiesService.getScriptProperties();
  const sels = getSelections(channelNum);
  sels[imgNum] = selected;
  props.setProperty('sel_' + channelNum, JSON.stringify(sels));
  return sels;
}

function clearSelections(channelNum) {
  PropertiesService.getScriptProperties().deleteProperty('sel_' + channelNum);
}

function countSelected(channelNum, total) {
  const sels = getSelections(channelNum);
  let count = 0;
  for (let i = 1; i <= total; i++) {
    if (sels[i] !== false) count++;
  }
  return count;
}

// ========== メイン処理 ==========

function doPost(e) {
  try {
    // Slackからのpayloadを解析
    let payload;
    if (e.parameter && e.parameter.payload) {
      payload = JSON.parse(e.parameter.payload);
    } else if (e.postData && e.postData.contents) {
      payload = JSON.parse(e.postData.contents);
    } else {
      return respond('Error: No payload');
    }

    // URL検証（Slack設定時）
    if (payload.type === 'url_verification') {
      return ContentService.createTextOutput(payload.challenge);
    }

    // ボタンクリック処理
    if (payload.type === 'block_actions') {
      return handleAction(payload);
    }

    return respond('OK');
  } catch (err) {
    console.error('doPost error:', err);
    return respond('Error: ' + err.message);
  }
}

function handleAction(payload) {
  const action = payload.actions[0];
  const actionId = action.action_id;
  const responseUrl = payload.response_url;

  console.log('Action:', actionId);

  // 画像選択: use_img_{ch}_{num} または skip_img_{ch}_{num}
  if (actionId.startsWith('use_img_') || actionId.startsWith('skip_img_')) {
    const parts = actionId.split('_');
    const ch = parts[2];
    const num = parseInt(parts[3]);
    const selected = actionId.startsWith('use_img_');

    setSelection(ch, num, selected);
    const count = countSelected(ch, 30);

    const msg = selected
      ? `✅ 画像${num}を選択（${count}/30枚）`
      : `❌ 画像${num}を除外（${count}/30枚）`;

    return respond(msg);
  }

  // 動画生成: generate_{ch}
  if (actionId.startsWith('generate_')) {
    const ch = actionId.replace('generate_', '');
    const count = countSelected(ch, 30);

    if (count === 0) {
      return respond('⚠️ 画像を1枚以上選択してください');
    }

    // GitHub Actions トリガー（非同期）
    triggerWorkflow(ch, count, responseUrl);
    clearSelections(ch);

    return respond(`🎬 ch${ch}の動画生成を開始！（${count}枚選択）`);
  }

  // 再生成: regenerate_{ch}
  if (actionId.startsWith('regenerate_')) {
    const ch = actionId.replace('regenerate_', '');
    clearSelections(ch);
    triggerPrepare(ch, responseUrl);
    return respond('🔄 再生成中...');
  }

  // スキップ: skip_{ch}
  if (actionId.startsWith('skip_')) {
    const ch = actionId.replace('skip_', '');
    clearSelections(ch);
    return respond('⏭️ スキップしました');
  }

  return respond('OK');
}

function respond(text) {
  return ContentService.createTextOutput(JSON.stringify({
    response_type: 'ephemeral',
    text: text
  })).setMimeType(ContentService.MimeType.JSON);
}

// ========== GitHub Actions ==========

function triggerWorkflow(channelNum, selectedCount, responseUrl) {
  const url = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/generate-video.yml/dispatches`;

  try {
    const resp = UrlFetchApp.fetch(url, {
      method: 'post',
      headers: {
        'Authorization': 'Bearer ' + getGitHubToken(),
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json'
      },
      payload: JSON.stringify({
        ref: 'main',
        inputs: { channel: channelNum }
      }),
      muteHttpExceptions: true
    });

    const code = resp.getResponseCode();
    if (code === 204) {
      sendToSlack(responseUrl, `✅ ch${channelNum}の動画生成を開始しました！\n選択画像: ${selectedCount}枚`);
    } else {
      sendToSlack(responseUrl, `❌ GitHub エラー(${code}): ${resp.getContentText()}`);
    }
  } catch (e) {
    sendToSlack(responseUrl, '❌ エラー: ' + e.message);
  }
}

function triggerPrepare(channelNum, responseUrl) {
  const chIndex = { '27': '1', '24': '2', '23': '3' }[channelNum] || '0';
  const url = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/syouwa-morning-prepare.yml/dispatches`;

  try {
    const resp = UrlFetchApp.fetch(url, {
      method: 'post',
      headers: {
        'Authorization': 'Bearer ' + getGitHubToken(),
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json'
      },
      payload: JSON.stringify({
        ref: 'main',
        inputs: { channel_index: chIndex }
      }),
      muteHttpExceptions: true
    });

    const code = resp.getResponseCode();
    if (code === 204) {
      sendToSlack(responseUrl, `🔄 ch${channelNum}の再生成を開始しました！`);
    } else {
      sendToSlack(responseUrl, `❌ GitHub エラー(${code})`);
    }
  } catch (e) {
    sendToSlack(responseUrl, '❌ エラー: ' + e.message);
  }
}

function sendToSlack(url, text) {
  if (!url) return;
  UrlFetchApp.fetch(url, {
    method: 'post',
    headers: { 'Content-Type': 'application/json' },
    payload: JSON.stringify({ text: text, response_type: 'ephemeral' })
  });
}

// ========== テスト ==========

function testSelection() {
  setSelection('27', 1, true);
  setSelection('27', 2, false);
  console.log('Count:', countSelected('27', 30));
  clearSelections('27');
}

function doGet(e) {
  return ContentService.createTextOutput('GAS is running. Use POST for Slack interactions.');
}
