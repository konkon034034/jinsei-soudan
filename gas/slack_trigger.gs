/**
 * Slack → GitHub Actions トリガー + 画像/台本行 選択状態管理
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

// ========== 選択状態管理（画像・台本行共通） ==========

function getSelections(key) {
  const props = PropertiesService.getScriptProperties();
  const data = props.getProperty(key);
  return data ? JSON.parse(data) : {};
}

function setSelection(key, num, selected) {
  const props = PropertiesService.getScriptProperties();
  const sels = getSelections(key);
  sels[num] = selected;
  props.setProperty(key, JSON.stringify(sels));
  return sels;
}

function clearSelections(key) {
  PropertiesService.getScriptProperties().deleteProperty(key);
}

function countSelected(key, total) {
  const sels = getSelections(key);
  let count = 0;
  for (let i = 1; i <= total; i++) {
    if (sels[i] !== false) count++;
  }
  return count;
}

// チャンネルごとの総数を保存
function setTotals(ch, totalImages, totalLines) {
  const props = PropertiesService.getScriptProperties();
  props.setProperty('total_img_' + ch, String(totalImages));
  props.setProperty('total_line_' + ch, String(totalLines));
}

function getTotals(ch) {
  const props = PropertiesService.getScriptProperties();
  return {
    images: parseInt(props.getProperty('total_img_' + ch) || '10'),
    lines: parseInt(props.getProperty('total_line_' + ch) || '20')
  };
}

// ========== メイン処理 ==========

function doPost(e) {
  try {
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

  // === 画像選択: use_img_{ch}_{num} / skip_img_{ch}_{num} ===
  if (actionId.startsWith('use_img_') || actionId.startsWith('skip_img_')) {
    const parts = actionId.split('_');
    const ch = parts[2];
    const num = parseInt(parts[3]);
    const selected = actionId.startsWith('use_img_');

    setSelection('img_' + ch, num, selected);
    const totals = getTotals(ch);
    const imgCount = countSelected('img_' + ch, totals.images);
    const lineCount = countSelected('line_' + ch, totals.lines);

    const msg = selected
      ? `✅ 画像${num}を選択\n📊 画像: ${imgCount}/${totals.images}枚 | 台本: ${lineCount}/${totals.lines}行`
      : `❌ 画像${num}を除外\n📊 画像: ${imgCount}/${totals.images}枚 | 台本: ${lineCount}/${totals.lines}行`;

    return respond(msg);
  }

  // === 台本行選択: use_line_{ch}_{num} / skip_line_{ch}_{num} ===
  if (actionId.startsWith('use_line_') || actionId.startsWith('skip_line_')) {
    const parts = actionId.split('_');
    const ch = parts[2];
    const num = parseInt(parts[3]);
    const selected = actionId.startsWith('use_line_');

    setSelection('line_' + ch, num, selected);
    const totals = getTotals(ch);
    const imgCount = countSelected('img_' + ch, totals.images);
    const lineCount = countSelected('line_' + ch, totals.lines);

    const msg = selected
      ? `✅ 台本${num}行目を選択\n📊 画像: ${imgCount}/${totals.images}枚 | 台本: ${lineCount}/${totals.lines}行`
      : `❌ 台本${num}行目を除外\n📊 画像: ${imgCount}/${totals.images}枚 | 台本: ${lineCount}/${totals.lines}行`;

    return respond(msg);
  }

  // === 動画生成: generate_{ch} ===
  if (actionId.startsWith('generate_')) {
    const ch = actionId.replace('generate_', '');
    const totals = getTotals(ch);
    const imgCount = countSelected('img_' + ch, totals.images);
    const lineCount = countSelected('line_' + ch, totals.lines);

    if (imgCount === 0 || lineCount === 0) {
      return respond(`⚠️ 画像と台本を選択してください\n現在: 画像${imgCount}枚, 台本${lineCount}行`);
    }

    // GitHub Actions トリガー
    triggerWorkflow(ch, imgCount, lineCount, responseUrl);

    // 選択状態をクリア
    clearSelections('img_' + ch);
    clearSelections('line_' + ch);

    return respond(`🎬 ch${ch}の動画生成を開始！\n画像: ${imgCount}枚 | 台本: ${lineCount}行`);
  }

  // === 再生成: regenerate_{ch} ===
  if (actionId.startsWith('regenerate_')) {
    const ch = actionId.replace('regenerate_', '');
    clearSelections('img_' + ch);
    clearSelections('line_' + ch);
    triggerPrepare(ch, responseUrl);
    return respond('🔄 再生成中...');
  }

  // === スキップ: skip_{ch} ===
  if (actionId.startsWith('skip_')) {
    const ch = actionId.replace('skip_', '');
    clearSelections('img_' + ch);
    clearSelections('line_' + ch);
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

function triggerWorkflow(channelNum, imgCount, lineCount, responseUrl) {
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
      sendToSlack(responseUrl, `✅ ch${channelNum}の動画生成を開始しました！\n画像: ${imgCount}枚 | 台本: ${lineCount}行`);
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
  // 総数を設定
  setTotals('27', 10, 20);

  // 画像選択
  setSelection('img_27', 1, true);
  setSelection('img_27', 2, false);

  // 台本選択
  setSelection('line_27', 1, true);
  setSelection('line_27', 5, false);

  const totals = getTotals('27');
  console.log('画像選択:', countSelected('img_27', totals.images), '/', totals.images);
  console.log('台本選択:', countSelected('line_27', totals.lines), '/', totals.lines);

  // クリア
  clearSelections('img_27');
  clearSelections('line_27');
}

function doGet(e) {
  return ContentService.createTextOutput('GAS is running. Use POST for Slack interactions.');
}
